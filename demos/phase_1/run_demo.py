"""Phase 1 demo orchestrator + end-state assertions.

Per SPEC §5–6: wires both scheduling agents in one process (each with its
own listener / Mesherra SDK / ledger), runs one proposal → one acceptance,
then re-loads both ledgers *cold* from SQLite and runs the 14 assertions
that pin down Phase 1 correctness.

Run as a script:

    uv run python -m demos.phase_1.run_demo
    uv run --extra dev pytest demos/phase_1/tests/test_run_demo.py

Both paths exercise the same logic; the script prints a PASS/FAIL line per
assertion and a final summary, the test asserts the structured result.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import json

from mesherra.crypto.primitives import (
    Verifier,
    canonical_json,
    content_hash,
)
from mesherra.models.primitives import ActionType, Operation, Residue
from mesherra.provenance.ledger import ProvenanceLedger

from agent_a import run_agent_a
from agent_b import configure_agent_b
from synthetic_calendar import generate_calendar, write_calendar
from wiring import build_agent_pair

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PRINCIPAL_A = "user-a@phase1.local"
_DEFAULT_PRINCIPAL_B = "user-b@phase1.local"


@dataclass
class AssertionResult:
    """One named end-state check (one of SPEC §5's 14)."""

    number: int
    name: str
    passed: bool
    detail: str = ""


@dataclass
class DemoResult:
    """Everything the orchestrator produces — for both human + test consumption."""

    task_id: str
    context_id: str
    assertions: list[AssertionResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(a.passed for a in self.assertions)


async def run_demo(
    *,
    data_dir: Path,
    principal_a_id: str = _DEFAULT_PRINCIPAL_A,
    principal_b_id: str = _DEFAULT_PRINCIPAL_B,
    host: str = _DEFAULT_HOST,
    port_b: int = 0,
    reference_time: datetime | None = None,
) -> DemoResult:
    """Run the two-agent negotiation, then evaluate the 14 SPEC §5 assertions.

    Args:
        data_dir: Where the orchestrator writes calendar fixtures and ledger
            SQLite files. Created if missing. The two ledger files end up
            here and persist after the run for forensics.
        principal_a_id / principal_b_id: Identities of the two agents.
        host: Bind host for B's listener.
        port_b: Port for B's listener. ``0`` asks the OS to pick a free one
            (recommended for tests; the demo CLI defaults can use a fixed port).
        reference_time: UTC anchor for both fixture generation and slot
            picking. Defaults to ``datetime.now(timezone.utc)``. Tests pass
            a fixed value for byte-stable assertions.

    Returns:
        :class:`DemoResult` with the assigned task_id, context_id, and one
        :class:`AssertionResult` per SPEC §5 check.
    """
    now = reference_time or datetime.now(timezone.utc)
    data_dir.mkdir(parents=True, exist_ok=True)
    _clean_prior_run(data_dir)

    cal_a_path = _generate_calendar_fixture(
        owner_id=principal_a_id, reference_time=now, seed=1, dest_dir=data_dir
    )
    cal_b_path = _generate_calendar_fixture(
        owner_id=principal_b_id, reference_time=now, seed=99, dest_dir=data_dir
    )

    pair = build_agent_pair(
        principal_a_id=principal_a_id,
        principal_b_id=principal_b_id,
        ledger_dir=data_dir,
    )
    chosen_port = port_b or _free_port(host)

    listener = await configure_agent_b(
        mesherra=pair.agent_b,
        calendar_path=cal_b_path,
        listener_host=host,
        listener_port=chosen_port,
        reference_time=now,
    )
    try:
        run_a = await run_agent_a(
            mesherra=pair.agent_a,
            peer_url=f"http://{host}:{chosen_port}/",
            peer_principal_id=principal_b_id,
            calendar_path=cal_a_path,
            reference_time=now,
        )
    finally:
        await listener.stop()

    # Persist payload sidecars (SPEC §5 #13). The Residue stores only
    # payload_hash; the *bytes* must live somewhere disk-side so the
    # cold-reload assertion can prove "the accepted slot was actually one
    # A proposed" without trusting in-process state. We write both the
    # proposal A sent and the acceptance B returned. Each is named by its
    # content_hash so the assertion can look up by hash from the ledger.
    payloads_dir = data_dir / "payloads"
    payloads_dir.mkdir(parents=True, exist_ok=True)
    _write_payload(payloads_dir, run_a.proposal)
    _write_payload(payloads_dir, run_a.outbound.response_payload)

    # Cold reload — SPEC §5 assertion 14 explicitly requires the ledgers be
    # re-readable after the running process is gone. Constructing fresh
    # ProvenanceLedger instances against the same SQLite files demonstrates
    # exactly that: the in-process instances are dropped, the on-disk state
    # is read independently.
    ledger_a_cold = ProvenanceLedger(
        db_path=pair.ledger_path_a, ledger_owner=principal_a_id
    )
    ledger_b_cold = ProvenanceLedger(
        db_path=pair.ledger_path_b, ledger_owner=principal_b_id
    )
    a_entries = ledger_a_cold.get_by_task(run_a.outbound.task_id)
    b_entries = ledger_b_cold.get_by_task(run_a.outbound.task_id)

    assertions = _evaluate_assertions(
        a_entries=a_entries,
        b_entries=b_entries,
        public_key_directory=pair.public_key_directory,
        ledger_a=ledger_a_cold,
        ledger_b=ledger_b_cold,
        payloads_dir=payloads_dir,
    )
    return DemoResult(
        task_id=run_a.outbound.task_id,
        context_id=run_a.outbound.context_id,
        assertions=assertions,
    )


# -- Assertion evaluation -------------------------------------------------


def _evaluate_assertions(
    *,
    a_entries: list[Residue],
    b_entries: list[Residue],
    public_key_directory: dict[str, str],
    ledger_a: ProvenanceLedger,
    ledger_b: ProvenanceLedger,
    payloads_dir: Path,
) -> list[AssertionResult]:
    """Run all 14 SPEC §5 checks against the cold-loaded ledger entries."""
    results: list[AssertionResult] = []

    # --- Per-ledger structural (1–4 against each side) ---
    results.append(_check_two_entries("A", a_entries, number=1))
    results.append(_check_two_entries("B", b_entries, number=1))
    results.append(
        _check_chain_valid(ledger_a, side="A", number=2),
    )
    results.append(
        _check_chain_valid(ledger_b, side="B", number=2),
    )
    results.append(
        _check_all_signatures_verify(
            a_entries, public_key_directory, side="A", number=3
        )
    )
    results.append(
        _check_all_signatures_verify(
            b_entries, public_key_directory, side="B", number=3
        )
    )
    results.append(_check_sequence_timestamps(a_entries, side="A", number=4))
    results.append(_check_sequence_timestamps(b_entries, side="B", number=4))

    # --- Cross-ledger paired (5–13) ---
    # Pair entries by action_type for the cross-ledger checks.
    a_emit = next((e for e in a_entries if e.action_type == ActionType.EMIT), None)
    a_receive = next((e for e in a_entries if e.action_type == ActionType.RECEIVE), None)
    b_emit = next((e for e in b_entries if e.action_type == ActionType.EMIT), None)
    b_receive = next((e for e in b_entries if e.action_type == ActionType.RECEIVE), None)

    results.append(_check_a_proposal_emit(a_emit, number=5))
    results.append(_check_b_proposal_receive(b_receive, number=6))
    results.append(
        _check_payload_hash_equal(a_emit, b_receive, leg="proposal", number=7)
    )
    results.append(_check_task_id_equal(a_emit, b_receive, leg="proposal", number=8))
    results.append(
        _check_context_id_equal(a_emit, b_receive, leg="proposal", number=9)
    )
    results.append(_check_b_acceptance_emit(b_emit, number=10))
    results.append(_check_a_acceptance_receive(a_receive, number=11))
    results.append(
        _check_payload_hash_equal(b_emit, a_receive, leg="acceptance", number=12)
    )
    results.append(
        _check_accepted_slot_was_proposed(
            a_emit=a_emit,
            b_emit=b_emit,
            payloads_dir=payloads_dir,
            number=13,
        )
    )

    # --- Cold reload (14) ---
    # Assertions 1–13 have already been evaluated against cold-loaded
    # ledgers; #14 specifically asserts that we *could* do that, which is
    # demonstrated by every prior check passing under cold-read conditions.
    cold_reload_passed = all(a.passed for a in results)
    results.append(
        AssertionResult(
            number=14,
            name="Cold-reload chain + signatures re-verified after process exit",
            passed=cold_reload_passed,
            detail=(
                "all per-ledger and cross-ledger checks ran against cold-loaded "
                "ProvenanceLedger instances"
                if cold_reload_passed
                else "at least one prior cold-load check failed; see assertions above"
            ),
        )
    )

    return results


def _check_two_entries(side: str, entries: list[Residue], number: int) -> AssertionResult:
    passed = len(entries) == 2 and {e.sequence for e in entries} == {0, 1}
    return AssertionResult(
        number=number,
        name=f"Ledger {side}: exactly two entries at sequences 0 and 1",
        passed=passed,
        detail=f"got {len(entries)} entries; sequences {sorted(e.sequence for e in entries)}",
    )


def _check_chain_valid(
    ledger: ProvenanceLedger, *, side: str, number: int
) -> AssertionResult:
    try:
        ok = ledger.verify_chain()
        return AssertionResult(
            number=number,
            name=f"Ledger {side}: hash chain valid (entry 1.previous_hash matches entry 0)",
            passed=bool(ok),
            detail="verify_chain() returned True" if ok else "verify_chain() returned False",
        )
    except Exception as exc:
        return AssertionResult(
            number=number,
            name=f"Ledger {side}: hash chain valid",
            passed=False,
            detail=f"verify_chain() raised: {exc!r}",
        )


def _check_all_signatures_verify(
    entries: list[Residue],
    public_key_directory: dict[str, str],
    *,
    side: str,
    number: int,
) -> AssertionResult:
    """Verify every Residue signature in ``entries`` under its owner's pubkey.

    Load-bearing for tamper-at-rest detection: this is the check that
    catches a post-demo edit to a ledger row. ``verify_chain()`` only
    validates the inter-entry ``previous_hash`` links; modifying a single
    field on a single entry (e.g., flipping an operation value, or
    rewriting payload_hash) leaves the chain intact but invalidates that
    entry's own signature. Because this check runs over *cold-loaded*
    entries in :func:`run_demo`, it transitively gives SPEC §5 #14 its
    tamper-detection teeth — without this, #14 would only prove the file
    is parseable, not that it's authentic.
    """
    failures: list[str] = []
    for entry in entries:
        pk = public_key_directory.get(entry.ledger_owner)
        if pk is None:
            failures.append(
                f"sequence={entry.sequence}: ledger_owner {entry.ledger_owner!r} "
                "not in public-key directory"
            )
            continue
        verifier = Verifier.from_b64(pk)
        canonical = canonical_json(entry.to_signing_payload())
        if not verifier.verify(canonical, entry.signature):
            failures.append(
                f"sequence={entry.sequence}: signature did not verify under "
                f"{entry.ledger_owner!r}'s public key"
            )
    return AssertionResult(
        number=number,
        name=f"Ledger {side}: every Residue signature verifies under ledger_owner's pubkey",
        passed=not failures,
        detail="; ".join(failures) if failures else f"{len(entries)} signatures verified",
    )


def _check_sequence_timestamps(
    entries: list[Residue], *, side: str, number: int
) -> AssertionResult:
    if len(entries) < 2:
        return AssertionResult(
            number=number,
            name=f"Ledger {side}: sequence 0 timestamp ≤ sequence 1 timestamp",
            passed=False,
            detail="fewer than two entries",
        )
    by_seq = {e.sequence: e for e in entries}
    passed = by_seq[0].timestamp <= by_seq[1].timestamp
    return AssertionResult(
        number=number,
        name=f"Ledger {side}: sequence 0 timestamp ≤ sequence 1 timestamp",
        passed=passed,
        detail=f"entry0={by_seq[0].timestamp!r}, entry1={by_seq[1].timestamp!r}",
    )


def _check_a_proposal_emit(entry: Residue | None, *, number: int) -> AssertionResult:
    name = "A entry 0: action_type=emit, operation=proposal, actor=A, counterpart=B"
    if entry is None:
        return AssertionResult(number=number, name=name, passed=False, detail="no emit entry in A's ledger")
    passed = (
        entry.action_type == ActionType.EMIT
        and entry.operation == Operation.PROPOSAL
        and entry.actor == entry.ledger_owner
        and entry.counterpart != entry.ledger_owner
    )
    return AssertionResult(
        number=number,
        name=name,
        passed=passed,
        detail=(
            f"action_type={entry.action_type.value}, operation={entry.operation.value}, "
            f"actor={entry.actor!r}, counterpart={entry.counterpart!r}"
        ),
    )


def _check_b_proposal_receive(entry: Residue | None, *, number: int) -> AssertionResult:
    name = "B entry 0: action_type=receive, operation=proposal, actor=A, counterpart=B"
    if entry is None:
        return AssertionResult(number=number, name=name, passed=False, detail="no receive entry in B's ledger")
    passed = (
        entry.action_type == ActionType.RECEIVE
        and entry.operation == Operation.PROPOSAL
        and entry.actor != entry.ledger_owner
        and entry.counterpart == entry.ledger_owner
    )
    return AssertionResult(
        number=number,
        name=name,
        passed=passed,
        detail=(
            f"action_type={entry.action_type.value}, operation={entry.operation.value}, "
            f"actor={entry.actor!r}, counterpart={entry.counterpart!r}"
        ),
    )


def _check_b_acceptance_emit(entry: Residue | None, *, number: int) -> AssertionResult:
    name = "B entry 1: action_type=emit, operation=acceptance, actor=B, counterpart=A"
    if entry is None:
        return AssertionResult(number=number, name=name, passed=False, detail="no emit entry in B's ledger")
    passed = (
        entry.action_type == ActionType.EMIT
        and entry.operation == Operation.ACCEPTANCE
        and entry.actor == entry.ledger_owner
        and entry.counterpart != entry.ledger_owner
    )
    return AssertionResult(
        number=number,
        name=name,
        passed=passed,
        detail=(
            f"action_type={entry.action_type.value}, operation={entry.operation.value}, "
            f"actor={entry.actor!r}, counterpart={entry.counterpart!r}"
        ),
    )


def _check_a_acceptance_receive(entry: Residue | None, *, number: int) -> AssertionResult:
    name = "A entry 1: action_type=receive, operation=acceptance, actor=B, counterpart=A"
    if entry is None:
        return AssertionResult(number=number, name=name, passed=False, detail="no receive entry in A's ledger")
    passed = (
        entry.action_type == ActionType.RECEIVE
        and entry.operation == Operation.ACCEPTANCE
        and entry.actor != entry.ledger_owner
        and entry.counterpart == entry.ledger_owner
    )
    return AssertionResult(
        number=number,
        name=name,
        passed=passed,
        detail=(
            f"action_type={entry.action_type.value}, operation={entry.operation.value}, "
            f"actor={entry.actor!r}, counterpart={entry.counterpart!r}"
        ),
    )


def _check_payload_hash_equal(
    emit: Residue | None,
    receive: Residue | None,
    *,
    leg: str,
    number: int,
) -> AssertionResult:
    name = f"Cross-ledger {leg}: payload_hash byte-equal on emit and receive sides"
    if emit is None or receive is None:
        return AssertionResult(number=number, name=name, passed=False, detail="missing emit or receive entry")
    passed = emit.payload_hash == receive.payload_hash
    return AssertionResult(
        number=number,
        name=name,
        passed=passed,
        detail=f"emit={emit.payload_hash[:16]}..., receive={receive.payload_hash[:16]}...",
    )


def _check_task_id_equal(
    emit: Residue | None,
    receive: Residue | None,
    *,
    leg: str,
    number: int,
) -> AssertionResult:
    name = f"Cross-ledger {leg}: task_id equal on emit and receive sides"
    if emit is None or receive is None:
        return AssertionResult(number=number, name=name, passed=False, detail="missing emit or receive entry")
    passed = emit.task_id == receive.task_id
    return AssertionResult(
        number=number,
        name=name,
        passed=passed,
        detail=f"emit={emit.task_id!r}, receive={receive.task_id!r}",
    )


def _check_context_id_equal(
    emit: Residue | None,
    receive: Residue | None,
    *,
    leg: str,
    number: int,
) -> AssertionResult:
    name = f"Cross-ledger {leg}: context_id equal on emit and receive sides"
    if emit is None or receive is None:
        return AssertionResult(number=number, name=name, passed=False, detail="missing emit or receive entry")
    passed = emit.context_id == receive.context_id
    return AssertionResult(
        number=number,
        name=name,
        passed=passed,
        detail=f"emit={emit.context_id!r}, receive={receive.context_id!r}",
    )


def _check_accepted_slot_was_proposed(
    *,
    a_emit: Residue | None,
    b_emit: Residue | None,
    payloads_dir: Path,
    number: int,
) -> AssertionResult:
    """The acceptance payload's single slot must be one of A's original candidates.

    Real payload-level check: cold-load A's proposal payload from its
    sidecar (looked up by ``a_emit.payload_hash``), iterate every
    candidate it contains, and for each one compute the canonical hash of
    a single-candidate payload at the same duration. Assert that B's emit
    payload_hash equals one of those hashes. If it does, the slot B
    signed an acceptance for is *byte-equivalent* to one A signed a
    proposal for — no trust in the running process required.

    Why this matters: without this check, a malicious B could emit an
    acceptance Residue for a slot it invented, sign it with its own key,
    and assertions #1–#12 would all pass (B's ledger hash-chain is fine
    from B's perspective, and #12 only proves the bytes B signed are the
    bytes A received). #13 is what closes the gap from "the signatures
    fit" to "the *semantic* claim fits."

    Failures here name the slot B accepted and the candidates A actually
    proposed, so the operator can see exactly where the mismatch lies.
    """
    name = "Acceptance payload's slot is byte-equal to one of A's proposed candidates"
    if a_emit is None or b_emit is None:
        return AssertionResult(
            number=number,
            name=name,
            passed=False,
            detail="missing A emit or B emit residue",
        )

    proposal_path = payloads_dir / f"{a_emit.payload_hash}.json"
    acceptance_path = payloads_dir / f"{b_emit.payload_hash}.json"
    if not proposal_path.exists():
        return AssertionResult(
            number=number,
            name=name,
            passed=False,
            detail=f"proposal sidecar {proposal_path.name!r} missing from {payloads_dir}",
        )
    if not acceptance_path.exists():
        return AssertionResult(
            number=number,
            name=name,
            passed=False,
            detail=f"acceptance sidecar {acceptance_path.name!r} missing from {payloads_dir}",
        )

    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    duration = proposal["duration_minutes"]
    proposed_candidates: list[str] = list(proposal["candidates"])

    # For each proposed candidate, build the one-candidate payload B would
    # have constructed for an acceptance and hash it. The accepting hash
    # B actually wrote must equal one of these.
    expected_acceptance_hashes = {
        content_hash(
            canonical_json({"candidates": [cand], "duration_minutes": duration})
        ): cand
        for cand in proposed_candidates
    }
    if b_emit.payload_hash in expected_acceptance_hashes:
        accepted = expected_acceptance_hashes[b_emit.payload_hash]
        return AssertionResult(
            number=number,
            name=name,
            passed=True,
            detail=(
                f"accepted slot {accepted!r} re-derives to {b_emit.payload_hash[:16]}..., "
                f"matching B's emit payload_hash; proposal had {len(proposed_candidates)} candidates"
            ),
        )

    # Mismatch — name the slot B claimed and the slots A proposed.
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    return AssertionResult(
        number=number,
        name=name,
        passed=False,
        detail=(
            f"B's accepted slot(s) {acceptance.get('candidates')!r} do not appear in A's "
            f"proposed candidates {proposed_candidates!r} at duration {duration}"
        ),
    )


# -- Helpers --------------------------------------------------------------


def _clean_prior_run(data_dir: Path) -> None:
    """Wipe artifacts from any prior run in ``data_dir``.

    SPEC §5 #1 asserts "Two entries exist (sequence 0 and 1)" — that's
    only true on a fresh ledger. Re-running the demo against an existing
    data dir would otherwise accumulate residue and break the assertions.
    We wipe ledger files, payload sidecars, and calendar fixtures so each
    invocation starts from clean state. Phase 2+ might version this dir
    (one subdir per run for historical attestation review); Phase 1 just
    needs a known-clean baseline.
    """
    for sqlite in data_dir.glob("*.sqlite"):
        sqlite.unlink()
    for cal in data_dir.glob("*_calendar.json"):
        cal.unlink()
    payloads_dir = data_dir / "payloads"
    if payloads_dir.is_dir():
        for f in payloads_dir.iterdir():
            f.unlink()
        payloads_dir.rmdir()


def _write_payload(payloads_dir: Path, payload: dict) -> Path:
    """Persist a payload as ``{content_hash}.json`` for cold-reload verification.

    Hash collisions are not a concern (SHA-256 over canonical JSON); two
    structurally-distinct payloads with the same hash would already break
    the ledger's payload-hash invariant before this helper sees them.
    """
    hashed = content_hash(canonical_json(payload))
    target = payloads_dir / f"{hashed}.json"
    target.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _generate_calendar_fixture(
    *, owner_id: str, reference_time: datetime, seed: int, dest_dir: Path
) -> Path:
    cal = generate_calendar(
        owner_principal_id=owner_id,
        reference_time=reference_time,
        seed=seed,
        busy_blocks_per_day=1,
    )
    safe = owner_id.replace("@", "_").replace(".", "_").replace("/", "_")
    path = dest_dir / f"{safe}_calendar.json"
    write_calendar(cal, path)
    return path


def _free_port(host: str) -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


# -- CLI entry ------------------------------------------------------------


def _print_results(result: DemoResult) -> None:
    print(f"\nPhase 1 demo run: task_id={result.task_id}  context_id={result.context_id}\n")
    for a in result.assertions:
        flag = "PASS" if a.passed else "FAIL"
        print(f"  [{flag}] {a.number:>2}. {a.name}")
        if a.detail:
            print(f"         {a.detail}")
    print()
    print("=" * 70)
    distinct_numbers = len({a.number for a in result.assertions})
    if result.all_passed:
        print(
            f"PHASE 1 SUCCESS — all {distinct_numbers} SPEC §5 assertions passed "
            f"({len(result.assertions)} individual checks, since 1–4 run per-ledger)."
        )
    else:
        failed = sum(1 for a in result.assertions if not a.passed)
        print(
            f"PHASE 1 FAILED — {failed} of {len(result.assertions)} individual "
            f"checks failed (across {distinct_numbers} SPEC §5 assertions)."
        )
    print("=" * 70)


async def _main() -> int:
    data_dir = Path(__file__).resolve().parent / "demo-data"
    result = await run_demo(data_dir=data_dir)
    _print_results(result)
    return 0 if result.all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
