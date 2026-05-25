"""Phase 4 prototype scenario 2 — four-party group negotiation tests.

Covers the test plan outlined in
``demos/phase_4_prototype/server/SCENARIO_2_DESIGN.md`` §9:

* Happy-path end-to-end shape (six exchanges, twelve Iris ledger entries,
  four entries per peer summary, positive duration).
* Intersection correctness against the values fixed in §3.
* Ledger hash equality across every bilateral pair.
* Scoped payload never carries blocked fields (`calendar_titles`,
  `attendee_emails`).
* ``_slots_available`` unit cases (one busy block, no busy blocks, all busy).

``pytest-asyncio`` is configured in ``asyncio_mode = "auto"`` (see
``pyproject.toml``), so ``async def`` test functions are picked up directly.
"""

from __future__ import annotations

import pytest

from demos.phase_4_prototype.server.group_negotiation import (
    BilateralExchangeRecord,
    FourPartyResult,
    IntersectionState,
    _slots_available,
    run_four_party,
)


# A module-scoped cached result avoids paying for six bilateral
# Mesherra exchanges in every single test. The negotiation is fully
# deterministic, so a single run is sufficient for all post-hoc
# assertions.
@pytest.fixture(scope="module")
async def four_party_result() -> FourPartyResult:
    return await run_four_party()


# ---------------------------------------------------------------------------
# Test 1 — happy path end-to-end
# ---------------------------------------------------------------------------


class TestHappyPathEndToEnd:
    async def test_success_true(self, four_party_result: FourPartyResult) -> None:
        assert four_party_result.success is True
        assert four_party_result.failure_reason is None

    async def test_chosen_slot_is_tuesday_thirteen_hundred(
        self, four_party_result: FourPartyResult
    ) -> None:
        assert four_party_result.chosen_slot == "2026-05-26T13:00:00Z"

    async def test_six_exchanges_in_correct_order(
        self, four_party_result: FourPartyResult
    ) -> None:
        assert len(four_party_result.exchanges) == 6
        ids = [ex.exchange_id for ex in four_party_result.exchanges]
        assert ids == ["A1", "A2", "A3", "B1", "B2", "B3"]

    async def test_phases_label_query_then_confirm(
        self, four_party_result: FourPartyResult
    ) -> None:
        phases = [ex.phase for ex in four_party_result.exchanges]
        assert phases == ["query", "query", "query", "confirm", "confirm", "confirm"]

    async def test_iris_ledger_has_twelve_entries(
        self, four_party_result: FourPartyResult
    ) -> None:
        # 6 bilaterals * 2 ledger entries (one emit, one receive) on Iris's side.
        assert len(four_party_result.iris_ledger) == 12

    async def test_each_peer_summary_has_four_ledger_entries(
        self, four_party_result: FourPartyResult
    ) -> None:
        # Each peer participates in two bilateral exchanges (one query, one
        # confirm); each bilateral contributes one receive + one emit entry
        # on the peer's ledger.
        assert len(four_party_result.marius_summary.all_ledger_entries) == 4
        assert len(four_party_result.wren_summary.all_ledger_entries) == 4
        assert len(four_party_result.atlas_summary.all_ledger_entries) == 4

    async def test_duration_ms_positive(
        self, four_party_result: FourPartyResult
    ) -> None:
        assert four_party_result.duration_ms > 0


# ---------------------------------------------------------------------------
# Test 2 — intersection correctness
# ---------------------------------------------------------------------------


class TestIntersectionCorrectness:
    async def test_intersection_state_matches_design_section_3(
        self, four_party_result: FourPartyResult
    ) -> None:
        intersection = four_party_result.intersection
        assert isinstance(intersection, IntersectionState)

        # Iris's initial candidates (design §3).
        assert intersection.iris_candidates == [
            "2026-05-26T13:00:00Z",
            "2026-05-26T15:30:00Z",
            "2026-05-27T11:30:00Z",
        ]

        # Marius confirms 13:00 Tue and 11:30 Wed.
        assert intersection.marius_available == [
            "2026-05-26T13:00:00Z",
            "2026-05-27T11:30:00Z",
        ]

        # Wren confirms 13:00 Tue and 15:30 Tue.
        assert intersection.wren_available == [
            "2026-05-26T13:00:00Z",
            "2026-05-26T15:30:00Z",
        ]

        # Atlas confirms only 13:00 Tue.
        assert intersection.atlas_available == ["2026-05-26T13:00:00Z"]

        # Progressive funnel.
        assert intersection.after_marius == [
            "2026-05-26T13:00:00Z",
            "2026-05-27T11:30:00Z",
        ]
        assert intersection.after_wren == ["2026-05-26T13:00:00Z"]
        assert intersection.after_atlas == ["2026-05-26T13:00:00Z"]

        # Chosen slot.
        assert intersection.chosen_slot == "2026-05-26T13:00:00Z"


# ---------------------------------------------------------------------------
# Test 3 — ledger hash equality across every bilateral pair
# ---------------------------------------------------------------------------


class TestLedgerHashEquality:
    async def test_iris_and_peer_first_ledger_hashes_match_per_exchange(
        self, four_party_result: FourPartyResult
    ) -> None:
        # For each bilateral, Iris's first ledger entry (her outbound emit)
        # must reference the same payload hash as the peer's first ledger
        # entry (their inbound receive). This is the load-bearing two-party
        # provenance invariant; it must hold for every one of the six
        # exchanges that make up the group negotiation.
        mismatches: list[str] = []
        for exchange in four_party_result.exchanges:
            assert exchange.iris_ledger_entries, (
                f"{exchange.exchange_id}: Iris ledger entries missing"
            )
            assert exchange.peer_ledger_entries, (
                f"{exchange.exchange_id}: peer ledger entries missing"
            )
            iris_hash = exchange.iris_ledger_entries[0].payload_hash
            peer_hash = exchange.peer_ledger_entries[0].payload_hash
            if iris_hash != peer_hash:
                mismatches.append(
                    f"{exchange.exchange_id} ({exchange.peer}): "
                    f"iris={iris_hash} peer={peer_hash}"
                )
        assert not mismatches, (
            "Ledger hash mismatch in: " + "; ".join(mismatches)
        )


# ---------------------------------------------------------------------------
# Test 4 — scoped payload never contains blocked fields
# ---------------------------------------------------------------------------


class TestScopedPayloadExcludesBlockedFields:
    async def test_no_calendar_titles_or_attendee_emails_in_any_exchange(
        self, four_party_result: FourPartyResult
    ) -> None:
        leaks: list[str] = []
        for exchange in four_party_result.exchanges:
            scoped = exchange.iris_scoped_payload
            if "calendar_titles" in scoped:
                leaks.append(
                    f"{exchange.exchange_id}: calendar_titles present"
                )
            if "attendee_emails" in scoped:
                leaks.append(
                    f"{exchange.exchange_id}: attendee_emails present"
                )
        assert not leaks, (
            "Blocked fields leaked into scoped payload: " + "; ".join(leaks)
        )

    async def test_scoped_payload_only_contains_allow_listed_keys(
        self, four_party_result: FourPartyResult
    ) -> None:
        # Slightly stronger contract: ensure the keys are exactly the
        # allow-listed set per the default MeshyCal policy template.
        allowed = {"candidates", "duration_minutes", "constraint_hints"}
        for exchange in four_party_result.exchanges:
            assert set(exchange.iris_scoped_payload.keys()).issubset(allowed), (
                f"{exchange.exchange_id}: unexpected keys "
                f"{set(exchange.iris_scoped_payload.keys()) - allowed}"
            )


# ---------------------------------------------------------------------------
# Test 5 — `_slots_available` pure unit test
# ---------------------------------------------------------------------------


class TestSlotsAvailableUnit:
    def test_one_busy_block_filters_overlapping_slot(self) -> None:
        candidates = [
            "2026-05-26T13:00:00Z",
            "2026-05-26T15:30:00Z",
            "2026-05-27T11:30:00Z",
        ]
        # Single busy block exactly overlapping the 15:30 candidate
        # (Marius's "synthetic-review-session" pattern from §3).
        busy = [("2026-05-26T15:30:00Z", "2026-05-26T16:30:00Z")]
        available = _slots_available(candidates, busy, duration_minutes=30)
        assert available == [
            "2026-05-26T13:00:00Z",
            "2026-05-27T11:30:00Z",
        ]

    def test_no_busy_blocks_returns_all_candidates(self) -> None:
        candidates = [
            "2026-05-26T13:00:00Z",
            "2026-05-26T15:30:00Z",
            "2026-05-27T11:30:00Z",
        ]
        available = _slots_available(candidates, [], duration_minutes=30)
        assert available == candidates

    def test_all_candidates_busy_returns_empty_list(self) -> None:
        candidates = [
            "2026-05-26T13:00:00Z",
            "2026-05-26T15:30:00Z",
            "2026-05-27T11:30:00Z",
        ]
        # One busy block per candidate, each exactly covering the 30-min
        # window starting at the candidate.
        busy = [
            ("2026-05-26T13:00:00Z", "2026-05-26T13:30:00Z"),
            ("2026-05-26T15:30:00Z", "2026-05-26T16:00:00Z"),
            ("2026-05-27T11:30:00Z", "2026-05-27T12:00:00Z"),
        ]
        available = _slots_available(candidates, busy, duration_minutes=30)
        assert available == []


# ---------------------------------------------------------------------------
# Sanity — `BilateralExchangeRecord` typing on the cached result.
# Not part of §9 explicitly, but a cheap smoke check that the cached
# fixture returned the right shape and protects against accidental
# regressions in the record type.
# ---------------------------------------------------------------------------


class TestRecordShape:
    async def test_every_exchange_is_a_bilateral_exchange_record(
        self, four_party_result: FourPartyResult
    ) -> None:
        for exchange in four_party_result.exchanges:
            assert isinstance(exchange, BilateralExchangeRecord)
            assert exchange.coordinator == "iris@meshycal.demo"
            assert exchange.task_id != ""
