# Scenario 2 Design — Four-Party Group Meeting Find

**File:** `MeshyCal/demos/phase_4_prototype/server/SCENARIO_2_DESIGN.md`
**Status:** Design spec. The implementer writes code from this document.

---

## 1. Goal

Scenario 2 demonstrates that Mesherra's two-party trust primitive composes cleanly into a multi-party coordination pattern without any change to the Mesherra layer itself. Iris convenes a 30-minute meeting with three peers — Marius, Wren, and Atlas — and needs a slot all four can attend. Her agent runs six bilateral Phase 3 Mesherra exchanges in total: three query exchanges (Iris asks each peer for their available slots, each peer replies with their free-slot candidates) and three confirm exchanges (Iris tells each peer which slot was chosen, each peer acknowledges). The intersection computation — figuring out which slots all four principals share — is pure local arithmetic on Iris's side between the two exchange phases. No new Mesherra primitives are required; the entire orchestration is built in MeshyCal's domain layer on top of the existing `Mesherra.send_to` / `on_message` surface. The result proves that the privacy and provenance guarantees established in Phase 3 hold at every individual bilateral link even inside a group negotiation: no peer ever learns another peer's calendar data, each bilateral exchange produces its own pair of signed ledger entries, and the chosen meeting slot is backed by six matching residue receipts.

---

## 2. Coordinator Pattern

Iris is the sole coordinator. She runs all exchanges sequentially (not concurrently) so the implementation is deterministic and easy to trace. Each exchange is a standard Phase 3 bilateral: Iris uses her `Mesherra` SDK instance to call `send_to`, the peer's `Mesherra` SDK instance handles the inbound message via its registered handler, returns a response, and both ledgers record a matching pair of residue entries.

### Phase A — Query (3 exchanges, in order)

**Exchange A1: Iris query → Marius**
- Iris sends a `PROPOSAL` payload of schema `meshycal.scheduling/proposal-v1` containing her own candidate slots. The payload carries the `candidates` list (her free slots), `duration_minutes: 30`, and `constraint_hints`. Blocked fields (`calendar_titles`, `attendee_emails`) are stripped by her outbound policy exactly as in Scenario 1.
- Marius's handler inspects the scoped payload, cross-references his own busy blocks, and returns an `ACCEPTANCE` response payload containing his subset of the candidates that work for him, plus his own `constraint_hints`.
- Both Iris's and Marius's ledgers record one emit entry and one receive entry, producing residue pair (A1-iris, A1-marius).

**Exchange A2: Iris query → Wren**
- Same structure. Wren responds with her available subset.
- Residue pair (A2-iris, A2-wren).

**Exchange A3: Iris query → Atlas**
- Same structure. Atlas responds with his available subset.
- Residue pair (A3-iris, A3-atlas).

### Intersection Computation (local, no network)

After A3 completes, Iris's orchestrator code computes:
1. Start with Iris's own candidate set.
2. Intersect with the set of slots Marius confirmed as available.
3. Intersect with the set of slots Wren confirmed as available.
4. Intersect with the set of slots Atlas confirmed as available.
5. If the intersection is empty, return a `FourPartyResult` with `success: False` and `failure_reason: "no_common_slot"`. Do not proceed to Phase B.
6. If non-empty, pick the first slot in ISO-8601 chronological order as `chosen_slot`. (Deterministic; no LLM.)

### Phase B — Confirm (3 exchanges, in order)

**Exchange B1: Iris confirm → Marius**
- Iris sends a `PROPOSAL` payload (same schema) containing only `candidates: [chosen_slot]`, `duration_minutes: 30`, and `constraint_hints`. This is the confirmation message.
- Marius's handler replies `ACCEPTANCE` with `candidates: [chosen_slot]`, `duration_minutes: 30`.
- Residue pair (B1-iris, B1-marius).

**Exchange B2: Iris confirm → Wren**
- Same structure. Wren acknowledges.
- Residue pair (B2-iris, B2-wren).

**Exchange B3: Iris confirm → Atlas**
- Same structure. Atlas acknowledges.
- Residue pair (B3-iris, B3-atlas).

After B3, all six bilateral exchanges are complete. The result is assembled into a `FourPartyResult` and returned.

**Why sequential, not concurrent.** The existing `A2AAdapter` / `Mesherra` SDK boots an HTTP listener per peer. Running six simultaneous listeners in one process is possible but introduces port-management complexity and async concurrency noise that adds implementation risk with no demo value. Sequential keeps each bilateral identical in structure to Scenario 1 and makes the trace easy to read. A note in the spec documents that a real deployment would pipeline these.

---

## 3. Synthetic Calendars

All busy blocks are synthetic. No real identities. Slots are on a notional "Tuesday" mapped to ISO-8601 UTC timestamps anchored on 2026-05-26 (the same reference week as Scenario 1).

Each busy block is described by `(start_iso, end_iso)` and is only used internally within the handler logic — it never appears in any outbound payload.

### Iris (convener)
Busy blocks (synthetic internal only):
- `2026-05-26T09:00:00Z` – `2026-05-26T10:00:00Z` (synthetic-atelier-critique)
- `2026-05-26T11:00:00Z` – `2026-05-26T12:00:00Z` (synthetic-field-notes-review)
- `2026-05-26T14:00:00Z` – `2026-05-26T15:00:00Z` (synthetic-glassworks-prep)

Iris's candidate slots she proposes outbound (free 30-minute windows):
- `2026-05-26T13:00:00Z`
- `2026-05-26T15:30:00Z`
- `2026-05-27T11:30:00Z`

### Marius
Busy blocks:
- `2026-05-26T10:00:00Z` – `2026-05-26T11:30:00Z` (synthetic-site-visit)
- `2026-05-26T15:30:00Z` – `2026-05-26T16:30:00Z` (synthetic-review-session)
- `2026-05-27T09:00:00Z` – `2026-05-27T10:30:00Z` (synthetic-morning-standup)

Marius's response to Iris's candidates — he filters out anything overlapping his busy blocks:
- `2026-05-26T13:00:00Z` — FREE (available)
- `2026-05-26T15:30:00Z` — BUSY (blocked by synthetic-review-session)
- `2026-05-27T11:30:00Z` — FREE (available)

Marius confirms: `["2026-05-26T13:00:00Z", "2026-05-27T11:30:00Z"]`

### Wren
Busy blocks:
- `2026-05-26T08:30:00Z` – `2026-05-26T09:30:00Z` (synthetic-morning-brief)
- `2026-05-27T11:30:00Z` – `2026-05-27T12:30:00Z` (synthetic-materials-review)

Wren's response to Iris's candidates:
- `2026-05-26T13:00:00Z` — FREE (available)
- `2026-05-26T15:30:00Z` — FREE (available)
- `2026-05-27T11:30:00Z` — BUSY (blocked by synthetic-materials-review)

Wren confirms: `["2026-05-26T13:00:00Z", "2026-05-26T15:30:00Z"]`

### Atlas
Busy blocks:
- `2026-05-26T15:30:00Z` – `2026-05-26T17:00:00Z` (synthetic-fabrication-sign-off)
- `2026-05-27T10:00:00Z` – `2026-05-27T12:00:00Z` (synthetic-logistics-call)

Atlas's response to Iris's candidates:
- `2026-05-26T13:00:00Z` — FREE (available)
- `2026-05-26T15:30:00Z` — BUSY (blocked by synthetic-fabrication-sign-off)
- `2026-05-27T11:30:00Z` — BUSY (blocked by synthetic-logistics-call)

Atlas confirms: `["2026-05-26T13:00:00Z"]`

### Intersection

- Iris's candidates: `{13:00 Tue, 15:30 Tue, 11:30 Wed}`
- After Marius: `{13:00 Tue, 11:30 Wed}`
- After Wren: `{13:00 Tue}` (11:30 Wed eliminated because Wren is busy)
- After Atlas: `{13:00 Tue}` (unchanged; Atlas also confirmed 13:00 Tue)

Chosen slot: `2026-05-26T13:00:00Z`. The happy path always lands here.

---

## 4. Data Shapes

### 4.1 `BilateralExchangeRecord`

One record per bilateral. Captures everything a UI or audit tool needs to verify that exchange.

```python
class BilateralExchangeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange_id: str          # e.g. "A1", "A2", "A3", "B1", "B2", "B3"
    phase: str                # "query" or "confirm"
    coordinator: str          # always "iris@meshycal.demo"
    peer: str                 # e.g. "marius@meshycal.demo"
    iris_scoped_payload: dict[str, Any]       # what Iris actually sent (post-airlock)
    peer_response_payload: dict[str, Any]     # what the peer replied
    iris_payload_hash: str    # SHA-256(JCS(iris_scoped_payload)), 64 hex chars
    peer_payload_hash: str    # SHA-256(JCS(peer_response_payload)), 64 hex chars
    iris_ledger_entries: list[ResidueDTO]     # Iris's ledger entries for this task
    peer_ledger_entries: list[ResidueDTO]     # peer's ledger entries for this task
    task_id: str              # A2A task_id assigned by the adapter for this exchange
```

`ResidueDTO` is the existing model already defined in `scenarios.py` — import and reuse it; do not duplicate.

### 4.2 `IntersectionState`

Captures the intermediate computation for the UI's "how did we get here" panel.

```python
class IntersectionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iris_candidates: list[str]           # Iris's initial proposal slots (ISO-8601)
    marius_available: list[str]          # slots Marius said work for him
    wren_available: list[str]            # slots Wren said work for her
    atlas_available: list[str]           # slots Atlas said work for him
    after_marius: list[str]              # iris_candidates ∩ marius_available
    after_wren: list[str]                # after_marius ∩ wren_available
    after_atlas: list[str]               # after_wren ∩ atlas_available (= final intersection)
    chosen_slot: str | None              # first slot in after_atlas; None if empty
```

### 4.3 `PeerLedgerSummary`

A summary of one non-Iris principal's full ledger across both query and confirm exchanges with that peer. For the UI's "per-principal receipt" panel.

```python
class PeerLedgerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    query_exchange_id: str            # "A1", "A2", or "A3"
    confirm_exchange_id: str          # "B1", "B2", or "B3"; "" when no_common_slot
    all_ledger_entries: list[ResidueDTO]   # all entries across both exchanges, ordered by sequence
    policy_doc: dict[str, Any]            # peer's signed policy doc
```

### 4.4 `FourPartyResult`

The top-level response model. The UI reads this entire structure.

```python
class FourPartyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Identity
    iris_principal_id: str           # "iris@meshycal.demo"
    marius_principal_id: str         # "marius@meshycal.demo"
    wren_principal_id: str           # "wren@meshycal.demo"
    atlas_principal_id: str          # "atlas@meshycal.demo"

    # Outcome
    success: bool
    failure_reason: str | None       # None when success=True; see §8 for values

    # Chosen slot (None when success=False)
    chosen_slot: str | None          # ISO-8601 UTC; "2026-05-26T13:00:00Z" on happy path

    # All six bilateral exchange records, in execution order
    exchanges: list[BilateralExchangeRecord]   # len == 6 on success; len == 3 on no_common_slot

    # Intersection trace
    intersection: IntersectionState | None    # None when success=False

    # Per-peer ledger summaries (one per non-Iris principal)
    marius_summary: PeerLedgerSummary
    wren_summary: PeerLedgerSummary
    atlas_summary: PeerLedgerSummary

    # Iris's full ledger across all six exchanges
    iris_ledger: list[ResidueDTO]

    # Iris's policy doc
    policy_doc_iris: dict[str, Any]

    # Timing
    duration_ms: int
```

**Field notes for the implementer:**

- `exchanges` is always in order: A1, A2, A3, then (if success) B1, B2, B3. On `no_common_slot` failure the list has exactly 3 entries (A1, A2, A3) and Phase B never ran.
- `BilateralExchangeRecord.iris_ledger_entries` and `peer_ledger_entries` contain only entries scoped to that exchange's `task_id`. `iris_ledger` at the top level is the union of all Iris's entries across all exchanges, ordered by sequence.
- `PeerLedgerSummary.all_ledger_entries` is the union of that peer's entries across their two exchanges, ordered by sequence. On `no_common_slot`, the peer summaries still exist (query phase ran) but `confirm_exchange_id` should be `""` and the confirm entries will be absent.
- `intersection` is `None` when `success=False`. Even on failure, the query exchange records and peer summaries are populated so the UI can show what was collected before failure.
- All `payload_hash` values are 64 lowercase hex characters (SHA-256 of JCS-canonical JSON), consistent with `ResidueDTO.payload_hash` and the existing `content_hash` + `canonical_json` functions from `mesherra.crypto.primitives`.

---

## 5. Endpoint Design

### Method and path

```
POST /scenarios/four-party/run
```

The existing placeholder is `GET`. Change it to `POST` to match `/scenarios/two-party/run` and to allow a future request body without HTTP semantic awkwardness.

### Request body

Empty for v0. All inputs are synthetic and hardcoded in the orchestrator.

```python
@app.post(
    "/scenarios/four-party/run",
    response_model=FourPartyResult,
)
async def run_four_party_endpoint() -> FourPartyResult:
    ...
```

### Response

`FourPartyResult` as defined in §4.4. HTTP 200 on both happy path and `no_common_slot` failure — the scenario ran successfully even if no slot was found; the `success` flag communicates the outcome. HTTP 500 only if an unexpected exception escapes.

### Error handling

Wrap in the same `try / except Exception` block as `run_two_party_endpoint` in `main.py`, raising `HTTPException(status_code=500, detail=...)` on unexpected errors.

---

## 6. File Layout

### New files to create

**`MeshyCal/demos/phase_4_prototype/server/group_negotiation.py`**

This is the primary new file. It contains:

1. The three new Pydantic models: `BilateralExchangeRecord`, `IntersectionState`, `PeerLedgerSummary`.
2. `FourPartyResult` (imports `ResidueDTO` from `scenarios.py`).
3. The principal ID constants for Wren and Atlas:
   ```python
   WREN = "wren@meshycal.demo"
   ATLAS = "atlas@meshycal.demo"
   ```
   (`IRIS` and `MARIUS` are already defined in `scenarios.py`; import them from there.)
4. `_busy_blocks(principal_id: str) -> list[tuple[str, str]]` — returns the synthetic busy schedule for a given principal.
5. `_slots_available(candidates: list[str], busy_blocks: list[tuple[str, str]], duration_minutes: int) -> list[str]` — pure function. Returns the subset of candidates that do not overlap any busy block.
6. `_make_peer_handler(principal_id: str, phase: str) -> tuple[ConsumerHandler, dict]` — factory that returns an `async def handler(msg) -> OutgoingResponse` closure for a given peer and phase, plus a `captured` dict the orchestrator can read after the exchange.
7. `_run_bilateral(...) -> BilateralExchangeRecord` — async function. Boots peer listener, runs `iris_sdk.send_to`, stops listener, reads both ledgers, returns `BilateralExchangeRecord`.
8. `async def run_four_party() -> FourPartyResult` — the top-level orchestrator. Uses `tempfile.TemporaryDirectory` exactly as `run_two_party()` does.

### Modifications to existing files

**`MeshyCal/demos/phase_4_prototype/server/scenarios.py`**

No new functions added. The `_residue_to_dto` and `_default_meshycal_policy` helpers are duplicated in `group_negotiation.py` (6-10 line functions; duplication is cleaner than reaching across private boundaries). Refactor to a shared `_helpers.py` later if a third scenario needs them.

**`MeshyCal/demos/phase_4_prototype/server/main.py`**

Two changes only:

1. Add to imports:
   ```python
   from .group_negotiation import FourPartyResult, run_four_party
   ```

2. Replace the existing `GET /scenarios/four-party/run` endpoint with:
   ```python
   @app.post(
       "/scenarios/four-party/run",
       response_model=FourPartyResult,
   )
   async def run_four_party_endpoint() -> FourPartyResult:
       """Run a real Phase 3 four-party group-find negotiation."""
       try:
           return await run_four_party()
       except Exception as e:
           raise HTTPException(
               status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
               detail=f"four-party scenario failed: {e!r}",
           ) from e
   ```

### Files to leave completely untouched

- `MeshyCal/demos/phase_4_prototype/index.html` — UI work is out of scope for this ticket.
- `mesherra/` — the entire Mesherra repo. No changes. Absolute constraint.
- `MeshyCal/demos/phase_1/` — Scenario 2 does not touch Phase 1 demo files.

---

## 7. UI Requirements (description only)

For the UI implementer (separate ticket):

**Stage layout.** Four principal panels in a hub-and-spoke layout: Iris centered, Marius / Wren / Atlas around her. Each peer panel shows that peer's principal ID and a summary of their response (how many slots they confirmed in the query phase, plus the confirm acknowledgement).

**Bilateral receipt table.** Six rows, one per exchange, labeled A1 through B3. Each row shows: exchange ID, peer name, phase (query / confirm), Iris's scoped payload hash (truncated to 16 chars with a tooltip for the full hash), the peer's response payload hash, and a "verified" badge.

**Intersection visualization.** A three-column progressive funnel: column 1 is Iris's three initial candidates; column 2 is the result after each peer's response (shown as three sub-columns, one per peer, with strikethroughs on eliminated slots); column 3 is the final chosen slot highlighted in jade green.

**Calendar updates.** Each of the four principal panels should show a "booked" indicator on the chosen slot's time band once `success: true` and `chosen_slot` are populated.

**Failure state.** If `success: false` and `failure_reason: "no_common_slot"`, the intersection funnel column 3 shows an empty state ("no overlap") and no calendar updates fire.

**Timing badge.** `duration_ms` shown as "completed in Xms".

---

## 8. Failure Modes

### `no_common_slot`

The intersection after all three peer responses is empty. `FourPartyResult` fields when this occurs:
- `success: False`
- `failure_reason: "no_common_slot"`
- `chosen_slot: None`
- `exchanges`: the three query-phase records only
- `intersection`: populated, with `after_atlas: []` and `chosen_slot: None`
- `marius_summary`, `wren_summary`, `atlas_summary`: populated but with `confirm_exchange_id: ""` and no confirm ledger entries

The v0 synthetic calendar is hand-designed so this never occurs on the happy path. This failure mode is representable in the type but not exercised in v0 tests.

### `schema_mismatch` (policy blocks an unexpected schema)

If a peer's `PolicyStore` has no rule for `meshycal.scheduling/proposal-v1`, the Mesherra inbound gateway raises `PolicyBlocked`. In v0 all four principals use the same `_default_meshycal_policy` template, so this cannot happen on the happy path. Let it propagate to the FastAPI 500 handler.

### Port collision

Each bilateral's listener is stopped before the next one starts (sequential pattern). No concurrent port-collision risk.

### General exception boundary

Any exception that is not part of the typed success/failure flow propagates to the FastAPI handler → HTTP 500.

---

## 9. Test Plan Outline

Tests live alongside the prototype (either inline in `server/` or a `tests/` subdir matching Phase 1's convention).

**Test: happy path end-to-end**
- Call `run_four_party()` directly.
- Assert `result.success is True`.
- Assert `result.chosen_slot == "2026-05-26T13:00:00Z"`.
- Assert `len(result.exchanges) == 6` with exchange IDs `["A1", "A2", "A3", "B1", "B2", "B3"]`.
- Assert `result.iris_ledger` has exactly 12 entries.
- Assert each peer summary has 4 ledger entries.
- Assert `result.duration_ms > 0`.

**Test: intersection correctness**
- Assert each `IntersectionState` field equals the values from §3.

**Test: ledger hash equality across all six bilateral pairs**
- For each exchange, assert `exchange.iris_ledger_entries[0].payload_hash == exchange.peer_ledger_entries[0].payload_hash`.

**Test: scoped payload never contains blocked fields**
- For each exchange, assert `calendar_titles` and `attendee_emails` absent from `iris_scoped_payload`.

**Test: `_slots_available` pure unit test**
- Happy path with one busy block; no busy blocks (all candidates); all busy (empty list).

**Test: schema-mismatch raises**
- Misconfigure one peer's PolicyStore; assert `PolicyBlocked` propagates.

**Test (future): `no_common_slot` representability**
- Stub `_busy_blocks` so all peers block all candidates; assert `success=False`, `failure_reason="no_common_slot"`, `len(exchanges)==3`.

---

*End of Scenario 2 Design Spec.*
