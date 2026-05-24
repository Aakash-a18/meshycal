"""Integration test for the Phase 1 demo orchestrator.

Asserts that ``run_demo`` produces the expected ``DemoResult`` shape and
that all 14 SPEC §5 assertions pass on a happy-path run. This is the
load-bearing demo-success check.

Also includes the assertion-#13 regression: rewriting a payload sidecar
on disk (to simulate the "malicious B invents a slot" attack the
theory-aligner called out) must cause assertion #13 to fail. Without
that property, #13 doesn't actually enforce what SPEC §5 wants.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from run_demo import (
    AssertionResult,
    DemoResult,
    _evaluate_assertions,
    _write_payload,
    run_demo,
)

_REF = datetime(2026, 5, 25, 8, 0, tzinfo=timezone.utc)


class TestRunDemoHappyPath:
    async def test_returns_demo_result_with_task_and_context(self, tmp_path: Path) -> None:
        result = await run_demo(data_dir=tmp_path, reference_time=_REF)
        assert isinstance(result, DemoResult)
        assert result.task_id != ""
        assert result.context_id != ""

    async def test_produces_14_assertions(self, tmp_path: Path) -> None:
        result = await run_demo(data_dir=tmp_path, reference_time=_REF)
        numbers = [a.number for a in result.assertions]
        # SPEC §5 enumerates 1..14. Several numbers appear twice (per-ledger
        # checks evaluated on each side); 14 distinct numbers must appear.
        assert set(numbers) == set(range(1, 15))

    async def test_all_assertions_pass(self, tmp_path: Path) -> None:
        result = await run_demo(data_dir=tmp_path, reference_time=_REF)
        failed = [a for a in result.assertions if not a.passed]
        assert not failed, _format_failures(failed)
        assert result.all_passed

    async def test_ledger_files_persist_after_run(self, tmp_path: Path) -> None:
        """The cold-reload contract requires the SQLite files to still exist
        after the orchestrator returns — the test could re-open them itself.

        Phase 2 sub-step 4: the orchestrator also writes a ``directory.sqlite``
        for the live Directory service; we check the two agent ledgers
        specifically rather than counting all SQLite files.
        """
        await run_demo(data_dir=tmp_path, reference_time=_REF)
        ledger_a = tmp_path / "user-a_phase1_local.sqlite"
        ledger_b = tmp_path / "user-b_phase1_local.sqlite"
        assert ledger_a.is_file(), f"A's ledger missing at {ledger_a}"
        assert ledger_b.is_file(), f"B's ledger missing at {ledger_b}"

    async def test_calendar_fixtures_written_to_data_dir(self, tmp_path: Path) -> None:
        await run_demo(data_dir=tmp_path, reference_time=_REF)
        cal_files = list(tmp_path.glob("*_calendar.json"))
        assert len(cal_files) == 2

    async def test_creates_data_dir_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested" / "demo"
        assert not nested.exists()
        result = await run_demo(data_dir=nested, reference_time=_REF)
        assert nested.is_dir()
        assert result.all_passed


def _format_failures(failures: list[AssertionResult]) -> str:
    return "\n".join(
        f"  #{a.number}: {a.name}\n    {a.detail}" for a in failures
    )


class TestAssertion13CatchesInventedSlot:
    """Assertion #13 must catch the attack the theory-aligner called out:
    a malicious B emitting an acceptance Residue for a slot it invented
    rather than one A actually proposed. Without #13, this attack would
    pass #1–#12 (B's own signature is valid, hashes are internally
    consistent) but violate the SPEC §5 #13 invariant.

    We construct the counterexample directly: a real proposal sidecar
    referenced by A's emit Residue, and a B-emit Residue whose
    payload_hash points to an acceptance payload built around a slot NOT
    in the proposal. #13 must fail; #1–12 are not exercised here (this
    test is specifically about #13's load-bearing logic).
    """

    def test_check_passes_when_acceptance_slot_is_in_proposal(
        self, tmp_path: Path
    ) -> None:
        from mesherra.crypto.primitives import canonical_json, content_hash

        from run_demo import _check_accepted_slot_was_proposed

        proposal = {
            "candidates": ["2026-05-25T09:00:00Z", "2026-05-25T10:00:00Z"],
            "duration_minutes": 30,
        }
        # Honest B picks the second candidate.
        honest_acceptance = {
            "candidates": ["2026-05-25T10:00:00Z"],
            "duration_minutes": 30,
        }
        payloads = tmp_path / "payloads"
        payloads.mkdir()
        _write_payload(payloads, proposal)
        _write_payload(payloads, honest_acceptance)

        proposal_hash = content_hash(canonical_json(proposal))
        acceptance_hash = content_hash(canonical_json(honest_acceptance))

        a_emit = _make_fake_residue(payload_hash=proposal_hash, sequence=0, operation_value="proposal")
        b_emit = _make_fake_residue(
            payload_hash=acceptance_hash, sequence=1, operation_value="acceptance"
        )

        result = _check_accepted_slot_was_proposed(
            a_emit=a_emit, b_emit=b_emit, payloads_dir=payloads, number=13
        )
        assert result.passed, result.detail

    def test_check_fails_when_acceptance_slot_is_invented(self, tmp_path: Path) -> None:
        """The malicious-B counterexample from the theory-aligner."""
        from mesherra.crypto.primitives import canonical_json, content_hash

        from run_demo import _check_accepted_slot_was_proposed

        proposal = {
            "candidates": ["2026-05-25T09:00:00Z", "2026-05-25T10:00:00Z"],
            "duration_minutes": 30,
        }
        # B claims to have accepted a slot that was NEVER offered.
        invented_acceptance = {
            "candidates": ["2099-01-01T00:00:00Z"],
            "duration_minutes": 30,
        }
        payloads = tmp_path / "payloads"
        payloads.mkdir()
        _write_payload(payloads, proposal)
        _write_payload(payloads, invented_acceptance)

        proposal_hash = content_hash(canonical_json(proposal))
        invented_hash = content_hash(canonical_json(invented_acceptance))

        a_emit = _make_fake_residue(payload_hash=proposal_hash, sequence=0, operation_value="proposal")
        b_emit = _make_fake_residue(
            payload_hash=invented_hash, sequence=1, operation_value="acceptance"
        )

        result = _check_accepted_slot_was_proposed(
            a_emit=a_emit, b_emit=b_emit, payloads_dir=payloads, number=13
        )
        assert not result.passed
        # The failure message must name the invented slot AND A's proposed
        # candidates so an operator can debug it.
        assert "2099-01-01" in result.detail
        assert "2026-05-25T09:00:00Z" in result.detail

    def test_check_fails_when_proposal_sidecar_is_missing(self, tmp_path: Path) -> None:
        """If the proposal payload disappeared from disk, #13 cannot
        prove the invariant — it must fail rather than silently pass."""
        from run_demo import _check_accepted_slot_was_proposed

        payloads = tmp_path / "payloads"
        payloads.mkdir()
        # Don't write any sidecars.

        a_emit = _make_fake_residue(payload_hash="a" * 64, sequence=0, operation_value="proposal")
        b_emit = _make_fake_residue(payload_hash="b" * 64, sequence=1, operation_value="acceptance")

        result = _check_accepted_slot_was_proposed(
            a_emit=a_emit, b_emit=b_emit, payloads_dir=payloads, number=13
        )
        assert not result.passed
        assert "missing" in result.detail


def _make_fake_residue(*, payload_hash: str, sequence: int, operation_value: str):
    """Construct a Residue with crafted fields for #13-only checks.

    Bypasses signature validity (which #3 covers) so the test focuses
    purely on #13's payload-derivation logic.
    """
    from mesherra.models.primitives import ActionType, Operation, Residue

    return Residue(
        version=1,
        ledger_owner="user-a@phase1.local" if operation_value == "proposal" else "user-b@phase1.local",
        task_id="task-fake-1",
        context_id="ctx-fake-1",
        sequence=sequence,
        previous_hash="" if sequence == 0 else "f" * 64,
        timestamp="2026-05-25T08:00:00Z",
        actor="user-a@phase1.local" if operation_value == "proposal" else "user-b@phase1.local",
        counterpart="user-b@phase1.local" if operation_value == "proposal" else "user-a@phase1.local",
        action_type=ActionType.EMIT,
        operation=Operation(operation_value),
        payload_hash=payload_hash,
        payload_schema="meshycal.scheduling/proposal-v1",
        signature="fake-sig-bytes-not-validated-here",
    )
