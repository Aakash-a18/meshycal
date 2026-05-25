# MeshyCal Sandbox — Architecture

**Purpose:** A reference document the UI designer (in Claude Design) and the backend implementer both read. Defines what the sandbox is, what the conceptual entities are, what the screens do, what data flows between browser and backend, and what's in v0 vs v1.

**Audience:** Non-technical strategy lead + the implementing agents. Reads top-to-bottom.

---

## 1. What the sandbox is

The sandbox is a **separate page** (`sandbox.html`) where a person can:

1. Create / edit synthetic principals (Iris, Marius, Atlas, anyone).
2. Edit each principal's calendar.
3. Edit each principal's policy (what fields may leave / arrive; how aggressive their agent may be).
4. Choose each principal's reasoner — what runs the "thinking" for that principal's agent. Options:
   - `scripted` (deterministic Python; free; offline)
   - `anthropic` (real Claude API; needs a key)
   - `openai` (real GPT API; needs a key)
   - `openai-compatible` (self-hosted / proxy / Ollama; needs base URL + key)
5. Fire arbitrary scheduling requests between principals.
6. Watch the negotiation play out, with the same narrative / agent-dialogue / tessera-fit visualization used in the existing demo (`index.html`), but generalized to N principals.

It is the **R&D mode**. You use it to test ideas, demo specific setups, and explore failure modes. A curated public demo subset is **v1** — out of scope here.

The Mesherra trust layer underneath is unchanged. Each bilateral exchange still goes through scoped disclosure, signed receipts, and tessera-fit hash matching. The sandbox is purely a new UI + new orchestration layer on top of the existing trust primitives.

---

## 2. The conceptual model

Six core entities. Everything flows through these.

### 2.1 Principal

A synthetic person whose agent participates in scheduling. Has:
- **id** — unique identifier, e.g. `iris@meshycal.demo` (used in receipts, hashes, ledger entries)
- **display_name** — what the UI shows, e.g. `Iris`
- **calendar** — a list of `CalendarEvent`s (see 2.2)
- **policy** — a `PolicyDoc` (see 2.3) governing what their airlock lets out and in
- **reasoner_config** — provider + model + API key + optional base URL (see 2.4)

### 2.2 CalendarEvent

One block on a principal's calendar.
- **start_iso** — ISO 8601 UTC timestamp, e.g. `2026-06-02T14:00:00Z`
- **duration_minutes** — integer
- **title** — synthetic label, e.g. `synthetic-project-sync`
- **attendee_principal_ids** — list of other principals also on this meeting (optional; empty = solo)

### 2.3 PolicyDoc

Same shape as the existing Phase 3 `mesherra.policy/doc-v1`, with one new field in v0: an `autonomy` section.

Conceptually:
- **outbound_allow** — fields permitted to leave on outbound proposals
- **outbound_block** — fields forbidden from leaving (calendar_titles, attendee_emails by default)
- **inbound_allow** — fields permitted on inbound proposals
- **max_array_size** — caps on array fields (e.g. candidates ≤ 5)
- **autonomy** *(new)* — how much my agent may act on its own:
  - `max_cascade_depth: 0 | 1 | 2 | 3` — how many hops of rescheduling the agent may chain before checking back with me. `0` = no rescheduling autonomy at all (must accept or decline); `1` = may move one of my own meetings; `2` = may chain one more level; etc.
  - *(v1)* `no_touch_counterparts`, `reschedule_budget_per_request`, etc.

### 2.4 ReasonerConfig

Which engine drives this principal's agent thinking.
- **provider** — one of `scripted` / `anthropic` / `openai` / `openai-compatible`
- **model** — model name string (e.g. `claude-sonnet-4-6`, `gpt-4o`, `llama3-8b-instruct`); ignored for `scripted`
- **api_key** — the secret. Sensitive. **Lives in memory only.** Never persisted server-side, never logged, never returned in any `GET` response. The browser sends it on each request and the server discards it after use.
- **base_url** — optional; only for `openai-compatible` providers

### 2.5 RequestSpec

What gets fired when the user presses "Fire request".
- **sender_id** — which principal is asking
- **recipient_id** — which principal is being asked
- **requested_slot_iso** — the proposed start time
- **duration_minutes** — meeting length
- **context_note** *(optional)* — short free-text describing what the meeting is for; if present, an LLM-backed reasoner may use it in its prompt

### 2.6 RunResult

What comes back from the backend after a request completes. The shape the UI renders.
- **success** — `true | false`
- **failure_reason** — `null` on success; otherwise a string the UI shows verbatim ("recipient declined", "cascade aborted: reasoner returned None", etc.)
- **chosen_slot_iso** — the agreed slot on success
- **dialogue** — ordered list of inter-agent messages with sender, recipient, direction (`proposal | acceptance | rejection | counter | reasoning`), and human-readable body
- **exchanges** — list of `BilateralExchangeDTO`s (sender, recipient, proposal hash, acceptance hash, task_id) — the cryptographic record
- **ledgers** — per-principal list of `ResidueDTO` entries (the signed receipts on each side)
- **calendar_deltas** — per-principal `before` / `after` calendar snapshots; the UI animates the transition
- **reasoner_trace** *(optional)* — captured if any LLM reasoner was used in the run (full reason text for each call)
- **duration_ms** — wall-clock time

The shape is intentionally a generalization of the existing `CascadingResult` (the cascading scenario's result). The UI's existing narrative/dialogue/tessera-fit code can render it with minimal changes.

---

## 3. The user flow

Open `sandbox.html` →

1. **Header** shows: `MeshyCal · Sandbox` + a back link to the main demo.
2. **Editor region** (left or top, designer's call): list of principal cards. By default a fresh session has three principals seeded — Iris, Marius, Atlas. The user can click any card to expand its editor inline (or in a side drawer).
3. **Request initiator** (right or below editor): a small form. Sender dropdown, recipient dropdown, slot+duration inputs, optional context note, "Fire request" button.
4. **Live run region** (the main visualization): when a run fires, this area animates the negotiation using the same narrative-band + agent-dialogue + tessera-fit machinery from `index.html`, but built dynamically from the actual principals involved in the run. After the run, the ledger entries and calendar deltas remain visible.

A "Reset session" button in the header nukes the session state and reloads with the default three principals.

---

## 4. The screens (logical, not pixel-specific)

### 4.1 Principal card (collapsed)

Compact summary:
- Avatar (initials) + display name
- Mini calendar preview (small dots / strip showing the day's busy blocks)
- Policy summary: a one-line phrase like "outbound: candidates + duration · blocks titles + emails · cascade depth 1"
- Reasoner provider badge ("scripted" or "claude" or "openai")
- Click to expand

### 4.2 Principal card (expanded — editor)

Three sub-sections, vertically stacked:

**Calendar editor**
- A list of events. Each event row: time picker, duration field, title input, attendees multi-select.
- "+ Add event" button.
- Per-event delete.

**Policy editor**
- Three text-area / multi-select inputs for `outbound_allow`, `outbound_block`, `inbound_allow`. Pre-filled with the default MeshyCal template values.
- A small "+ field" button on each list.
- A `max_array_size` row for `candidates` with a number input.
- A new `autonomy.max_cascade_depth` selector (radio buttons 0 / 1 / 2 / 3 with one-line descriptions of each).

**Reasoner editor**
- Provider dropdown (4 options).
- Model name input (conditional: shown for non-scripted).
- API key input (`type="password"`, with a small visible eye-toggle for "show key", and a warning line: "API keys stay in your browser and in this server's memory. They are never logged or persisted.").
- Base URL input (only shown for `openai-compatible`).

### 4.3 Request initiator

Compact form near the visualization region:
- Sender (dropdown of session principals)
- Recipient (dropdown; can't equal sender)
- Day + time (or a single datetime-local input)
- Duration (number input, minutes; default 30)
- Context note (optional one-line text input; "for the meeting context — fed to LLM reasoners if used")
- **Fire request** button. Disabled while a run is in progress.

### 4.4 Live run region

Reuses the existing visualization, generalized:

- **Narrative band** at the top: tells the story in plain English ("Iris is requesting a 30-min slot from Marius on Tuesday at 14:00. Marius's reasoner is checking…"). Updates as the run progresses through beats. On failure: "Run aborted. <reason>".
- **Per-principal calendar strip** (one mini calendar per principal involved): shows their `before` state, then animates to their `after` state after the run completes.
- **Agent dialogue transcript** below: each inter-agent message appears as a row with timestamp, sender label, direction badge, and body text. Per-agent left-border color (assigned dynamically from a palette).
- **Tessera-fit badges**: one inline badge per bilateral exchange that succeeded. Shows both payload hashes side by side (truncated).
- **Ledger panel**: per-principal ledger (collapsible if N > 3). Each entry shows the signed Residue.
- **Reasoner trace inspector** (if any LLM was used): a collapsible panel showing what each LLM call was asked and how it responded, verbatim.

### 4.5 Session header / footer

- Top: brand + back-to-demo link + "Reset session" button + small "● connected" or "○ offline" badge for the backend.
- Bottom: a colophon noting that API keys are session-only and never persisted.

---

## 5. Backend API surface

All paths under `/sandbox`. JSON in, JSON out. Errors return `{detail: "..."}` with a non-2xx status code.

### 5.1 Session lifecycle

```
POST   /sandbox/session
   → returns { token: str, principals: [Principal, Principal, Principal] }
     (token is a UUID; default three principals — Iris, Marius, Atlas — are seeded)

GET    /sandbox/session/{token}
   → returns { token, principals: [...] }
     (api_key fields stripped from response; UI never sees them again after typing)

DELETE /sandbox/session/{token}
   → 204; clears server-side state for that session
```

### 5.2 Principal CRUD

```
PUT    /sandbox/session/{token}/principal/{principal_id}
   body: full Principal object (including api_key if user typed one)
   → returns updated Principal (api_key stripped from response)

DELETE /sandbox/session/{token}/principal/{principal_id}
   → 204
```

### 5.3 Run a request

```
POST   /sandbox/session/{token}/run
   body: RequestSpec
   → returns RunResult
```

On any exception → 500 with `{detail: "<message>"}`. The UI shows the detail verbatim in the narrative band.

### 5.4 Sensitive-data discipline

The `api_key` field is `WriteOnly` in API terms: the client `PUT`s it; the server uses it; subsequent `GET`s never return it. The server keeps it in an in-memory dict keyed by session token. When the session is deleted (or uvicorn restarts), it's gone.

The server does NOT log keys. Even on errors. Reasoner-side exceptions are caught and re-raised with the key elided from the message.

---

## 6. The LLM provider abstraction

All four reasoners satisfy the existing `SchedulingReasoner` protocol from `server/reasoner.py`. v0 adds:

```python
class AnthropicReasoner:
    def __init__(self, *, api_key, model="claude-sonnet-4-6"):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
    def propose_reschedule_target(self, **kwargs) -> RescheduleProposal | None:
        # Build structured prompt from kwargs (requested_slot, calendar,
        # atlas_inferred_free_slots, etc.). Call self._client.messages.create
        # with tool_use / structured output targeting the RescheduleProposal
        # shape. Return parsed result or None.

class OpenAIReasoner:
    def __init__(self, *, api_key, model="gpt-4o", base_url=None):
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
    def propose_reschedule_target(self, **kwargs) -> RescheduleProposal | None:
        # Same shape, OpenAI Chat Completions or Responses API with
        # response_format json_schema or function-calling.
```

The orchestrator picks a reasoner per principal based on `ReasonerConfig.provider`:

```
scripted          → ScriptedReasoner()
anthropic         → AnthropicReasoner(api_key=..., model=...)
openai            → OpenAIReasoner(api_key=..., model=...)
openai-compatible → OpenAIReasoner(api_key=..., model=..., base_url=...)
```

This means a future fifth provider (e.g. `local-llama` direct call) adds one class and one branch — no other code changes.

For v0 the only protocol method is `propose_reschedule_target` (existing). v0.1 may add `should_accept_proposal` and `find_candidate_slots` so the LLM can drive more of the agent's behavior.

---

## 7. The orchestrator (generalized)

Replaces the three hardcoded scenarios with one generic function:

```python
async def run_sandbox_request(
    session: SandboxSession,
    request: RequestSpec,
) -> RunResult:
```

Logic (v0):

1. Validate: sender ≠ recipient; both exist in session; slot is in the future.
2. Build Mesherra principals for everyone in the session (signers, ledgers, policy stores, directory all in a tempdir).
3. Apply each principal's policy + reasoner config.
4. Boot the recipient's listener. (Other principals get listeners booted lazily if the cascade extends to them.)
5. Run the bilateral: sender → recipient. The recipient's reasoner is invoked inside its handler.
6. If the recipient's reasoner returns `accept` directly: one bilateral, done.
7. If the recipient is busy AND their policy allows cascade (`max_cascade_depth ≥ 1`): the recipient's reasoner picks a conflict-holder and a candidate new slot for it; recipient → conflict-holder bilateral fires; if accepted, recipient now accepts the original sender. Two bilaterals, one cascade hop.
8. If `max_cascade_depth ≥ 2`: the conflict-holder may itself cascade once. v0 caps at depth 1; v0.1 generalizes.
9. Assemble the RunResult: collect dialogue messages, ledger entries, calendar deltas, tessera fits.
10. Return.

On any exception: catch in the FastAPI endpoint, return 500 with `{detail: ...}`.

---

## 8. Security model (v0)

- API keys typed by the user are sent over HTTPS (in production) to the backend, used for that one request, then discarded from memory.
- Keys are NOT stored in any database, NOT persisted to disk, NOT included in logs.
- The backend's session dict holds the key only while the session is alive. Session destruction (explicit DELETE, server restart, idle TTL of 1 hour) drops the key.
- The UI's localStorage stores the session token but NEVER the API key. After a page reload the user must re-enter their key.
- The browser-side code does NOT make direct LLM API calls. All LLM traffic originates from the backend. This keeps the key off the public network beyond the user → backend hop.
- A small warning banner near the API key inputs reinforces this: "API keys stay in your browser and in this server's memory. They are never logged or persisted."

---

## 9. Aesthetic constraints

The sandbox must feel like part of the same project as the existing prototype.

- Fonts: Fraunces (display), Newsreader (body), IBM Plex Mono (data).
- Palette: parchment cream (`hsl(40 28% 91%)`), deep ink (`hsl(222 28% 11%)`), terracotta (`hsl(13 60% 50%)`), jade (`hsl(155 30% 33%)`), gold (`hsl(40 70% 53%)`).
- No external UI libraries (no shadcn, no material, no bootstrap). Pure HTML + CSS + vanilla JS, single-file `sandbox.html` consistent with the existing single-file `index.html`.
- Reuse the editorial archival voice. Buttons in IBM Plex Mono uppercase letter-spaced. Headings in Fraunces italic with optical sizing. Data in Plex Mono.
- Reuse existing CSS class patterns where they fit (`.ledger`, `.calendar`, `.event`, `.party`, `.tessera-fit-overlay`).
- New CSS class prefix: `sb-` for sandbox-specific styles.

---

## 10. v0 scope cut vs deferred to v1

### In v0

- Three default principals on first session boot (Iris, Marius, Atlas).
- Edit calendar, policy, reasoner config per principal.
- Add / delete principals (up to maybe 6 in v0 — UI starts to break beyond that).
- Reasoner providers: `scripted`, `anthropic`, `openai`, `openai-compatible`.
- Request fire: 2-party or 1-hop cascade (depth ≤ 1).
- In-memory session state; idle TTL 1 hour; explicit reset.
- Live visualization reuses existing narrative + dialogue + tessera-fit infra.
- Multi-provider tests with mocked clients (no live keys in CI).

### Deferred to v1

- Curated public-demo subset (a stripped-down sandbox that hides the editor and offers pre-baked scenarios).
- Persistent sessions (save/load).
- Multi-party group find (4+ principals in a single request).
- Cancel / reschedule of existing meetings as request types.
- Deeper autonomy bounds (no-touch counterparts, reschedule budgets, time windows).
- 2-hop and 3-hop cascades.
- Per-principal API key encryption-at-rest (when persistence lands).

### Explicitly NOT in scope (long-term roadmap, separate work)

- A real Anthropic-API-cost dashboard or rate limiter.
- Mobile app.
- Multi-user collaboration (multiple humans in one session).
- Production deployment.

---

## 11. What stays the same (architectural invariants)

These do not change as the sandbox lands:

- **Mesherra trust layer.** Zero Python changes there. The sandbox calls into the existing `Mesherra` SDK exactly the way the three demo scenarios do.
- **Scoped disclosure.** Phase 3 outbound/inbound policy still strips fields before signing. The sandbox's policy editor is a UI on top of the existing `mesherra.policy/doc-v1` schema.
- **Tessera-fit invariant.** Each bilateral exchange still produces two matching `payload_hash` values across the two principals' ledgers.
- **Hash-chained Residue.** Each principal's ledger is one chain across all task_ids.
- **No real user data.** Every principal id ends `@meshycal.demo`. Every default calendar entry is prefixed `synthetic-`. The user can create custom names but is gently nudged toward synthetic-style ids.
- **Dependency direction.** Sandbox code lives entirely under `MeshyCal/demos/phase_4_prototype/`. Mesherra does not import from MeshyCal. Ever.

---

## 12. File layout (when implemented)

```
MeshyCal/demos/phase_4_prototype/
├── sandbox.html                              # NEW: the sandbox page
├── SANDBOX_ARCHITECTURE.md                   # this document
├── SANDBOX_BACKEND_DESIGN.md                 # detailed backend spec (ideator output)
├── SANDBOX_FRONTEND_DESIGN.md                # detailed frontend spec (ideator output)
├── server/
│   ├── sandbox.py                            # NEW: generic orchestrator + session state
│   ├── reasoner_anthropic.py                 # NEW: AnthropicReasoner
│   ├── reasoner_openai.py                    # NEW: OpenAIReasoner (also handles openai-compatible)
│   ├── reasoner.py                           # EXISTING: extended with the new reasoner picker
│   └── main.py                               # EXTENDED: adds /sandbox/* endpoints
└── tests/
    ├── test_sandbox_reasoners.py             # NEW: mocked LLM client tests
    ├── test_sandbox_orchestrator.py          # NEW: end-to-end run with scripted reasoner
    └── test_sandbox_endpoints.py             # NEW: session lifecycle + run endpoint
```

---

## 13. What the Claude-Design UI work needs from this doc

The most important pieces for designing the sandbox UI:

1. **The conceptual model (§2)** — the entities you're rendering: Principal, Calendar, CalendarEvent, PolicyDoc, ReasonerConfig, RequestSpec, RunResult.
2. **The user flow (§3)** — what the user does step by step.
3. **The screens (§4)** — what regions the page has and what each does.
4. **The aesthetic constraints (§9)** — fonts, palette, no UI libs.
5. **The RunResult shape (§2.6)** — what the visualization region renders. The existing `index.html` already has the machinery; the sandbox's challenge is making it data-driven instead of scenario-specific.

The UI design produced in Claude Design should be a single HTML file (or HTML + a small accompanying CSS/JS file) consistent with the existing `index.html` aesthetic. The implementer will wire it to the backend API surface (§5) once both this design and the backend land.

---

*End of MeshyCal Sandbox Architecture document.*
