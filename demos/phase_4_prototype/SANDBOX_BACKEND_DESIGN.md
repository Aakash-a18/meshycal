# MeshyCal Phase 4 Sandbox — Backend Design v0

**File:** `MeshyCal/demos/phase_4_prototype/SANDBOX_BACKEND_DESIGN.md`
**Status:** Detailed implementation spec. Reference material for the backend implementer when sandbox build begins. The higher-level `SANDBOX_ARCHITECTURE.md` is the document for non-technical reading and for feeding into UI design tools.

---

## 1. Goal and Scope of v0

### What the sandbox backend does

The sandbox is an R&D mode layered on top of the existing Phase 4 prototype. Its purpose is to let a developer construct an arbitrary set of synthetic principals, configure each one with its own calendar, policy, and LLM-backed reasoner, fire a scheduling request between any two of them, and watch a real Mesherra negotiation play out — complete with signed ledger entries, scoped payloads, and tessera-fit verification — all from a browser-based editor.

The key difference from the three hardcoded scenarios is authorship. The hardcoded scenarios have fixed principals, fixed calendars, and fixed scripted reasoners. The sandbox lets the developer author all of that at runtime. The Mesherra trust layer, the signed PolicyStore, and the hash-chain ledger are identical underneath; the sandbox is purely additive plumbing above them.

### v0 scope — what is in

- Session lifecycle: create a session (POST), read it (GET), destroy it (DELETE). Sessions are in-memory only; they expire after 60 minutes of idle time and are wiped on uvicorn restart. No disk persistence, no database.
- Principal CRUD: upsert and delete synthetic principals within a session. Each principal carries its own calendar, policy, reasoner configuration, and (optionally) a live API key.
- Three reasoner implementations: `ScriptedReasoner` (reused from `reasoner.py`), `AnthropicReasoner` (new, wraps the `anthropic` Python SDK), `OpenAIReasoner` (new, wraps the `openai` Python SDK; also covers `openai-compatible` self-hosted endpoints via `base_url`).
- Two-party negotiation: the `POST /sandbox/session/{token}/run` endpoint accepts a `SandboxRequestSpec` naming a sender and a recipient, boots a real Mesherra negotiation between them using their configured reasoners, and returns a `SandboxRunResult` the UI can render.
- One cascade hop: if the recipient's calendar has a conflict and its reasoner proposes a reschedule to a third principal, the orchestrator follows that one hop. Maximum cascade depth is 1 in v0.
- Scoped-disclosure invariants hold identically to the hardcoded scenarios.
- API keys are accepted only on `PUT /sandbox/session/{token}/principal/{id}` and are never returned in `GET` responses or written to any log.

### v0 scope — what is deferred to v1

| Deferred | Why |
|---|---|
| Custom policy editing per principal | Requires a policy editor UI; v0 uses default MeshyCal template for all principals |
| Cascade depth > 1 | Complexity and UI rendering of deep chains |
| Persisted sessions | Internal R&D tool; in-memory is sufficient |
| Public demo subset | v1 work |
| Streaming negotiation progress (SSE / WebSocket) | UI receives complete result when run finishes |
| Multi-sender group negotiations | v0 is one sender, one recipient, optional one cascade hop |
| Rate limiting / authentication | Internal R&D only in v0 |
| Reasoner response caching | Each run calls the LLM fresh |

---

## 2. The LLM Provider Abstraction

### 2.1 Extended Protocol

The existing `SchedulingReasoner` Protocol in `reasoner.py` defines one method: `propose_reschedule_target`. The sandbox needs a second method: `evaluate_proposal` — the decision a recipient must make when it receives an inbound proposal.

**New dataclass (added to `reasoner.py`):**

```python
@dataclass(frozen=True)
class ProposalVerdict:
    """What the reasoner decides when evaluating an inbound proposal."""
    accept: bool
    chosen_slot: str | None  # must be one of proposed_candidates if accept=True
    reason: str
```

**Extended Protocol (added to `SchedulingReasoner`):**

```python
def evaluate_proposal(
    self,
    *,
    proposed_candidates: list[str],
    duration_minutes: int,
    current_calendar: list[CalendarEvent],
    requester_principal_id: str,
    context: str | None,
) -> ProposalVerdict:
    ...
```

If `accept=True`, `chosen_slot` must be one of `proposed_candidates`; orchestrator validates this. If `accept=False`, `chosen_slot=None`. `reason` is rendered verbatim in the UI's negotiation trace.

**`ScriptedReasoner.evaluate_proposal`:** iterate `proposed_candidates`; return first that does not collide. Empty match → `ProposalVerdict(accept=False, chosen_slot=None, reason="no proposed slot is free")`.

**`LLMReasoner` stub:** raises `NotImplementedError` (matches existing pattern).

### 2.2 AnthropicReasoner

**Location:** `server/sandbox_reasoners.py`

```python
class AnthropicReasoner:
    def __init__(self, *, api_key: str, model: str = "claude-sonnet-4-6") -> None:
```

No `base_url` (Anthropic SDK doesn't support it). `api_key` stored on `self._api_key`. Never logged. Client constructed per-call (not cached) so key rotation between PUT calls takes effect on next run.

**`propose_reschedule_target` strategy:**
1. Build structured prompt: principal_id, current_calendar (titles included; pre-airlock view), requested_slot, duration, atlas_inferred_free_slots.
2. Ask model for JSON: `{"new_slot": "<ISO>", "blocked_event_title": "...", "reason": "..."}` OR sentinel `{"result": "none"}`.
3. Parse. On failure or sentinel → return `None`.
4. Safety check: if `new_slot` not in `atlas_inferred_free_slots`, return `None` (reject hallucinations).
5. Return `RescheduleProposal(...)`.

**`evaluate_proposal` strategy:**
1. Build structured prompt: proposed_candidates, duration, current_calendar, context.
2. Ask model for JSON: `{"accept": bool, "chosen_slot": "<ISO> or null", "reason": "..."}`.
3. Parse failure → `ProposalVerdict(accept=False, ..., reason="model response unparseable")`.
4. Validate chosen_slot ∈ proposed_candidates if accept=True; else decline.

**API errors:** propagate up; orchestrator wraps in `SandboxReasonerError` → endpoint returns 502 with provider error message. API key never appears in any exception message or log.

### 2.3 OpenAIReasoner

**Location:** `server/sandbox_reasoners.py`

```python
class OpenAIReasoner:
    def __init__(self, *, api_key: str, model: str = "gpt-4o", base_url: str | None = None) -> None:
```

`base_url` non-None → openai-compatible mode. Same class handles both via `openai.OpenAI(api_key=..., base_url=...)`.

Method strategies identical to AnthropicReasoner. When `base_url is None` use `response_format={"type": "json_object"}`; when `base_url is not None` omit it and parse JSON from raw text (self-hosted models may not support structured output).

### 2.4 Factory function

```python
def make_reasoner(principal: SandboxPrincipal) -> SchedulingReasoner:
    """The sole location in the codebase that reads principal.reasoner_api_key."""
    if principal.reasoner_provider == "scripted":
        return ScriptedReasoner()
    if principal.reasoner_provider == "anthropic":
        if not principal.reasoner_api_key:
            raise SandboxConfigError(f"principal {principal.id!r}: anthropic requires api_key")
        return AnthropicReasoner(api_key=principal.reasoner_api_key, model=principal.reasoner_model or "claude-sonnet-4-6")
    if principal.reasoner_provider in ("openai", "openai-compatible"):
        if not principal.reasoner_api_key:
            raise SandboxConfigError(f"principal {principal.id!r}: openai requires api_key")
        return OpenAIReasoner(api_key=principal.reasoner_api_key, model=principal.reasoner_model or "gpt-4o", base_url=principal.reasoner_base_url)
    raise SandboxConfigError(f"unknown reasoner_provider={principal.reasoner_provider!r}")
```

---

## 3. The Principal Config Model

**Location:** `server/sandbox_models.py`

```python
class CalendarEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot_start: str                           # ISO 8601 UTC
    duration_minutes: int = Field(ge=1)
    title: str                                # synthetic label only
    attendee_principal_ids: list[str] = Field(default_factory=list)


class PolicyRuleModel(BaseModel):
    model_config = ConfigDict(extra="allow")  # v0: carried but not enforced
    match: dict[str, Any]
    outbound_allow: list[str] | None = None
    outbound_block: list[str] | None = None
    inbound_allow: list[str] | None = None
    inbound_block: list[str] | None = None
    max_array_size: dict[str, int] | None = None


class PolicyDocModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[PolicyRuleModel] = Field(default_factory=list)


class SandboxPrincipal(BaseModel):
    """One synthetic participant. reasoner_api_key NEVER returned on GET."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    calendar: list[CalendarEventModel] = Field(default_factory=list)
    policy: PolicyDocModel = Field(default_factory=PolicyDocModel)

    reasoner_provider: Literal["scripted", "anthropic", "openai", "openai-compatible"] = "scripted"
    reasoner_model: str | None = None
    reasoner_api_key: str | None = None       # SENSITIVE
    reasoner_base_url: str | None = None      # only for openai-compatible

    @model_validator(mode="after")
    def validate_provider_constraints(self) -> "SandboxPrincipal":
        if self.reasoner_base_url is not None and self.reasoner_provider != "openai-compatible":
            raise ValueError("reasoner_base_url only valid for openai-compatible")
        if self.reasoner_provider == "openai-compatible" and not self.reasoner_base_url:
            raise ValueError("openai-compatible requires reasoner_base_url")
        return self


class SandboxPrincipalPublic(BaseModel):
    """SandboxPrincipal projected for GET responses. api_key omitted."""
    model_config = ConfigDict(extra="forbid")
    id: str
    display_name: str
    calendar: list[CalendarEventModel]
    policy: PolicyDocModel
    reasoner_provider: Literal["scripted", "anthropic", "openai", "openai-compatible"]
    reasoner_model: str | None
    reasoner_base_url: str | None
    # reasoner_api_key intentionally absent
```

**Default models (applied by `make_reasoner` when `reasoner_model` is None):**

| Provider | Default model |
|---|---|
| `scripted` | N/A |
| `anthropic` | `claude-sonnet-4-6` |
| `openai` | `gpt-4o` |
| `openai-compatible` | `gpt-4o` (caller should override) |

---

## 4. The Generic Request Orchestrator

### 4.1 Input/output models

```python
class SandboxRequestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender_id: str
    recipient_id: str
    requested_slot: str             # ISO 8601 UTC
    duration_minutes: int = Field(ge=1, le=480)
    context: str | None = None      # passed to evaluate_proposal


class SandboxNegotiationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_index: int
    step_type: Literal["proposal", "counter_proposal", "cascade_reschedule", "acceptance", "decline"]
    initiator_id: str
    responder_id: str
    proposal_payload: dict[str, Any]      # scoped (post-airlock)
    response_payload: dict[str, Any]
    proposal_payload_hash: str
    response_payload_hash: str
    initiator_ledger_entries: list[ResidueDTO]
    responder_ledger_entries: list[ResidueDTO]
    task_id: str
    reasoner_trace: SandboxReasonerTraceDTO | None


class SandboxReasonerTraceDTO(BaseModel):
    """Nullable variant of the cascading scenario's ReasonerTraceDTO."""
    model_config = ConfigDict(extra="forbid")
    requested_slot: str
    blocking_event_title: str | None = None
    blocking_event_attendee: str | None = None
    proposed_new_slot: str | None = None
    reason: str


class SandboxCalendarDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal_id: str
    display_name: str
    before: list[CalendarEventModel]
    after: list[CalendarEventModel]


class SandboxRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_token: str
    run_id: str

    sender_id: str
    recipient_id: str
    requested_slot: str
    duration_minutes: int

    outcome: Literal["accepted", "declined", "cascade_accepted", "error"]
    chosen_slot: str | None
    failure_reason: str | None

    steps: list[SandboxNegotiationStep]
    calendar_deltas: list[SandboxCalendarDelta]
    principal_ledgers: dict[str, list[ResidueDTO]]
    policy_docs: dict[str, dict[str, Any]]

    duration_ms: int
```

### 4.2 `run_sandbox_request` algorithm (v0)

**Location:** `server/sandbox_orchestrator.py`

Inside one `tempfile.TemporaryDirectory` scoped to the call (matches `run_cascading`).

1. **Validate inputs:** sender/recipient exist in session, differ, `len(session.principals) >= 2`.
2. **Boot Mesherra infra for all session principals:** signer, default MeshyCal policy, PolicyStore, ProvenanceLedger, Mesherra SDK, StaticDirectoryClient. Listeners only for principals that actively receive.
3. **Build reasoners:** `make_reasoner` for sender + recipient. May raise `SandboxConfigError` → 422.
4. **Two-party negotiation:** sender builds rich proposal with `calendar_titles`/`attendee_emails`/etc. Recipient's inbound handler calls `recipient_reasoner.evaluate_proposal(...)`. If accept → `outcome="accepted"`. If decline → empty candidates list → orchestrator sets `outcome="declined"`.
5. **Cascade hop (v0 depth=1):** If recipient's calendar has conflict at requested_slot AND `recipient_reasoner.propose_reschedule_target(...)` returns non-None: find first attendee in conflicting event that's in session AND not the sender → that's the cascade target. Run second bilateral. If cascade target accepts → `outcome="cascade_accepted"`. If declines → `outcome="declined"` with `failure_reason="cascade_target_declined"`. If cascade target would itself need to cascade → `outcome="declined"` with `failure_reason="cascade_depth_exceeded"`.
6. **Calendar deltas:** Compute per-principal before/after. Orchestrator does NOT mutate `session.principals[id].calendar` (runs are idempotent from session's perspective).
7. **Collect ledgers + policy docs.**
8. **Close stores/ledgers before tempdir exits.**
9. **Return SandboxRunResult.**

### 4.3 Error wrapping

Endpoint wraps unexpected exceptions in:
```json
{"detail": {"error": "orchestration_failed", "run_id": "<uuid>", "message": "<repr>"}}
```
API keys never appear in `str(e)` — reasoners ensure this by never formatting the key into exception messages.

---

## 5. Session State Model

**Location:** `server/sandbox_session.py`

```python
class SandboxSession(BaseModel):
    token: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    principals: dict[str, SandboxPrincipal] = Field(default_factory=dict)
    run_log: list[str] = Field(default_factory=list)


class SandboxSessionStore:
    """In-memory session registry. Singleton on app.state."""
    TTL_SECONDS: int = 3600

    def __init__(self) -> None:
        self._sessions: dict[str, SandboxSession] = {}

    def create(self, default_principals: list[SandboxPrincipal]) -> SandboxSession: ...
    def get(self, token: str) -> SandboxSession | None: ...  # lazy-evicts expired
    def delete(self, token: str) -> bool: ...
    def _evict_expired(self) -> None: ...  # called from .get()
```

**Default principals on session boot:** Iris and Marius with synthetic calendars (Iris: morning-standup at 09:00, focus-block at 11:00; Marius: weekly-review at 10:00, project-sync at 14:00 with `atlas@meshycal.demo` as attendee). All synthetic data — no real names or emails.

---

## 6. New FastAPI Endpoints

All under `/sandbox`. Added to existing `app` in `main.py`. Existing `/scenarios/*` untouched.

| Method + Path | Body | Returns | Notes |
|---|---|---|---|
| `POST /sandbox/session` | `SandboxSessionCreateRequest` (optional, empty in v0) | `SandboxSessionPublic` | 201; pre-populated with 2 default principals |
| `GET /sandbox/session/{token}` | none | `SandboxSessionPublic` | 200; api_keys scrubbed |
| `PUT /sandbox/session/{token}/principal/{id}` | `SandboxPrincipal` (includes api_key) | `SandboxPrincipalPublic` | 200 or 201; api_key in body, never in response |
| `DELETE /sandbox/session/{token}/principal/{id}` | none | `{"deleted": true, "id": "..."}` | 200; 409 if would leave <2 principals |
| `POST /sandbox/session/{token}/run` | `SandboxRequestSpec` | `SandboxRunResult` | 200 |
| `DELETE /sandbox/session/{token}` | none | `{"deleted": true, "token": "..."}` | 200 |

### Error envelope

```python
class SandboxErrorDetail(BaseModel):
    error: str          # snake_case code
    message: str
    run_id: str | None = None     # orchestration_failed only
    provider: str | None = None   # reasoner_api_error only
```

Standard error responses:
- 404 session not found / expired
- 422 config invalid (Pydantic validation, missing api_key, sender == recipient)
- 502 reasoner_api_error (Anthropic / OpenAI 4xx/5xx)
- 500 orchestration_failed (unexpected)
- 409 cannot delete principal (would leave < 2 in session)

---

## 7. Test Plan

**Location:** `tests/test_sandbox.py`

No live API calls. Mock `anthropic.Anthropic.messages.create` and `openai.OpenAI.chat.completions.create`.

**Categories:**
- Unit: `ScriptedReasoner.evaluate_proposal` (accepts free, declines busy, accepts on empty calendar)
- Unit: `AnthropicReasoner` mocked — parse success, sentinel, hallucinated slot rejected, accept/decline branches, parse failure → decline
- Unit: `OpenAIReasoner` mocked — same set, plus `openai-compatible` omits `response_format`
- Unit: `make_reasoner` — all four providers, missing api_key error, openai-compatible base_url validation
- Integration: session lifecycle via `httpx.AsyncClient` + `ASGITransport`
- Integration: `api_key` never appears in any `GET` response (full-body string scan)
- Contract: `run_sandbox_request` scoped-disclosure invariants (titles/emails stripped, tessera-fit holds)
- Contract: scripted two-party acceptance / decline / cascade-accepted scenarios

---

## 8. What to Leave Untouched

- **Mesherra trust layer.** Zero Python changes.
- **`server/scenarios.py`, `server/cascading.py`, `server/group_negotiation.py`.** All three hardcoded scenarios unchanged.
- **Existing `main.py` endpoints** (`/healthz`, `/scenarios/*`). Sandbox endpoints added; existing not modified or removed.
- **Existing `SchedulingReasoner.propose_reschedule_target` signature.** `evaluate_proposal` is additive.
- **`index.html`.** Sandbox lives at `sandbox.html`, separate file.
- **All existing test files.** New file `test_sandbox.py` only.

---

## 9. File Layout

```
demos/phase_4_prototype/
├── sandbox.html                         # NEW (frontend work)
├── SANDBOX_BACKEND_DESIGN.md            # THIS FILE
├── SANDBOX_ARCHITECTURE.md              # higher-level reference
└── server/
    ├── reasoner.py                      # ADD: ProposalVerdict, evaluate_proposal
    ├── main.py                          # ADD: 6 sandbox endpoints, lifespan boot
    ├── sandbox_models.py                # NEW: all Pydantic models, no Mesherra imports
    ├── sandbox_session.py               # NEW: in-memory session store
    ├── sandbox_reasoners.py             # NEW: AnthropicReasoner, OpenAIReasoner, make_reasoner
    └── sandbox_orchestrator.py          # NEW: run_sandbox_request

tests/
└── test_sandbox.py                      # NEW: all §7 tests
```

### Import dependency graph (acyclic)

```
sandbox_models.py        ← (no internal imports)
sandbox_session.py       ← sandbox_models.py
sandbox_reasoners.py     ← reasoner.py + sandbox_models.py
sandbox_orchestrator.py  ← all the above + scenarios.py (for helpers) + cascading.py (for DTOs) + mesherra.*
main.py                  ← sandbox_models.py + sandbox_session.py + sandbox_orchestrator.py
reasoner.py              ← stdlib only (extended additively)
```

### `pyproject.toml` additions

Add optional extras:
```toml
[project.optional-dependencies]
sandbox = ["anthropic>=0.25", "openai>=1.30"]
```

Server boots regardless of whether sandbox deps are installed; missing-dep errors surface on first use (clear message via `SandboxConfigError`).

---

## Key design decisions (rationale)

1. **`evaluate_proposal` added to Protocol.** Sandbox inbound handlers need each principal's reasoner to decide acceptance, not just whether to reschedule. Existing `propose_reschedule_target` only covers the "can I move something?" question.

2. **API keys read exactly once** — in `make_reasoner` — and passed directly to SDK constructor. Never on `app.state`, never in any result model, never in any log string. Reasoner object holds key on a private attribute. Session deletion drops it.

3. **`SandboxPrincipalPublic` is a separate model** (not a `model_dump(exclude={...})` call). Pydantic's `extra="forbid"` catches accidental additions at validation time, not silently at serialization.

4. **Orchestrator does NOT mutate session calendar after a run.** Runs are idempotent from session's perspective. Calendar deltas are display-only. Applying mutations is a v1 feature.

5. **Cascade depth cap of 1 enforced by not recursing.** Cleaner than tracking depth as a parameter.

---

*End of spec. Reference material for the implementer. The higher-level `SANDBOX_ARCHITECTURE.md` is the document for non-technical reading and UI design.*
