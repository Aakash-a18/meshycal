"""Tests for the cascading-reschedule scenario (Track C, Phase 4).

Exercises the §10 test plan from
``demos/phase_4_prototype/server/SCENARIO_3_DESIGN.md``:

* Happy path — ledger lengths, ordering, reasoner trace fields.
* Reasoner ``None`` branch — :class:`CascadeAbortedError` is raised.
* Tessera-fits — proposal/acceptance payload hashes match across
  Iris↔Marius (exchanges A and C) and Marius↔Atlas (exchange B).
* ``task_id`` relationships — exchanges A and C share ``task_id_1``;
  exchange B uses a distinct ``task_id_2``.
* Marius' single hash chain — sequences ``[0, 1, 2, 3]`` across both
  task IDs.
* Scoped payload — Iris' wire payload omits ``calendar_titles`` and
  ``attendee_emails``.
* Calendar deltas — Marius' 14:00 leaves and 16:00 arrives; Iris gains
  14:00; Atlas gains 16:00.

These tests boot real Mesherra listeners on localhost, exchange real
signed envelopes, and read real SQLite-backed ledgers in a tempdir.
``asyncio_mode = "auto"`` is set in ``pyproject.toml``; ``async def``
test functions are picked up directly without an ``@pytest.mark.asyncio``
decorator.
"""

from __future__ import annotations

import pytest

from demos.phase_4_prototype.server.cascading import (
    ATLAS,
    IRIS,
    MARIUS,
    CascadeAbortedError,
    run_cascading,
)


# -- Happy path -----------------------------------------------------------


class TestHappyPath:
    async def test_principal_ids(self) -> None:
        result = await run_cascading()
        assert result.iris_principal_id == IRIS
        assert result.marius_principal_id == MARIUS
        assert result.atlas_principal_id == ATLAS

    async def test_ledger_lengths(self) -> None:
        result = await run_cascading()
        assert len(result.iris_ledger) == 2
        assert len(result.marius_ledger) == 4
        assert len(result.atlas_ledger) == 2

    async def test_iris_ledger_order(self) -> None:
        result = await run_cascading()
        assert result.iris_ledger[0].action_type == "emit"
        assert result.iris_ledger[0].operation == "proposal"
        assert result.iris_ledger[1].action_type == "receive"
        assert result.iris_ledger[1].operation == "acceptance"

    async def test_marius_ledger_order(self) -> None:
        result = await run_cascading()
        assert result.marius_ledger[0].action_type == "receive"
        assert result.marius_ledger[0].operation == "proposal"
        assert result.marius_ledger[1].action_type == "emit"
        assert result.marius_ledger[1].operation == "proposal"
        assert result.marius_ledger[2].action_type == "receive"
        assert result.marius_ledger[2].operation == "acceptance"
        assert result.marius_ledger[3].action_type == "emit"
        assert result.marius_ledger[3].operation == "acceptance"

    async def test_atlas_ledger_order(self) -> None:
        result = await run_cascading()
        assert result.atlas_ledger[0].action_type == "receive"
        assert result.atlas_ledger[0].operation == "proposal"
        assert result.atlas_ledger[1].action_type == "emit"
        assert result.atlas_ledger[1].operation == "acceptance"

    async def test_reasoner_trace_fields(self) -> None:
        result = await run_cascading()
        assert result.reasoner_trace.proposed_new_slot == "2026-06-02T16:00:00Z"
        assert result.reasoner_trace.blocking_event_title == "synthetic-project-sync"
        assert result.reasoner_trace.blocking_event_attendee == ATLAS
        assert result.reasoner_trace.requested_slot == "2026-06-02T14:00:00Z"

    async def test_duration_ms_positive(self) -> None:
        result = await run_cascading()
        assert result.duration_ms > 0


# -- Reasoner-returns-None branch -----------------------------------------


class TestReasonerNoneAborts:
    async def test_null_reasoner_raises_cascade_aborted(self) -> None:
        class NullReasoner:
            def propose_reschedule_target(self, **kwargs):  # noqa: ANN003, ANN201
                return None

        with pytest.raises(CascadeAbortedError, match="no viable reschedule slot"):
            await run_cascading(reasoner=NullReasoner())


# -- Tessera-fits ---------------------------------------------------------


class TestTesseraFits:
    async def test_iris_marius_proposal_fit(self) -> None:
        """Iris' emit (seq 0) == Marius' receive (seq 0) ==
        ``exchange_iris_marius_proposal.proposal_payload_hash``.
        """
        result = await run_cascading()
        assert (
            result.iris_ledger[0].payload_hash
            == result.marius_ledger[0].payload_hash
            == result.exchange_iris_marius_proposal.proposal_payload_hash
        )

    async def test_marius_iris_acceptance_fit(self) -> None:
        """Marius' emit (seq 3) == Iris' receive (seq 1) ==
        ``exchange_marius_iris_acceptance.acceptance_payload_hash``.
        """
        result = await run_cascading()
        assert (
            result.marius_ledger[3].payload_hash
            == result.iris_ledger[1].payload_hash
            == result.exchange_marius_iris_acceptance.acceptance_payload_hash
        )

    async def test_marius_atlas_proposal_fit(self) -> None:
        """Marius' emit (seq 1) == Atlas' receive (seq 0) ==
        ``exchange_marius_atlas.proposal_payload_hash``.
        """
        result = await run_cascading()
        assert (
            result.marius_ledger[1].payload_hash
            == result.atlas_ledger[0].payload_hash
            == result.exchange_marius_atlas.proposal_payload_hash
        )

    async def test_marius_atlas_acceptance_fit(self) -> None:
        """Atlas' emit (seq 1) == Marius' receive (seq 2) ==
        ``exchange_marius_atlas.acceptance_payload_hash``.
        """
        result = await run_cascading()
        assert (
            result.atlas_ledger[1].payload_hash
            == result.marius_ledger[2].payload_hash
            == result.exchange_marius_atlas.acceptance_payload_hash
        )


# -- task_id relationships ------------------------------------------------


class TestTaskIdRelationships:
    async def test_exchanges_a_and_c_share_task_id_1(self) -> None:
        result = await run_cascading()
        assert (
            result.exchange_iris_marius_proposal.task_id
            == result.exchange_marius_iris_acceptance.task_id
        )

    async def test_exchange_b_uses_distinct_task_id_2(self) -> None:
        result = await run_cascading()
        assert (
            result.exchange_marius_atlas.task_id
            != result.exchange_iris_marius_proposal.task_id
        )


# -- Marius' single hash chain -------------------------------------------


class TestMariusHashChain:
    async def test_marius_sequences_are_zero_one_two_three(self) -> None:
        """Marius' four ledger rows span both task IDs but form ONE
        sequence-numbered hash chain (0, 1, 2, 3)."""
        result = await run_cascading()
        sequences = [e.sequence for e in result.marius_ledger]
        assert sequences == [0, 1, 2, 3]


# -- Scoped proposal excludes blocked fields ------------------------------


class TestScopedProposal:
    async def test_calendar_titles_blocked(self) -> None:
        result = await run_cascading()
        assert "calendar_titles" not in result.iris_scoped_proposal

    async def test_attendee_emails_blocked(self) -> None:
        result = await run_cascading()
        assert "attendee_emails" not in result.iris_scoped_proposal

    async def test_candidates_passed_through(self) -> None:
        """Sanity check: the scoped projection still carries the
        allow-listed ``candidates`` field."""
        result = await run_cascading()
        assert "candidates" in result.iris_scoped_proposal


# -- Calendar deltas ------------------------------------------------------


class TestCalendarDeltas:
    async def test_marius_14_00_removed(self) -> None:
        result = await run_cascading()
        marius_before_slots = {e.slot_start for e in result.marius_calendar.before}
        marius_after_slots = {e.slot_start for e in result.marius_calendar.after}
        assert "2026-06-02T14:00:00Z" in marius_before_slots
        assert "2026-06-02T14:00:00Z" not in marius_after_slots

    async def test_marius_16_00_added(self) -> None:
        result = await run_cascading()
        marius_after_slots = {e.slot_start for e in result.marius_calendar.after}
        assert "2026-06-02T16:00:00Z" in marius_after_slots

    async def test_iris_14_00_added(self) -> None:
        result = await run_cascading()
        iris_after_slots = {e.slot_start for e in result.iris_calendar.after}
        assert "2026-06-02T14:00:00Z" in iris_after_slots

    async def test_atlas_16_00_added(self) -> None:
        result = await run_cascading()
        atlas_after_slots = {e.slot_start for e in result.atlas_calendar.after}
        assert "2026-06-02T16:00:00Z" in atlas_after_slots
