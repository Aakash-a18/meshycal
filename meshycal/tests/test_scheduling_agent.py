"""Unit tests for SchedulingAgent — Mesherra-wired, reasoner-driven, book-on-accept.

Builds two real agents wired through an in-process StaticDirectoryClient
and verifies a real signed exchange. The scripted reasoner makes these
fully deterministic.
"""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path

import pytest

from mesherra.crypto.primitives import Signer, canonical_json, content_hash
from mesherra.identity import StaticDirectoryClient
from mesherra.policy import PolicyStore, sign_policy_doc
from mesherra.provenance.ledger import ProvenanceLedger

from meshycal import (
    CalendarEvent,
    CalendarObject,
    ScriptedReasoner,
    SchedulingAgent,
    build_policy_doc,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _wire_agent(td: Path, principal_id: str, display_name: str,
                       events: list[CalendarEvent], directory: StaticDirectoryClient,
                       label: str) -> tuple[SchedulingAgent, Signer]:
    signer = Signer.generate()
    calendar = CalendarObject(owner_principal_id=principal_id, events=events)
    policy_store = PolicyStore(
        db_path=td / f"{label}_policy.sqlite",
        principal_id=principal_id,
        public_key_b64=signer.public_key_b64(),
    )
    policy_store.save_signed(sign_policy_doc(
        doc=build_policy_doc(principal_id=principal_id),
        signer=signer,
    ))
    ledger = ProvenanceLedger(
        db_path=td / f"{label}_ledger.sqlite",
        ledger_owner=principal_id,
    )
    agent = SchedulingAgent(
        calendar=calendar,
        signer=signer,
        policy_store=policy_store,
        ledger=ledger,
        directory=directory,
        reasoner=ScriptedReasoner(),
        display_name=display_name,
    )
    return agent, signer


@pytest.mark.asyncio
async def test_two_agents_real_signed_exchange():
    """The hash invariant: scoped payload_hash matches on both agents'
    ledgers after a successful proposal+accept exchange."""
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        # Build signers first so the directory has both keys.
        s_signer = Signer.generate()
        r_signer = Signer.generate()
        directory = StaticDirectoryClient({
            "iris@test.local": s_signer.public_key_b64(),
            "marius@test.local": r_signer.public_key_b64(),
        })

        def _agent(pid, name, events, signer, label):
            cal = CalendarObject(owner_principal_id=pid, events=events)
            store = PolicyStore(
                db_path=td / f"{label}_policy.sqlite",
                principal_id=pid, public_key_b64=signer.public_key_b64(),
            )
            store.save_signed(sign_policy_doc(
                doc=build_policy_doc(principal_id=pid), signer=signer))
            ledger = ProvenanceLedger(
                db_path=td / f"{label}_ledger.sqlite", ledger_owner=pid)
            return SchedulingAgent(
                calendar=cal, signer=signer, policy_store=store, ledger=ledger,
                directory=directory, reasoner=ScriptedReasoner(),
                display_name=name,
            )

        sender = _agent("iris@test.local", "Iris",
                        [CalendarEvent(time="09:00", duration=60, title="standup")],
                        s_signer, "sender")
        recipient = _agent("marius@test.local", "Marius",
                           [CalendarEvent(time="11:00", duration=30, title="focus")],
                           r_signer, "recipient")

        port = _free_port()
        handle = await recipient.start_listener(host="127.0.0.1", port=port)
        try:
            candidates = ["2026-05-26T13:00:00Z", "2026-05-26T14:00:00Z"]
            result = await sender.propose_meeting_to(
                peer_url=f"http://127.0.0.1:{port}/",
                peer_principal_id="marius@test.local",
                candidates=candidates,
                duration_minutes=30,
            )
        finally:
            await handle.stop()

        # The hash invariant — central Mesherra check.
        sender_entries = list(sender.ledger.get_by_task(result.task_id))
        recipient_entries = list(recipient.ledger.get_by_task(result.task_id))
        sender_emit = next(
            e for e in sender_entries
            if e.action_type.value == "emit" and e.operation.value == "proposal"
        )
        recipient_recv = next(
            e for e in recipient_entries
            if e.action_type.value == "receive" and e.operation.value == "proposal"
        )
        assert sender_emit.payload_hash == recipient_recv.payload_hash

        # Recipient's reasoner accepted, so they booked it.
        assert recipient.last_verdict is not None
        assert recipient.last_verdict.accept is True
        # Recipient calendar gained an event at the chosen slot's HH:MM.
        chosen = recipient.last_verdict.chosen_slot
        assert chosen is not None
        hhmm = chosen[11:16]  # "2026-05-26T13:00:00Z" → "13:00"
        assert any(e.time == hhmm for e in recipient.calendar.events)

        sender.close()
        recipient.close()


@pytest.mark.asyncio
async def test_agent_rich_payload_includes_blocked_fields():
    """The agent constructs the rich payload (including fields the
    policy will strip). The airlock — not the agent — is what removes
    them on the wire."""
    cal = CalendarObject(
        owner_principal_id="x@test.local",
        events=[
            CalendarEvent(time="09:00", duration=30, title="secret-1on1",
                          attendees="hidden@example"),
        ],
    )
    signer = Signer.generate()
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        store = PolicyStore(
            db_path=td / "p.sqlite",
            principal_id="x@test.local",
            public_key_b64=signer.public_key_b64(),
        )
        store.save_signed(sign_policy_doc(
            doc=build_policy_doc(principal_id="x@test.local"),
            signer=signer,
        ))
        ledger = ProvenanceLedger(
            db_path=td / "l.sqlite", ledger_owner="x@test.local"
        )
        directory = StaticDirectoryClient({"x@test.local": signer.public_key_b64()})
        agent = SchedulingAgent(
            calendar=cal, signer=signer, policy_store=store, ledger=ledger,
            directory=directory, reasoner=ScriptedReasoner(),
            display_name="Tester",
        )

        rich = agent.build_rich_payload(
            candidates=["2026-05-26T13:00:00Z"],
            duration_minutes=30,
        )
        assert "candidates" in rich
        assert "duration_minutes" in rich
        assert "calendar_titles" in rich
        assert "secret-1on1" in rich["calendar_titles"]
        assert "attendee_emails" in rich
        assert "hidden@example" in rich["attendee_emails"]
        agent.close()
