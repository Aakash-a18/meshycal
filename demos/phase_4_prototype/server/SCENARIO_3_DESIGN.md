# Scenario 3 Design — Cascading Reschedule with Scripted Deterministic Reasoner

## 1. Goal

Scenario 3 proves that MeshyCal agents can exhibit agentic behavior — autonomous multi-step reasoning and downstream negotiation — while remaining fully grounded in Mesherra's trust layer. Concretely: Iris asks Marius for a meeting at a slot Marius has already committed to Atlas; Marius' scheduling agent detects the conflict, reasons about whether it can free the slot by moving the Atlas meeting, picks a candidate replacement time, negotiates the move with Atlas (a second independent bilateral exchange), and only after Atlas confirms does Marius accept Iris' original request. The UI shows the reasoning trace inline so observers can follow the agent's decision chain. The entire cascade is composed of chained two-party Mesherra exchanges — Mesherra itself is unchanged; the "agent" is simply an async Python function that calls the existing `sdk.send_to` twice in the correct order from inside Marius' inbound handler. This demonstrates that agentic scheduling behavior does not require a new trust primitive: it requires a reasoner that decides when and what to negotiate next, wired into the existing inbound-handler callback.

## 2. The Cascade Pattern

The cascade runs inside a single async call to `run_cascading()`. All three principals (Iris, Marius, Atlas) boot their Mesherra instances and listeners before the first `send_to` call. Marius' inbound handler is the cascade's pivot point: it calls `await marius_sdk.send_to(atlas_url, ...)` before returning its response to Iris, holding Iris' A2A task open during the Atlas round-trip.

### Step 1 — Iris proposes to Marius

`await iris_sdk.send_to(marius_url, payload=iris_rich_proposal, operation=PROPOSAL)`

Iris' rich proposal payload (pre-airlock):
```json
{
  "candidates":        ["2026-06-02T14:00:00Z"],
  "duration_minutes":  30,
  "calendar_titles":   ["synthetic-morning-standup"],
  "attendee_emails":   ["synthetic-iris-attendee@example.invalid"],
  "constraint_hints":  {"tz": "Europe/Paris", "preferred_window": {"start_hour": 9, "end_hour": 18}}
}
```

After Iris' policy engine scopes this outbound, the wire payload is:
```json
{
  "candidates":       ["2026-06-02T14:00:00Z"],
  "duration_minutes": 30,
  "constraint_hints": {"tz": "Europe/Paris", "preferred_window": {"start_hour": 9, "end_hour": 18}}
}
```

(`calendar_titles` and `attendee_emails` blocked outbound by the default MeshyCal policy template, identical to scenario 1.) This initiates A2A task `task_id_1`.

### Step 2 — Marius' agent reasons

Marius' inbound handler fires. Before doing anything else, it calls:

```python
proposal = reasoner.propose_reschedule_target(
    requested_slot="2026-06-02T14:00:00Z",
    requested_duration_minutes=30,
    current_calendar=MARIUS_SYNTHETIC_CALENDAR,
    atlas_principal_id=ATLAS,
    atlas_inferred_free_slots=ATLAS_INFERRED_FREE_SLOTS,
)
```

`ScriptedReasoner` scans Marius' calendar, finds `synthetic-project-sync` at `14:00` with Atlas as a co-attendee, checks the free-slot list, picks `2026-06-02T16:00:00Z` (not in Marius' calendar, first in Atlas' free list), and returns a `RescheduleProposal` with a formatted `reason` string for the UI.

If `reasoner` returns `None`, the handler raises `CascadeAbortedError` immediately. No further Mesherra calls.

### Step 3 — Marius proposes the reschedule to Atlas

Still inside `marius_handler`, before returning to Iris:

```python
atlas_result = await marius_sdk.send_to(
    peer_url=atlas_url,
    peer_principal_id=ATLAS,
    payload={
        "candidates":       [proposal.new_slot],
        "duration_minutes": 45,
        "constraint_hints": {"reason": "synthetic-reschedule-for-new-request"},
    },
    payload_schema=PAYLOAD_SCHEMA,
    operation=Operation.PROPOSAL,
)
```

This initiates A2A `task_id_2`.

### Step 4 — Atlas accepts deterministically

Atlas' handler picks the first candidate unconditionally and returns acceptance. `task_id_2` completes.

### Step 5 — Marius' ledger records the Atlas exchange

Marius' Outbound Gateway appended two residue entries for `task_id_2`: seq 1 (EMIT/proposal to Atlas) and seq 2 (RECEIVE/acceptance from Atlas).

### Step 6 — Marius accepts Iris' original request

`marius_handler` returns `OutgoingResponse(payload={"candidates": ["2026-06-02T14:00:00Z"], "duration_minutes": 30}, operation=Operation.ACCEPTANCE)`. Marius' Inbound Gateway writes seq 3 (EMIT/acceptance to Iris, `task_id_1`). Iris' Outbound Gateway writes seq 1 (RECEIVE/acceptance from Marius, `task_id_1`).

### Ledger entry table

| Principal | seq | task_id   | action_type | operation  | actor  | counterpart |
|-----------|-----|-----------|-------------|------------|--------|-------------|
| Iris      | 0   | task_id_1 | emit        | proposal   | iris   | marius      |
| Iris      | 1   | task_id_1 | receive     | acceptance | marius | iris        |
| Marius    | 0   | task_id_1 | receive     | proposal   | iris   | marius      |
| Marius    | 1   | task_id_2 | emit        | proposal   | marius | atlas       |
| Marius    | 2   | task_id_2 | receive     | acceptance | atlas  | marius      |
| Marius    | 3   | task_id_1 | emit        | acceptance | marius | iris        |
| Atlas     | 0   | task_id_2 | receive     | proposal   | marius | atlas       |
| Atlas     | 1   | task_id_2 | emit        | acceptance | atlas  | marius      |

8 entries total. Iris: 2, Marius: 4, Atlas: 2. Two A2A task IDs.

### Three signed bilateral exchanges

- **Exchange A — Iris→Marius proposal** (part of `task_id_1`)
- **Exchange B — Marius↔Atlas reschedule** (`task_id_2`)
- **Exchange C — Marius→Iris acceptance** (part of `task_id_1`)

Exchanges A and C share `task_id_1`. The Marius ledger is one hash chain across both task IDs.

## 3. The Scripted Reasoner

File: `server/reasoner.py`

```python
"""Scheduling reasoner Protocol and scripted v0 implementation.

The Protocol is the seam between the v0 scripted demo and a future LLM-backed
implementation. Any object satisfying SchedulingReasoner can be injected into
run_cascading() without changing the orchestrator.

LLM swap-in contract (documented, not enforced at runtime):
  An LLMReasoner implementing this Protocol would:
  1. Accept an LLM client (Anthropic/OpenAI SDK instance) at construction.
  2. Build a structured prompt from the keyword arguments.
  3. Call the model with structured-output mode targeting RescheduleProposal.
  4. Return RescheduleProposal on success, None when no viable slot exists.
  The orchestrator never changes; the `reason` field is the model's verbatim
  natural-language explanation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class CalendarEvent:
    """A synthetic calendar entry. No real user data."""
    slot_start: str                         # ISO 8601 UTC
    duration_minutes: int
    title: str                              # synthetic label
    attendee_principal_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RescheduleProposal:
    """What the reasoner proposes when it decides to move an existing meeting."""
    new_slot: str
    blocked_event_title: str
    reason: str


class SchedulingReasoner(Protocol):
    """Interface all reasoner implementations must satisfy.

    Pure function semantics; no I/O, no randomness, no side effects.
    Keyword-only arguments so new optional inputs are backward-compatible.
    """

    def propose_reschedule_target(
        self,
        *,
        requested_slot: str,
        requested_duration_minutes: int,
        current_calendar: list[CalendarEvent],
        atlas_principal_id: str,
        atlas_inferred_free_slots: list[str],
    ) -> RescheduleProposal | None:
        ...


class ScriptedReasoner:
    """Deterministic v0 implementation.

    Algorithm:
    1. Find the event in current_calendar at requested_slot.
    2. Confirm atlas_principal_id is a co-attendee.
    3. Pick the first slot in atlas_inferred_free_slots that doesn't collide
       with current_calendar.
    4. Return RescheduleProposal with a formatted reason string.
    Returns None on any miss (no conflict; wrong attendee; no viable slot).
    """

    def propose_reschedule_target(
        self,
        *,
        requested_slot: str,
        requested_duration_minutes: int,
        current_calendar: list[CalendarEvent],
        atlas_principal_id: str,
        atlas_inferred_free_slots: list[str],
    ) -> RescheduleProposal | None:
        blocking: CalendarEvent | None = None
        for event in current_calendar:
            if event.slot_start == requested_slot:
                blocking = event
                break
        if blocking is None:
            return None
        if atlas_principal_id not in blocking.attendee_principal_ids:
            return None
        occupied = {e.slot_start for e in current_calendar}
        for candidate in atlas_inferred_free_slots:
            if candidate not in occupied:
                return RescheduleProposal(
                    new_slot=candidate,
                    blocked_event_title=blocking.title,
                    reason=(
                        f"busy at requested slot {requested_slot} with "
                        f"{atlas_principal_id} for \"{blocking.title}\"; "
                        f"proposing to move that meeting to {candidate}, "
                        "which is free on both calendars"
                    ),
                )
        return None


class LLMReasoner:
    """Future Phase 4.5 implementation. Documented seam only."""

    def propose_reschedule_target(self, **kwargs: object) -> RescheduleProposal | None:
        raise NotImplementedError(
            "LLMReasoner is the Phase 4.5 implementation. "
            "Inject ScriptedReasoner() for v0."
        )
```

## 4. Synthetic Calendars

Module-level constants in `server/cascading.py`. Immutable, no env vars, no I/O.

```python
IRIS   = "iris@meshycal.demo"
MARIUS = "marius@meshycal.demo"
ATLAS  = "atlas@meshycal.demo"

IRIS_SYNTHETIC_CALENDAR: list[CalendarEvent] = [
    CalendarEvent("2026-06-02T09:00:00Z", 60, "synthetic-morning-standup", []),
    CalendarEvent("2026-06-02T11:00:00Z", 30, "synthetic-focus-block", []),
]

MARIUS_SYNTHETIC_CALENDAR: list[CalendarEvent] = [
    CalendarEvent("2026-06-02T10:00:00Z", 60, "synthetic-weekly-review", []),
    CalendarEvent("2026-06-02T14:00:00Z", 45, "synthetic-project-sync", [ATLAS]),
    CalendarEvent("2026-06-02T15:30:00Z", 30, "synthetic-1-on-1", []),
]

ATLAS_INFERRED_FREE_SLOTS: list[str] = [
    "2026-06-02T16:00:00Z",
    "2026-06-02T17:00:00Z",
]
```

These fixtures guarantee the happy path: Iris requests `14:00`; Marius has `synthetic-project-sync` with Atlas at `14:00`; the reasoner picks `16:00` (not in Marius' calendar, first in Atlas' free list); Atlas accepts; Marius returns acceptance to Iris.

## 5. Data Shapes

All Pydantic models in `server/cascading.py`. `ResidueDTO` imported from `.scenarios`.

```python
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict

from .scenarios import ResidueDTO, PAYLOAD_SCHEMA


class BilateralExchangeDTO(BaseModel):
    """Cryptographic evidence for one completed bilateral exchange."""
    model_config = ConfigDict(extra="forbid")

    exchange_label: str           # "iris-to-marius" | "marius-to-atlas" | "marius-accepts-iris"
    initiator: str                # principal_id of the sender
    responder: str                # principal_id of the responder
    proposal_payload_hash: str    # SHA-256(JCS(scoped proposal))
    acceptance_payload_hash: str  # SHA-256(JCS(acceptance payload))
    task_id: str                  # A2A task_id


class ReasonerTraceDTO(BaseModel):
    """Marius' agent's reasoning output. Rendered verbatim in the UI."""
    model_config = ConfigDict(extra="forbid")

    requested_slot: str
    blocking_event_title: str
    blocking_event_attendee: str
    proposed_new_slot: str
    reason: str


class CalendarEventDTO(BaseModel):
    """Wire-safe projection of CalendarEvent for the UI."""
    model_config = ConfigDict(extra="forbid")

    slot_start: str
    duration_minutes: int
    title: str
    # attendee_principal_ids intentionally omitted per scoping discipline


class CalendarStateDTO(BaseModel):
    """Principal's calendar before and after the cascade."""
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    before: list[CalendarEventDTO]
    after: list[CalendarEventDTO]


class CascadingResult(BaseModel):
    """Complete structured output of the cascading-reschedule scenario."""
    model_config = ConfigDict(extra="forbid")

    iris_principal_id: str
    marius_principal_id: str
    atlas_principal_id: str

    reasoner_trace: ReasonerTraceDTO

    exchange_iris_marius_proposal: BilateralExchangeDTO
    exchange_marius_atlas: BilateralExchangeDTO
    exchange_marius_iris_acceptance: BilateralExchangeDTO

    iris_scoped_proposal: dict[str, Any]
    marius_reschedule_proposal: dict[str, Any]
    atlas_acceptance_payload: dict[str, Any]
    marius_acceptance_to_iris: dict[str, Any]

    iris_ledger: list[ResidueDTO]
    marius_ledger: list[ResidueDTO]
    atlas_ledger: list[ResidueDTO]

    iris_calendar: CalendarStateDTO
    marius_calendar: CalendarStateDTO
    atlas_calendar: CalendarStateDTO

    policy_doc_iris: dict[str, Any]
    duration_ms: int
```

### Field notes

- `exchange_iris_marius_proposal.task_id == exchange_marius_iris_acceptance.task_id` always (both `task_id_1`).
- `exchange_marius_atlas.task_id` is always distinct (`task_id_2`).
- `iris_scoped_proposal` is the post-policy payload (no `calendar_titles` or `attendee_emails`). Use `_strip_blocked_fields` from `scenarios.py`.
- `marius_calendar.after`: the `synthetic-project-sync` event moves from 14:00 to 16:00. Computed by orchestrator (no actual write).
- `iris_calendar.after`: gains the new Iris↔Marius meeting at 14:00.
- `atlas_calendar.after`: gains the rescheduled `synthetic-project-sync` at 16:00.
- `atlas_calendar.before`: empty list — Atlas' internal calendar is not modeled in v0.

## 6. Endpoint Design

Replace the existing `GET /scenarios/cascading/run` placeholder in `server/main.py` with:

```python
@app.post(
    "/scenarios/cascading/run",
    response_model=CascadingResult,
)
async def run_cascading_endpoint() -> CascadingResult:
    """Run the three-principal cascading-reschedule scenario."""
    try:
        return await run_cascading()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"cascading scenario failed: {e!r}",
        ) from e
```

Add to `main.py` imports:
```python
from .cascading import CascadingResult, run_cascading
```

Empty request body (or no body). Error shape matches `run_two_party_endpoint`.

## 7. File Layout

### Files to CREATE

**`server/reasoner.py`**
- `CalendarEvent`, `RescheduleProposal`, `SchedulingReasoner` (Protocol), `ScriptedReasoner`, `LLMReasoner` (stub)
- No Mesherra imports. stdlib only: `dataclasses`, `typing`

**`server/cascading.py`**
- Constants: `IRIS`, `MARIUS`, `ATLAS`, `IRIS_SYNTHETIC_CALENDAR`, `MARIUS_SYNTHETIC_CALENDAR`, `ATLAS_INFERRED_FREE_SLOTS`
- Pydantic models: `BilateralExchangeDTO`, `ReasonerTraceDTO`, `CalendarEventDTO`, `CalendarStateDTO`, `CascadingResult`
- Exception: `CascadeAbortedError(RuntimeError)`
- Private helpers: `_cascading_policy(principal_id)`, `_calendar_after_move(...)`, `_calendar_after_add(...)`
- `async def run_cascading(reasoner: SchedulingReasoner | None = None) -> CascadingResult`

Imports from Mesherra: same as `scenarios.py`.
Imports from this package: `from .scenarios import ResidueDTO, _residue_to_dto, _free_port, _strip_blocked_fields`.
Imports from reasoner: `from .reasoner import CalendarEvent, RescheduleProposal, SchedulingReasoner, ScriptedReasoner`.

### Files to MODIFY

**`server/main.py`** — three changes only:
1. Add `from .cascading import CascadingResult, run_cascading`
2. Remove the existing `GET /scenarios/cascading/run` placeholder
3. Add the new `POST /scenarios/cascading/run` endpoint per §6

### Files NOT to touch

| File | Reason |
|------|--------|
| `server/scenarios.py` | Read-only imports from `cascading.py`; no modifications |
| `server/__init__.py` | No changes |
| `mesherra/src/**` | Trust layer is frozen |
| `index.html` | UI is a separate deliverable |
| `pyproject.toml`, `.venv` | No new deps |

### Dependency graph (no cycles)

```
main.py
  └── cascading.py
        ├── reasoner.py           (no back-imports)
        └── scenarios.py          (read-only helpers)
              └── mesherra SDK
```

## 8. UI Requirements (description only)

For the UI implementer:

**Three-principal stage.** Three columns: Iris (left), Marius (center, wider — 4 ledger entries), Atlas (right). Each shows the principal's name, running ledger entries, and calendar before/after.

**Cascade flow arrows.** Animated arrows in sequence: (1) Iris→Marius, (2) PAUSE with "agent reasoning..." spinner in Marius' column, (3) Marius→Atlas, (4) Atlas→Marius, (5) Marius→Iris. The pause at (2) is the key beat for communicating agentic behavior.

**Reasoning trace panel.** Bordered panel inside Marius' column. Renders `reasoner_trace.reason` verbatim in IBM Plex Mono. Also shows the labeled key-values (`requested_slot`, `blocking_event_title`, `blocking_event_attendee`, `proposed_new_slot`). Appears during the pause and stays visible afterward. Must not be collapsed — it's the feature being demonstrated.

**Three tessera-fits.** The stone-halves animation plays three times in cascade order (A, B, C). Each fit shows the exchange label, the two principals, and the two matching payload hashes. Exchange B fires between A and C to make the dependency structure visually obvious.

**Two A2A task IDs.** Display both `task_id_1` and `task_id_2` in monospace badges. Make clear that A + C share `task_id_1` while B uses `task_id_2`.

**Calendar deltas.** At cascade completion, render before/after for all three. Terracotta for removed entries; jade for added entries.

## 9. Failure Modes

Documented; not exercised in v0 happy path.

### Atlas declines

`marius_sdk.send_to(atlas_url)` returns with `response_operation == REJECTION`. Orchestrator raises `CascadeAbortedError("atlas declined the reschedule proposal for {new_slot}; cannot free the requested slot")`. Endpoint returns 500.

### Reasoner returns None

Handler raises `CascadeAbortedError("reasoner found no viable reschedule slot...")` before any further Mesherra calls.

### Reasoner raises exception

Wrap reasoner call in `try/except`; re-raise as `CascadeAbortedError`. The orchestrator's `try/finally` ensures all listeners/stores/ledgers close cleanly.

### Directory lookup fails

Cannot happen in v0 (all three principals registered before any `send_to`). Document in code comment.

## 10. Test Plan Outline

New file: `MeshyCal/demos/phase_4_prototype/tests/test_cascading.py`

### Happy path

```python
async def test_happy_path():
    result = await run_cascading()

    assert result.iris_principal_id == IRIS
    assert result.marius_principal_id == MARIUS
    assert result.atlas_principal_id == ATLAS

    assert len(result.iris_ledger) == 2
    assert len(result.marius_ledger) == 4
    assert len(result.atlas_ledger) == 2

    # Iris
    assert result.iris_ledger[0].action_type == "emit"
    assert result.iris_ledger[0].operation == "proposal"
    assert result.iris_ledger[1].action_type == "receive"
    assert result.iris_ledger[1].operation == "acceptance"

    # Marius — 4 entries
    assert result.marius_ledger[0].action_type == "receive"
    assert result.marius_ledger[0].operation == "proposal"
    assert result.marius_ledger[1].action_type == "emit"
    assert result.marius_ledger[1].operation == "proposal"
    assert result.marius_ledger[2].action_type == "receive"
    assert result.marius_ledger[2].operation == "acceptance"
    assert result.marius_ledger[3].action_type == "emit"
    assert result.marius_ledger[3].operation == "acceptance"

    # Atlas
    assert result.atlas_ledger[0].action_type == "receive"
    assert result.atlas_ledger[0].operation == "proposal"
    assert result.atlas_ledger[1].action_type == "emit"
    assert result.atlas_ledger[1].operation == "acceptance"

    # Reasoner trace
    assert result.reasoner_trace.proposed_new_slot == "2026-06-02T16:00:00Z"
    assert result.reasoner_trace.blocking_event_title == "synthetic-project-sync"
    assert result.reasoner_trace.blocking_event_attendee == ATLAS
    assert result.reasoner_trace.requested_slot == "2026-06-02T14:00:00Z"

    assert result.duration_ms > 0
```

### Reasoner returns None branch

```python
async def test_reasoner_returns_none_aborts_cascade():
    class NullReasoner:
        def propose_reschedule_target(self, **kwargs):
            return None

    with pytest.raises(CascadeAbortedError, match="no viable reschedule slot"):
        await run_cascading(reasoner=NullReasoner())
```

### Tessera-fit assertions

```python
async def test_iris_marius_tessera_fit():
    result = await run_cascading()
    assert (
        result.iris_ledger[0].payload_hash
        == result.marius_ledger[0].payload_hash
        == result.exchange_iris_marius_proposal.proposal_payload_hash
    )
    assert (
        result.marius_ledger[3].payload_hash
        == result.iris_ledger[1].payload_hash
        == result.exchange_marius_iris_acceptance.acceptance_payload_hash
    )

async def test_marius_atlas_tessera_fit():
    result = await run_cascading()
    assert (
        result.marius_ledger[1].payload_hash
        == result.atlas_ledger[0].payload_hash
        == result.exchange_marius_atlas.proposal_payload_hash
    )
    assert (
        result.atlas_ledger[1].payload_hash
        == result.marius_ledger[2].payload_hash
        == result.exchange_marius_atlas.acceptance_payload_hash
    )
```

### task_id relationships

```python
async def test_task_id_relationships():
    result = await run_cascading()
    assert (
        result.exchange_iris_marius_proposal.task_id
        == result.exchange_marius_iris_acceptance.task_id
    )
    assert (
        result.exchange_marius_atlas.task_id
        != result.exchange_iris_marius_proposal.task_id
    )
```

### Marius single hash chain

```python
async def test_marius_ledger_hash_chain():
    result = await run_cascading()
    sequences = [e.sequence for e in result.marius_ledger]
    assert sequences == [0, 1, 2, 3]
```

### Scoped proposal excludes blocked fields

```python
async def test_scoped_proposal_excludes_blocked_fields():
    result = await run_cascading()
    assert "calendar_titles" not in result.iris_scoped_proposal
    assert "attendee_emails" not in result.iris_scoped_proposal
    assert "candidates" in result.iris_scoped_proposal
```

### Calendar deltas

```python
async def test_calendar_deltas():
    result = await run_cascading()
    marius_before_slots = {e.slot_start for e in result.marius_calendar.before}
    marius_after_slots = {e.slot_start for e in result.marius_calendar.after}
    assert "2026-06-02T14:00:00Z" in marius_before_slots
    assert "2026-06-02T14:00:00Z" not in marius_after_slots
    assert "2026-06-02T16:00:00Z" in marius_after_slots

    iris_after_slots = {e.slot_start for e in result.iris_calendar.after}
    assert "2026-06-02T14:00:00Z" in iris_after_slots

    atlas_after_slots = {e.slot_start for e in result.atlas_calendar.after}
    assert "2026-06-02T16:00:00Z" in atlas_after_slots
```

---

*End of Scenario 3 Design Spec.*
