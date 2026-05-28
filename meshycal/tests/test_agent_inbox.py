"""Tests for SchedulingAgentInbox — the M1 adapter that turns a real
SchedulingAgent's substrate (MeetingObjects in the object store +
entries in the ProvenanceLedger) into the renderer-facing MeetingCard /
MeetingDetail shapes the api emits.

These tests run against a real agent. They do NOT exercise the full
two-party negotiation (that's covered by
test_meeting_object_roundtrip.py). Here we manually seed the agent's
substrate with a MeetingObject and assert the adapter reads it
correctly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mesherra.crypto.primitives import Signer
from mesherra.identity import StaticDirectoryClient
from mesherra.models.primitives import LayerKind, Mutability
from mesherra.object.store import ObjectStore
from mesherra.policy import PolicyStore, sign_policy_doc
from mesherra.provenance.ledger import ProvenanceLedger

from meshycal import (
    CalendarObject,
    ScriptedReasoner,
    SchedulingAgent,
    build_policy_doc,
)
from meshycal.api.agent_inbox import SchedulingAgentInbox
from meshycal.api.models import MeetingStatus
from meshycal.meeting_object import MEETING_OBJECT_SCHEMA, MeetingObjectState

ALICE = "alice@sandbox.local"
BOB = "bob@sandbox.local"


def _build_agent(td: Path, principal_id: str) -> SchedulingAgent:
    signer = Signer.generate()
    directory = StaticDirectoryClient({principal_id: signer.public_key_b64()})
    calendar = CalendarObject(owner_principal_id=principal_id, events=[])
    policy = PolicyStore(
        db_path=td / f"{principal_id}_policy.sqlite",
        principal_id=principal_id,
        public_key_b64=signer.public_key_b64(),
    )
    policy.save_signed(
        sign_policy_doc(
            doc=build_policy_doc(principal_id=principal_id), signer=signer,
        )
    )
    ledger = ProvenanceLedger(
        db_path=td / f"{principal_id}_ledger.sqlite",
        ledger_owner=principal_id,
    )
    objects = ObjectStore(
        db_path=td / f"{principal_id}_objects.sqlite",
        owner_principal_id=principal_id,
    )
    return SchedulingAgent(
        calendar=calendar,
        signer=signer,
        policy_store=policy,
        ledger=ledger,
        object_store=objects,
        directory=directory,
        reasoner=ScriptedReasoner(),
        display_name=principal_id.split("@")[0].capitalize(),
        single_process_mode=True,
    )


def _seed_accepted_meeting(
    agent: SchedulingAgent,
    *,
    peer_principal_id: str,
    time: str = "2026-06-01T13:00:00Z",
    duration_minutes: int = 30,
    title: str | None = None,
) -> str:
    """Create a real MeetingObject in the agent's substrate, return its id."""
    state = MeetingObjectState(
        time=time,
        duration_minutes=duration_minutes,
        timezone="UTC",
        title=title or f"meeting with {peer_principal_id}",
        location=None,
        attendees=[agent.principal_id, peer_principal_id],
        agreement_hash="a" * 64,  # synthetic but matches the 64-hex constraint
        provenance_pointer=None,
    )
    obj = agent._sdk.create_object(
        state=state.model_dump(),
        home_layer=LayerKind.PERSONAL,
        mutability=Mutability.LIVE,
        schema_ref=MEETING_OBJECT_SCHEMA,
    )
    return obj.object_id


def test_empty_agent_yields_empty_inbox():
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        agent = _build_agent(td, ALICE)
        try:
            inbox = SchedulingAgentInbox(agent)
            assert inbox.list_cards() == []
        finally:
            agent.close()


def test_seeded_meeting_appears_as_accepted_card():
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        agent = _build_agent(td, ALICE)
        try:
            _seed_accepted_meeting(agent, peer_principal_id=BOB)
            inbox = SchedulingAgentInbox(agent)
            cards = inbox.list_cards()
            assert len(cards) == 1
            card = cards[0]
            assert card.status is MeetingStatus.ACCEPTED
            assert card.counterparty_principal_id == BOB
            assert card.proposed_time == "2026-06-01T13:00:00Z"
            assert card.duration_minutes == 30
            assert "bob" in card.title.lower()
        finally:
            agent.close()


def test_find_detail_returns_full_meeting_object_state():
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        agent = _build_agent(td, ALICE)
        try:
            meeting_id = _seed_accepted_meeting(agent, peer_principal_id=BOB)
            inbox = SchedulingAgentInbox(agent)
            detail = inbox.find_detail(meeting_id)
            assert detail is not None
            assert detail.id == meeting_id
            assert detail.status is MeetingStatus.ACCEPTED
            assert detail.agreement_hash is not None
            assert len(detail.agreement_hash) == 64
            assert all(c in "0123456789abcdef" for c in detail.agreement_hash)
        finally:
            agent.close()


def test_find_detail_unknown_id_returns_none():
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        agent = _build_agent(td, ALICE)
        try:
            inbox = SchedulingAgentInbox(agent)
            assert inbox.find_detail("does-not-exist") is None
        finally:
            agent.close()


def test_counterparty_name_humanized_from_principal_id():
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        agent = _build_agent(td, ALICE)
        try:
            _seed_accepted_meeting(agent, peer_principal_id="bob@sandbox.local")
            inbox = SchedulingAgentInbox(agent)
            card = inbox.list_cards()[0]
            # "bob@sandbox.local" → "Bob" — local-part, capitalized.
            assert card.counterparty_name == "Bob"
        finally:
            agent.close()


def test_two_meetings_both_appear():
    """Multiple accepted meetings → multiple cards."""
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        agent = _build_agent(td, ALICE)
        try:
            _seed_accepted_meeting(
                agent,
                peer_principal_id=BOB,
                time="2026-06-01T13:00:00Z",
                title="meeting with bob",
            )
            _seed_accepted_meeting(
                agent,
                peer_principal_id="sara@sandbox.local",
                time="2026-06-02T14:00:00Z",
                title="meeting with sara",
            )
            inbox = SchedulingAgentInbox(agent)
            cards = inbox.list_cards()
            assert len(cards) == 2
            counterparties = {c.counterparty_principal_id for c in cards}
            assert counterparties == {BOB, "sara@sandbox.local"}
        finally:
            agent.close()
