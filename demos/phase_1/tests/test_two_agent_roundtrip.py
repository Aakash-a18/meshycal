"""Integration tests for the two-agent Phase 1 negotiation.

Exercises Agent A and Agent B over real localhost A2A:

* Acceptance path: A proposes; B is free for the first candidate; B accepts.
* Counter path: A proposes; B is busy for every candidate; B counter-proposes
  from its own calendar.
* Rejection path: Both A and B are fully booked; B returns REJECTION rather
  than silently dropping.

The trust-layer plumbing (SendClaim signing/verification, Residue chain
writes) is exercised end-to-end because both agents go through the real
Mesherra SDK, the real A2A adapter, and a real TCP localhost connection.
"""

from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_a import PAYLOAD_SCHEMA, run_agent_a
from agent_b import configure_agent_b
from mesherra.models.primitives import ActionType, Operation
from synthetic_calendar import generate_calendar, write_calendar
from wiring import build_agent_pair

_A_ID = "user-a@phase1.local"
_B_ID = "user-b@phase1.local"
_HOST = "127.0.0.1"
# Fixed reference time so the slot picker produces the same candidates each
# run regardless of when the test executes. A Monday at 08:00 UTC.
_REF = datetime(2026, 5, 25, 8, 0, tzinfo=timezone.utc)


def _free_port() -> int:
    """Ask the OS for an unused port (bind 0, read back the assigned port)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_HOST, 0))
        return int(s.getsockname()[1])


def _write_calendar_for(
    *, owner_id: str, seed: int, busy_blocks_per_day: int, dest_dir: Path
) -> Path:
    cal = generate_calendar(
        owner_principal_id=owner_id,
        reference_time=_REF,
        seed=seed,
        busy_blocks_per_day=busy_blocks_per_day,
    )
    path = dest_dir / f"{owner_id.replace('@', '_').replace('.', '_')}_calendar.json"
    write_calendar(cal, path)
    return path


def _write_fully_busy_calendar(*, owner_id: str, dest_dir: Path) -> Path:
    """Block every working hour for the next 14 days — forces REJECTION path."""
    busy = []
    for offset in range(14):
        day = _REF.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset)
        if day.weekday() < 5:
            busy.append(
                {
                    "start_utc": day.replace(hour=9).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end_utc": day.replace(hour=17).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
    cal = {
        "owner_principal_id": owner_id,
        "reference_time": _REF.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "busy": busy,
    }
    path = dest_dir / f"{owner_id.replace('@', '_').replace('.', '_')}_calendar.json"
    write_calendar(cal, path)
    return path


class TestAcceptancePath:
    async def test_b_accepts_first_free_candidate(self, tmp_path: Path) -> None:
        # Different seeds → different busy patterns → at least one of A's
        # three candidates falls in B's free time.
        cal_a = _write_calendar_for(
            owner_id=_A_ID, seed=1, busy_blocks_per_day=1, dest_dir=tmp_path
        )
        cal_b = _write_calendar_for(
            owner_id=_B_ID, seed=99, busy_blocks_per_day=1, dest_dir=tmp_path
        )
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )

        port_b = _free_port()
        listener = await configure_agent_b(
            mesherra=pair.agent_b,
            calendar_path=cal_b,
            listener_host=_HOST,
            listener_port=port_b,
            reference_time=_REF,
        )
        try:
            result = await run_agent_a(
                mesherra=pair.agent_a,
                peer_url=f"http://{_HOST}:{port_b}/",
                peer_principal_id=_B_ID,
                calendar_path=cal_a,
                reference_time=_REF,
            )
        finally:
            await listener.stop()

        outbound = result.outbound
        assert outbound.response_operation == Operation.ACCEPTANCE
        assert outbound.response_sender_principal_id == _B_ID
        assert len(outbound.response_payload["candidates"]) == 1
        assert outbound.response_payload["duration_minutes"] == 30
        # A2A assigned a task_id during the roundtrip.
        assert outbound.task_id != ""
        # The proposal A built is surfaced for the orchestrator's payload
        # sidecar (needed for SPEC §5 #13's payload-derivation check).
        assert "candidates" in result.proposal
        assert len(result.proposal["candidates"]) == 3

    async def test_both_ledgers_record_paired_residues(self, tmp_path: Path) -> None:
        cal_a = _write_calendar_for(
            owner_id=_A_ID, seed=1, busy_blocks_per_day=1, dest_dir=tmp_path
        )
        cal_b = _write_calendar_for(
            owner_id=_B_ID, seed=99, busy_blocks_per_day=1, dest_dir=tmp_path
        )
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )

        port_b = _free_port()
        listener = await configure_agent_b(
            mesherra=pair.agent_b,
            calendar_path=cal_b,
            listener_host=_HOST,
            listener_port=port_b,
            reference_time=_REF,
        )
        try:
            result = await run_agent_a(
                mesherra=pair.agent_a,
                peer_url=f"http://{_HOST}:{port_b}/",
                peer_principal_id=_B_ID,
                calendar_path=cal_a,
                reference_time=_REF,
            )
        finally:
            await listener.stop()

        a_entries = pair.agent_a.get_residue(result.outbound.task_id)
        b_entries = pair.agent_b.get_residue(result.outbound.task_id)
        assert len(a_entries) == 2, "A writes one emit + one receive"
        assert len(b_entries) == 2, "B writes one receive + one emit"

        # Pair them by action_type and payload_hash for the cross-ledger check.
        a_emit = next(e for e in a_entries if e.action_type == ActionType.EMIT)
        b_receive = next(e for e in b_entries if e.action_type == ActionType.RECEIVE)
        a_receive = next(e for e in a_entries if e.action_type == ActionType.RECEIVE)
        b_emit = next(e for e in b_entries if e.action_type == ActionType.EMIT)

        # Cross-ledger linkage: A's emit must pair with B's receive on the
        # same payload_hash, task_id, context_id, payload_schema.
        assert a_emit.payload_hash == b_receive.payload_hash
        assert a_emit.task_id == b_receive.task_id
        assert a_emit.context_id == b_receive.context_id
        assert a_emit.payload_schema == b_receive.payload_schema
        assert a_emit.operation == Operation.PROPOSAL
        assert b_receive.operation == Operation.PROPOSAL

        # B's acceptance: B's emit pairs with A's receive.
        assert b_emit.payload_hash == a_receive.payload_hash
        assert b_emit.task_id == a_receive.task_id
        assert b_emit.context_id == a_receive.context_id
        assert b_emit.operation == Operation.ACCEPTANCE
        assert a_receive.operation == Operation.ACCEPTANCE


class TestCounterPath:
    async def test_b_counters_when_all_candidates_conflict(self, tmp_path: Path) -> None:
        # Seed B's calendar to conflict with every workday slot A would
        # propose. Easiest: block 09:00–11:00 every day, which catches A's
        # 09:00 / 09:30 / 10:00 / 10:30 candidates (A is free at those
        # times, so it proposes them; B is busy then).
        cal_a = _write_calendar_for(
            owner_id=_A_ID, seed=1, busy_blocks_per_day=0, dest_dir=tmp_path
        )
        # Build B's busy as 09:00–17:00 every weekday EXCEPT 16:00–16:30
        # which we leave free — that gives B a counter candidate.
        busy = []
        for offset in range(7):
            day = _REF.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset)
            if day.weekday() < 5:
                busy.append(
                    {
                        "start_utc": day.replace(hour=9).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "end_utc": day.replace(hour=16).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                )
                busy.append(
                    {
                        "start_utc": day.replace(hour=16, minute=30).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "end_utc": day.replace(hour=17).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                )
        b_cal = {
            "owner_principal_id": _B_ID,
            "reference_time": _REF.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "busy": busy,
        }
        cal_b = tmp_path / "b_calendar.json"
        write_calendar(b_cal, cal_b)

        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )

        port_b = _free_port()
        listener = await configure_agent_b(
            mesherra=pair.agent_b,
            calendar_path=cal_b,
            listener_host=_HOST,
            listener_port=port_b,
            reference_time=_REF,
        )
        try:
            result = await run_agent_a(
                mesherra=pair.agent_a,
                peer_url=f"http://{_HOST}:{port_b}/",
                peer_principal_id=_B_ID,
                calendar_path=cal_a,
                reference_time=_REF,
            )
        finally:
            await listener.stop()

        assert result.outbound.response_operation == Operation.COUNTER
        # B's counter should include at least one 16:00 slot from its
        # narrow free window.
        counter_slots = result.outbound.response_payload["candidates"]
        assert any(slot.endswith("T16:00:00Z") for slot in counter_slots), (
            f"expected B's counter to include a 16:00 slot; got {counter_slots}"
        )


class TestRejectionPath:
    async def test_b_rejects_when_both_calendars_fully_busy(self, tmp_path: Path) -> None:
        # A has a free slot to propose (otherwise A errors before sending),
        # so we make A free and B fully booked.
        cal_a = _write_calendar_for(
            owner_id=_A_ID, seed=1, busy_blocks_per_day=0, dest_dir=tmp_path
        )
        cal_b = _write_fully_busy_calendar(owner_id=_B_ID, dest_dir=tmp_path)

        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )

        port_b = _free_port()
        listener = await configure_agent_b(
            mesherra=pair.agent_b,
            calendar_path=cal_b,
            listener_host=_HOST,
            listener_port=port_b,
            reference_time=_REF,
        )
        try:
            result = await run_agent_a(
                mesherra=pair.agent_a,
                peer_url=f"http://{_HOST}:{port_b}/",
                peer_principal_id=_B_ID,
                calendar_path=cal_a,
                reference_time=_REF,
            )
        finally:
            await listener.stop()

        assert result.outbound.response_operation == Operation.REJECTION


class TestAgentACalendarErrors:
    async def test_raises_when_a_has_no_free_slots(self, tmp_path: Path) -> None:
        """SPEC §6 says A's pipeline terminates if no free slot exists in
        the 7-day window. The agent must surface that with a ValueError so
        the orchestrator can report it rather than sending an empty proposal."""
        cal_a = _write_fully_busy_calendar(owner_id=_A_ID, dest_dir=tmp_path)
        cal_b = _write_calendar_for(
            owner_id=_B_ID, seed=99, busy_blocks_per_day=1, dest_dir=tmp_path
        )
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )

        port_b = _free_port()
        listener = await configure_agent_b(
            mesherra=pair.agent_b,
            calendar_path=cal_b,
            listener_host=_HOST,
            listener_port=port_b,
            reference_time=_REF,
        )
        try:
            with pytest.raises(ValueError, match="could not find any free"):
                await run_agent_a(
                    mesherra=pair.agent_a,
                    peer_url=f"http://{_HOST}:{port_b}/",
                    peer_principal_id=_B_ID,
                    calendar_path=cal_a,
                    reference_time=_REF,
                )
        finally:
            await listener.stop()


def test_schema_id_constant_matches_schema_file() -> None:
    """Synchronization check: the PAYLOAD_SCHEMA constant the agents send
    must match the $id in the schema file the validator loads."""
    import json

    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "proposal_v1.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"] == PAYLOAD_SCHEMA
