"""Track B UI contract tests — Scenario 2 (four-party group find).

These tests pin the JS-backend wire shape for the Scenario 2 panel in
``demos/phase_4_prototype/index.html``. The UI's ``runScenario2`` and
``s2PopulateReceiptRow`` functions read a fixed set of field paths off
the ``FourPartyResult`` JSON; if either side drifts, the receipt rows,
funnel, and ledger panels break silently.

We call ``run_four_party()`` directly rather than going through FastAPI:
Pydantic's ``model_config = ConfigDict(extra="forbid")`` already
guarantees the wire shape matches the model, so the in-process object
graph is a faithful stand-in for the JSON the browser receives.

``asyncio_mode = "auto"`` is set in ``pyproject.toml`` so ``async def``
tests are picked up natively.
"""

from __future__ import annotations

import pytest

from demos.phase_4_prototype.server.group_negotiation import (
    FourPartyResult,
    run_four_party,
)


# One module-scoped run is sufficient: the negotiation is deterministic
# and six real bilateral exchanges are expensive to repeat.
@pytest.fixture(scope="module")
async def result() -> FourPartyResult:
    return await run_four_party()


# ---------------------------------------------------------------------------
# 1. Top-level identity / outcome fields the UI status banner reads.
# ---------------------------------------------------------------------------


class TestTopLevelFields:
    async def test_principal_ids_present(self, result: FourPartyResult) -> None:
        # UI does not currently render the principal IDs verbatim, but the
        # backend contract advertises all four and the receipt rows derive
        # the short peer label from ``ex.peer`` which must match these.
        assert isinstance(result.iris_principal_id, str) and result.iris_principal_id
        assert isinstance(result.marius_principal_id, str) and result.marius_principal_id
        assert isinstance(result.wren_principal_id, str) and result.wren_principal_id
        assert isinstance(result.atlas_principal_id, str) and result.atlas_principal_id

    async def test_success_and_failure_reason(self, result: FourPartyResult) -> None:
        # ``runScenario2`` branches on ``lastReal4.success`` and only renders
        # the failure banner / detail when it is falsy.
        assert result.success is True
        assert result.failure_reason is None

    async def test_chosen_slot(self, result: FourPartyResult) -> None:
        # ``s2ChosenChip`` is fed ``lastReal4.chosen_slot``.
        assert result.chosen_slot == "2026-05-26T13:00:00Z"

    async def test_duration_ms(self, result: FourPartyResult) -> None:
        # Status tail reads ``lastReal4.duration_ms``.
        assert isinstance(result.duration_ms, int)
        assert result.duration_ms > 0


# ---------------------------------------------------------------------------
# 2. Exchanges array — receipt rows and exchange log read these fields.
# ---------------------------------------------------------------------------


class TestExchangesContract:
    async def test_receipt_row_order(self, result: FourPartyResult) -> None:
        # ``s2ClearReceiptRows`` and the run loop iterate exactly these IDs;
        # any drift in order would mis-populate the receipt table.
        ids = [ex.exchange_id for ex in result.exchanges]
        assert ids == ["A1", "A2", "A3", "B1", "B2", "B3"]

    async def test_each_exchange_has_ui_fields(
        self, result: FourPartyResult
    ) -> None:
        # ``s2PopulateReceiptRow`` reads ``exchange_id``, ``phase``, ``peer``,
        # ``iris_payload_hash``, ``peer_payload_hash``. All must be present
        # and non-empty for every exchange (Pydantic guarantees presence;
        # this guards against accidental empty strings).
        for ex in result.exchanges:
            assert ex.exchange_id
            assert ex.phase in {"query", "confirm"}
            assert ex.peer  # short label is split on "@"
            assert ex.iris_payload_hash
            assert ex.peer_payload_hash

    async def test_phase_split_three_query_then_three_confirm(
        self, result: FourPartyResult
    ) -> None:
        # The receipt-row badge styling depends on ``phase`` matching the
        # query/confirm convention exactly.
        phases = [ex.phase for ex in result.exchanges]
        assert phases == ["query", "query", "query", "confirm", "confirm", "confirm"]

    async def test_tessera_fit_invariant_per_exchange(
        self, result: FourPartyResult
    ) -> None:
        # The "✓ verified" badge in the receipt row is, in a real product,
        # conditional on the Mesherra Tessera-fit contract: for each
        # bilateral, the payload bytes Iris emitted are the bytes the peer
        # received, so Iris's emit-residue hash must equal the peer's
        # receive-residue hash. The top-level ``iris_payload_hash`` and
        # ``peer_payload_hash`` on the exchange record describe *different
        # halves* of the bilateral (Iris's outbound proposal vs the peer's
        # outbound response) and are intentionally NOT equal — that is
        # why the UI renders them as two side-by-side hash columns. The
        # tessera-fit invariant lives one layer down, on the paired
        # ledger residues.
        mismatches: list[str] = []
        for ex in result.exchanges:
            assert ex.iris_ledger_entries, (
                f"{ex.exchange_id}: Iris ledger entries missing"
            )
            assert ex.peer_ledger_entries, (
                f"{ex.exchange_id}: peer ledger entries missing"
            )
            # Iris's first entry is her outbound emit; peer's first entry
            # is the corresponding inbound receive of the same wire bytes.
            iris_emit_hash = ex.iris_ledger_entries[0].payload_hash
            peer_recv_hash = ex.peer_ledger_entries[0].payload_hash
            if iris_emit_hash != peer_recv_hash:
                mismatches.append(
                    f"{ex.exchange_id}: iris_emit={iris_emit_hash} "
                    f"peer_recv={peer_recv_hash}"
                )
        assert not mismatches, (
            "Tessera-fit violated: " + "; ".join(mismatches)
        )


# ---------------------------------------------------------------------------
# 3. Intersection funnel — the right-hand column reads every field below.
# ---------------------------------------------------------------------------


class TestIntersectionContract:
    async def test_intersection_present(self, result: FourPartyResult) -> None:
        # ``runScenario2`` dereferences ``lastReal4.intersection.after_atlas``
        # without guarding for null when ``success`` is true.
        assert result.intersection is not None

    async def test_iris_candidates_funnel_start(
        self, result: FourPartyResult
    ) -> None:
        # The leftmost funnel column shows Iris's three opening candidates.
        assert result.intersection is not None
        assert len(result.intersection.iris_candidates) == 3
        assert result.intersection.iris_candidates == [
            "2026-05-26T13:00:00Z",
            "2026-05-26T15:30:00Z",
            "2026-05-27T11:30:00Z",
        ]

    async def test_per_peer_available_fields_present(
        self, result: FourPartyResult
    ) -> None:
        # ``s2MarkPeerChips`` reads ``ex.peer_response_payload.candidates``
        # for chip elimination, but the funnel summary panel reads the
        # per-peer available lists off ``intersection.*_available``.
        assert result.intersection is not None
        assert isinstance(result.intersection.marius_available, list)
        assert isinstance(result.intersection.wren_available, list)
        assert isinstance(result.intersection.atlas_available, list)

    async def test_progressive_narrowing_fields_present(
        self, result: FourPartyResult
    ) -> None:
        # ``after_marius``, ``after_wren``, ``after_atlas`` drive the funnel's
        # cumulative-intersection columns.
        assert result.intersection is not None
        assert isinstance(result.intersection.after_marius, list)
        assert isinstance(result.intersection.after_wren, list)
        assert isinstance(result.intersection.after_atlas, list)

    async def test_funnel_narrows_to_single_slot(
        self, result: FourPartyResult
    ) -> None:
        # Funnel column reading: starts at 3, must narrow to 1 by the time
        # all three peers have weighed in.
        assert result.intersection is not None
        assert len(result.intersection.iris_candidates) == 3
        assert result.intersection.after_atlas == ["2026-05-26T13:00:00Z"]

    async def test_intersection_chosen_slot_matches_top_level(
        self, result: FourPartyResult
    ) -> None:
        # ``s2ChosenChip`` reads the top-level chosen_slot; the funnel's
        # final column mirrors ``intersection.chosen_slot``. They must agree.
        assert result.intersection is not None
        assert result.intersection.chosen_slot == result.chosen_slot


# ---------------------------------------------------------------------------
# 4. Peer summaries — ledger panel reads ``*_summary.all_ledger_entries``.
# ---------------------------------------------------------------------------


class TestPeerSummaryContract:
    async def test_three_peer_summaries_present(
        self, result: FourPartyResult
    ) -> None:
        # ``runScenario2`` iterates exactly ["marius_summary", "wren_summary",
        # "atlas_summary"] and pulls ``all_ledger_entries`` off each.
        assert result.marius_summary is not None
        assert result.wren_summary is not None
        assert result.atlas_summary is not None

    async def test_all_ledger_entries_non_empty(
        self, result: FourPartyResult
    ) -> None:
        # Each peer participates in one query + one confirm bilateral.
        # Each bilateral records two residues on the peer side (receive
        # + emit), so each summary should hold at least four entries.
        assert len(result.marius_summary.all_ledger_entries) >= 4
        assert len(result.wren_summary.all_ledger_entries) >= 4
        assert len(result.atlas_summary.all_ledger_entries) >= 4

    async def test_peer_ledger_entries_have_ui_fields(
        self, result: FourPartyResult
    ) -> None:
        # The peer ledger panel pulls the same field set off each entry.
        for summary in (
            result.marius_summary,
            result.wren_summary,
            result.atlas_summary,
        ):
            for entry in summary.all_ledger_entries:
                # ``sequence`` is used as a sort key, so it must be int.
                assert isinstance(entry.sequence, int)
                assert isinstance(entry.timestamp, str) and entry.timestamp
                assert isinstance(entry.action_type, str) and entry.action_type
                assert isinstance(entry.operation, str) and entry.operation
                assert isinstance(entry.actor, str) and entry.actor
                assert isinstance(entry.counterpart, str) and entry.counterpart
                assert isinstance(entry.payload_hash, str) and entry.payload_hash


# ---------------------------------------------------------------------------
# 5. Iris ledger — left ledger panel reads ``iris_ledger[*].<field>``.
# ---------------------------------------------------------------------------


class TestIrisLedgerContract:
    async def test_iris_ledger_present_and_non_empty(
        self, result: FourPartyResult
    ) -> None:
        # Six bilateral exchanges produce 12 Iris residues (emit + receive
        # per bilateral). We assert presence + non-emptiness rather than
        # the exact count, to allow harmless additions of housekeeping
        # entries without breaking the UI contract.
        assert isinstance(result.iris_ledger, list)
        assert len(result.iris_ledger) >= 12

    async def test_iris_ledger_entry_field_paths(
        self, result: FourPartyResult
    ) -> None:
        # The exact field paths the UI maps in ``runScenario2``:
        #   seq         <- r.sequence
        #   ts          <- r.timestamp
        #   action      <- r.action_type
        #   op          <- r.operation
        #   actor       <- r.actor
        #   counterpart <- r.counterpart
        #   hash        <- r.payload_hash
        for entry in result.iris_ledger:
            assert isinstance(entry.sequence, int)
            assert isinstance(entry.timestamp, str) and entry.timestamp
            assert isinstance(entry.action_type, str) and entry.action_type
            assert isinstance(entry.operation, str) and entry.operation
            assert isinstance(entry.actor, str) and entry.actor
            assert isinstance(entry.counterpart, str) and entry.counterpart
            assert isinstance(entry.payload_hash, str) and entry.payload_hash
