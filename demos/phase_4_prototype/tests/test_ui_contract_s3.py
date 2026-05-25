"""UI-backend contract tests for Scenario 3 (cascading reschedule).

The browser UI (Track C, ``demos/phase_4_prototype/index.html``) consumes
the JSON projection of :class:`CascadingResult` over the
``/api/scenarios/cascading`` endpoint. The JS in ``runScenario3()``,
``s3ShowReasoningTrace()``, ``s3PopulateTaskIds()`` and the ledger /
exchange-badge renderers reach into specific field paths on that result.

These contract tests exercise the Python ``run_cascading()`` directly and
assert each field path the JS reads is present, well-typed, and obeys
the cross-field invariants the UI's tessera-fit badges depend on. No
browser is launched; we only verify the shape contract.

``asyncio_mode = "auto"`` is set in the repo ``pyproject.toml``; ``async
def`` test functions are picked up directly.
"""

from __future__ import annotations

import pytest

from demos.phase_4_prototype.server.cascading import (
    ATLAS,
    IRIS,
    MARIUS,
    run_cascading,
)


# A single real cascade is expensive (two listeners, real Ed25519, real
# SQLite ledgers). Share one result across the whole module so the
# contract suite runs in roughly the same time as one happy-path run.
@pytest.fixture(scope="module")
async def cascade_result():
    return await run_cascading()


# -- Top-level principal-id fields ----------------------------------------


class TestPrincipalIdFields:
    async def test_iris_principal_id_present(self, cascade_result) -> None:
        assert isinstance(cascade_result.iris_principal_id, str)
        assert cascade_result.iris_principal_id == IRIS

    async def test_marius_principal_id_present(self, cascade_result) -> None:
        assert isinstance(cascade_result.marius_principal_id, str)
        assert cascade_result.marius_principal_id == MARIUS

    async def test_atlas_principal_id_present(self, cascade_result) -> None:
        assert isinstance(cascade_result.atlas_principal_id, str)
        assert cascade_result.atlas_principal_id == ATLAS


# -- reasoner_trace --------------------------------------------------------


class TestReasonerTrace:
    async def test_requested_slot_present(self, cascade_result) -> None:
        assert isinstance(cascade_result.reasoner_trace.requested_slot, str)
        assert cascade_result.reasoner_trace.requested_slot != ""

    async def test_blocking_event_title_present(self, cascade_result) -> None:
        assert isinstance(cascade_result.reasoner_trace.blocking_event_title, str)
        assert cascade_result.reasoner_trace.blocking_event_title != ""

    async def test_blocking_event_attendee_present(self, cascade_result) -> None:
        assert isinstance(
            cascade_result.reasoner_trace.blocking_event_attendee, str
        )
        assert cascade_result.reasoner_trace.blocking_event_attendee != ""

    async def test_proposed_new_slot_present(self, cascade_result) -> None:
        assert isinstance(cascade_result.reasoner_trace.proposed_new_slot, str)
        assert cascade_result.reasoner_trace.proposed_new_slot != ""

    async def test_reason_is_non_empty_string(self, cascade_result) -> None:
        assert isinstance(cascade_result.reasoner_trace.reason, str)
        assert len(cascade_result.reasoner_trace.reason) > 0

    async def test_reason_mentions_requested_slot(self, cascade_result) -> None:
        # Basic sanity: the reasoner's explanation should reference the
        # slot it was asked about, since the UI shows the trace and the
        # slot side-by-side.
        assert (
            cascade_result.reasoner_trace.requested_slot
            in cascade_result.reasoner_trace.reason
        )


# -- BilateralExchangeDTO shape for all three exchanges -------------------


class TestExchangeIrisMariusProposal:
    async def test_proposal_payload_hash(self, cascade_result) -> None:
        ex = cascade_result.exchange_iris_marius_proposal
        assert isinstance(ex.proposal_payload_hash, str)
        assert ex.proposal_payload_hash != ""

    async def test_acceptance_payload_hash(self, cascade_result) -> None:
        ex = cascade_result.exchange_iris_marius_proposal
        assert isinstance(ex.acceptance_payload_hash, str)
        assert ex.acceptance_payload_hash != ""

    async def test_task_id(self, cascade_result) -> None:
        ex = cascade_result.exchange_iris_marius_proposal
        assert isinstance(ex.task_id, str)
        assert ex.task_id != ""

    async def test_exchange_label(self, cascade_result) -> None:
        assert isinstance(
            cascade_result.exchange_iris_marius_proposal.exchange_label, str
        )
        assert cascade_result.exchange_iris_marius_proposal.exchange_label != ""

    async def test_initiator_and_responder(self, cascade_result) -> None:
        ex = cascade_result.exchange_iris_marius_proposal
        assert ex.initiator == IRIS
        assert ex.responder == MARIUS


class TestExchangeMariusAtlas:
    async def test_proposal_payload_hash(self, cascade_result) -> None:
        ex = cascade_result.exchange_marius_atlas
        assert isinstance(ex.proposal_payload_hash, str)
        assert ex.proposal_payload_hash != ""

    async def test_acceptance_payload_hash(self, cascade_result) -> None:
        ex = cascade_result.exchange_marius_atlas
        assert isinstance(ex.acceptance_payload_hash, str)
        assert ex.acceptance_payload_hash != ""

    async def test_task_id(self, cascade_result) -> None:
        ex = cascade_result.exchange_marius_atlas
        assert isinstance(ex.task_id, str)
        assert ex.task_id != ""


class TestExchangeMariusIrisAcceptance:
    async def test_proposal_payload_hash(self, cascade_result) -> None:
        ex = cascade_result.exchange_marius_iris_acceptance
        assert isinstance(ex.proposal_payload_hash, str)
        assert ex.proposal_payload_hash != ""

    async def test_acceptance_payload_hash(self, cascade_result) -> None:
        ex = cascade_result.exchange_marius_iris_acceptance
        assert isinstance(ex.acceptance_payload_hash, str)
        assert ex.acceptance_payload_hash != ""

    async def test_task_id(self, cascade_result) -> None:
        ex = cascade_result.exchange_marius_iris_acceptance
        assert isinstance(ex.task_id, str)
        assert ex.task_id != ""


# -- task_id sharing / distinctness pattern -------------------------------


class TestTaskIdPattern:
    """The UI's task-id bar prints ``task_id_1`` once for exchanges A+C
    and ``task_id_2`` for exchange B (see ``s3PopulateTaskIds``)."""

    async def test_task_id_1_shared_by_a_and_c(self, cascade_result) -> None:
        a = cascade_result.exchange_iris_marius_proposal
        c = cascade_result.exchange_marius_iris_acceptance
        assert a.task_id == c.task_id

    async def test_task_id_2_distinct_from_task_id_1(
        self, cascade_result
    ) -> None:
        a = cascade_result.exchange_iris_marius_proposal
        b = cascade_result.exchange_marius_atlas
        assert b.task_id != a.task_id


# -- marius_reschedule_proposal payload dict ------------------------------


class TestMariusReschedulePayload:
    async def test_candidates_present(self, cascade_result) -> None:
        assert "candidates" in cascade_result.marius_reschedule_proposal
        assert isinstance(
            cascade_result.marius_reschedule_proposal["candidates"], list
        )
        assert len(cascade_result.marius_reschedule_proposal["candidates"]) >= 1

    async def test_duration_minutes_present(self, cascade_result) -> None:
        assert (
            "duration_minutes" in cascade_result.marius_reschedule_proposal
        )
        assert isinstance(
            cascade_result.marius_reschedule_proposal["duration_minutes"], int
        )

    async def test_constraint_hints_present(self, cascade_result) -> None:
        assert (
            "constraint_hints" in cascade_result.marius_reschedule_proposal
        )
        assert isinstance(
            cascade_result.marius_reschedule_proposal["constraint_hints"], dict
        )


# -- atlas_acceptance_payload ---------------------------------------------


class TestAtlasAcceptancePayload:
    async def test_payload_is_dict(self, cascade_result) -> None:
        assert isinstance(cascade_result.atlas_acceptance_payload, dict)

    async def test_payload_has_candidates(self, cascade_result) -> None:
        # The UI renders ``candidates`` and ``duration_minutes`` from the
        # acceptance payload (see runScenario3 STEP 5).
        assert "candidates" in cascade_result.atlas_acceptance_payload

    async def test_payload_has_duration_minutes(self, cascade_result) -> None:
        assert "duration_minutes" in cascade_result.atlas_acceptance_payload


# -- Ledger entry shape (each entry maps 1:1 to a UI ledger row) ---------


def _assert_ledger_entry_shape(entry) -> None:
    assert isinstance(entry.sequence, int)
    assert isinstance(entry.timestamp, str) and entry.timestamp != ""
    assert isinstance(entry.action_type, str) and entry.action_type != ""
    assert isinstance(entry.operation, str) and entry.operation != ""
    assert isinstance(entry.actor, str) and entry.actor != ""
    assert isinstance(entry.counterpart, str) and entry.counterpart != ""
    assert isinstance(entry.payload_hash, str) and entry.payload_hash != ""


class TestLedgerEntryShapes:
    async def test_iris_ledger_entries(self, cascade_result) -> None:
        assert isinstance(cascade_result.iris_ledger, list)
        assert len(cascade_result.iris_ledger) >= 1
        for entry in cascade_result.iris_ledger:
            _assert_ledger_entry_shape(entry)

    async def test_marius_ledger_entries(self, cascade_result) -> None:
        assert isinstance(cascade_result.marius_ledger, list)
        assert len(cascade_result.marius_ledger) >= 1
        for entry in cascade_result.marius_ledger:
            _assert_ledger_entry_shape(entry)

    async def test_atlas_ledger_entries(self, cascade_result) -> None:
        assert isinstance(cascade_result.atlas_ledger, list)
        assert len(cascade_result.atlas_ledger) >= 1
        for entry in cascade_result.atlas_ledger:
            _assert_ledger_entry_shape(entry)


# -- Cascade-hash invariants the tessera-fit badges depend on -----------


class TestCascadeHashInvariants:
    """The three SVG tessera-fit badges only line up if these
    cross-ledger payload-hash equalities hold."""

    async def test_iris_to_marius_proposal_hash_matches(
        self, cascade_result
    ) -> None:
        # Exchange A's first signed envelope: Iris emits a proposal,
        # Marius receives it. Same JCS bytes ⇒ same SHA-256.
        assert (
            cascade_result.iris_ledger[0].payload_hash
            == cascade_result.marius_ledger[0].payload_hash
        )

    async def test_marius_to_atlas_proposal_hash_matches(
        self, cascade_result
    ) -> None:
        # Exchange B's first signed envelope: Marius emits a reschedule
        # proposal, Atlas receives it.
        assert (
            cascade_result.marius_ledger[1].payload_hash
            == cascade_result.atlas_ledger[0].payload_hash
        )

    async def test_atlas_to_marius_acceptance_hash_matches(
        self, cascade_result
    ) -> None:
        # Exchange B's acceptance: Atlas emits acceptance, Marius
        # receives it.
        assert (
            cascade_result.marius_ledger[2].payload_hash
            == cascade_result.atlas_ledger[1].payload_hash
        )

    async def test_marius_to_iris_acceptance_hash_matches(
        self, cascade_result
    ) -> None:
        # Exchange C's acceptance: Marius emits acceptance, Iris
        # receives it.
        assert (
            cascade_result.marius_ledger[3].payload_hash
            == cascade_result.iris_ledger[1].payload_hash
        )


# -- Marius single hash-chain sequences across two task IDs ---------------


class TestMariusHashChainSequences:
    """The UI's Marius ledger panel renders one hash chain across both
    task IDs. The four entries must carry sequences [0, 1, 2, 3]."""

    async def test_marius_sequences_are_contiguous_chain(
        self, cascade_result
    ) -> None:
        sequences = [entry.sequence for entry in cascade_result.marius_ledger]
        assert sequences == [0, 1, 2, 3]


# -- duration_ms ----------------------------------------------------------


class TestDurationMs:
    async def test_duration_ms_is_int(self, cascade_result) -> None:
        assert isinstance(cascade_result.duration_ms, int)

    async def test_duration_ms_is_non_negative(self, cascade_result) -> None:
        # The UI prints "real cascade in {duration_ms}ms" in the status
        # line; a negative value would render absurdly.
        assert cascade_result.duration_ms >= 0
