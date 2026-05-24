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

    async def test_produces_all_assertion_numbers(self, tmp_path: Path) -> None:
        result = await run_demo(data_dir=tmp_path, reference_time=_REF)
        numbers = [a.number for a in result.assertions]
        # Phase 1 SPEC §5 enumerates 1..14; several numbers appear twice
        # (per-ledger checks evaluated on each side). Phase 3 adds the
        # scoped-disclosure assertions #15 and #16 (run once each, against
        # the proposal leg). #17 (force-injection) lives in its own
        # pytest class below rather than in the orchestrator's runtime
        # check, per SPEC §8 — it requires a deliberately misbehaving
        # gateway and so doesn't fit the happy-path orchestrator loop.
        assert set(numbers) == set(range(1, 17))

    async def test_all_assertions_pass(self, tmp_path: Path) -> None:
        result = await run_demo(data_dir=tmp_path, reference_time=_REF)
        failed = [a for a in result.assertions if not a.passed]
        assert not failed, _format_failures(failed)
        assert result.all_passed

    async def test_ledger_files_persist_after_run(self, tmp_path: Path) -> None:
        """The cold-reload contract requires the SQLite files to still exist
        after the orchestrator returns — the test could re-open them itself.

        Phase 2: directory.sqlite is also written.
        Phase 3: per-principal policy stores are also written. Check the
        two agent ledgers specifically (by name) rather than counting all
        SQLite files.
        """
        await run_demo(data_dir=tmp_path, reference_time=_REF)
        ledger_a = tmp_path / "user-a_phase1_local.sqlite"
        ledger_b = tmp_path / "user-b_phase1_local.sqlite"
        assert ledger_a.is_file(), f"A's ledger missing at {ledger_a}"
        assert ledger_b.is_file(), f"B's ledger missing at {ledger_b}"
        # Phase 3: the policy stores should also persist.
        policy_a = tmp_path / "user-a_phase1_local_policy.sqlite"
        policy_b = tmp_path / "user-b_phase1_local_policy.sqlite"
        assert policy_a.is_file(), f"A's policy store missing at {policy_a}"
        assert policy_b.is_file(), f"B's policy store missing at {policy_b}"

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


class TestAssertion17ForceInjection:
    """SPEC §8 #17 — defense-in-depth must fire if the engine is buggy.

    The orchestrator can't reasonably ship a buggy engine into the happy
    path, so #17 lives as its own regression test: construct an A-side
    Mesherra with a deliberately misbehaving PolicyEngine that returns
    ALLOW_SCOPED while leaving the blocked field present, then prove the
    OutboundGateway's re-check raises PolicyScopingFailed before signing.
    """

    async def test_buggy_engine_caught_before_send(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from typing import Any

        import pytest
        from mesherra.a2a_adapter import A2AAdapter
        from mesherra.crypto.primitives import Signer
        from mesherra.gateways.outbound import PolicyScopingFailed
        from mesherra.identity import StaticDirectoryClient
        from mesherra.models.primitives import Operation
        from mesherra.policy import (
            PolicyDecision,
            PolicyEngine,
            PolicyStore,
            Verdict,
            sign_policy_doc,
        )
        from mesherra.provenance.ledger import ProvenanceLedger
        from mesherra.sdk import Mesherra

        from policy_template import build_default_meshycal_policy

        class BuggyEngine(PolicyEngine):
            def evaluate(self, **kwargs: Any) -> PolicyDecision:
                payload = kwargs["payload"]
                # Tamper just enough to *not* be JCS-equal to input — but
                # leave calendar_titles intact so the gateway's
                # defense-in-depth re-check catches the omission.
                tampered = dict(payload)
                tampered["__buggy_marker__"] = 1
                return PolicyDecision(
                    verdict=Verdict.ALLOW_SCOPED,
                    scoped_payload=tampered,
                    matched_rule_count=1,
                )

        # Two agents, A wired with the buggy engine. B has no listener
        # because we expect to never reach the wire.
        a_signer = Signer.generate()
        b_signer = Signer.generate()
        a_principal = "user-a@phase3-injection.local"
        b_principal = "user-b@phase3-injection.local"
        directory = StaticDirectoryClient({
            a_principal: a_signer.public_key_b64(),
            b_principal: b_signer.public_key_b64(),
        })
        a_ledger = ProvenanceLedger(
            db_path=tmp_path / "a_ledger.sqlite", ledger_owner=a_principal,
        )
        a_store = PolicyStore(
            db_path=tmp_path / "a_policy.sqlite",
            principal_id=a_principal,
            public_key_b64=a_signer.public_key_b64(),
        )
        a_store.save_signed(
            sign_policy_doc(
                doc=build_default_meshycal_policy(principal_id=a_principal),
                signer=a_signer,
            )
        )
        a_sdk = Mesherra(
            principal_id=a_principal,
            signer=a_signer,
            ledger=a_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=a_store,
            policy_engine=BuggyEngine(),
        )

        try:
            with pytest.raises(PolicyScopingFailed):
                await a_sdk.send_to(
                    peer_url="http://127.0.0.1:1/",  # never reached
                    peer_principal_id=b_principal,
                    payload={
                        "candidates": ["2026-05-26T14:00:00Z"],
                        "duration_minutes": 30,
                        # The blocked field the buggy engine "forgot" to strip.
                        "calendar_titles": ["should-never-leak"],
                    },
                    payload_schema="meshycal.scheduling/proposal-v1",
                    operation=Operation.PROPOSAL,
                )
            # No residue should have been written.
            assert a_ledger.get_all() == []
        finally:
            a_store.close()
            a_ledger.close()


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
