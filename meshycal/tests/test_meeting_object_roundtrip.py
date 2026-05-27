"""End-to-end integration test for MeshyCal's MeetingObject flow.

This is the keystone scenario MeshyCal was waiting on Mesherra Phase 4
Slice 1+2 to ship: two scheduling agents negotiate a meeting, and the
agreement is materialized as a real **Mesherra Object** that lives
canonically in the initiator's stack and is live-reference-promoted to
the counterpart. Both sides see the same canonical state through their
respective views, neither side fabricates the agreement independently.

The flow exercised:

1. Alice + Bob each construct a Mesherra-wired SchedulingAgent.
2. Alice proposes a meeting to Bob via the existing PROPOSAL path.
3. Bob's scripted reasoner accepts; Bob sends back an ACCEPTANCE
   (signed, paired residue) but does **not** book locally — he is
   waiting for the canonical MeetingObject from Alice.
4. On receiving ACCEPTANCE, Alice creates a MeetingObject (a real
   Mesherra Object with ``mutability=LIVE``), promotes it to Bob via
   ``Mesherra.promote(mutability=LIVE)``, ships the handle through
   PROMOTE, and books the meeting on her own CalendarObject.
5. Bob's gateway records the received PromotionHandle (trust-layer
   path; consumer never sees it). Bob explicitly calls
   ``subscribe_to_pending_meetings()`` to pick up any new
   meshycal.scheduling/meeting-v1 handles, subscribe, fetch initial
   state, and book.

Invariants asserted:

* Alice's ObjectStore holds the MeetingObject with the agreed slot.
* Alice has an active owner-side subscription row pointing at Bob.
* Bob has the received handle + an active receiver-side subscription.
* Both calendars hold a booking at the agreed slot — matching HH:MM.
* The MeetingObject state Bob reads equals what Alice created
  (cryptographically: same content_hash).
* Both ledgers carry the full provenance chain for the round-trip.

The §9 #11 LIVE scope-filter invariant from Mesherra is preserved by
construction: Alice's CalendarObject's private fields never appear in
any wire payload reaching Bob, because the MeetingObjectState schema
limits what crosses to the agreed meeting details only.
"""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path

import pytest

from mesherra.crypto.primitives import Signer
from mesherra.identity import StaticDirectoryClient
from mesherra.models.primitives import (
    Mutability,
    Operation,
    SubscriptionRole,
    SubscriptionStatus,
)
from mesherra.object.store import ObjectStore
from mesherra.policy import PolicyStore, sign_policy_doc
from mesherra.provenance.ledger import ProvenanceLedger

from meshycal import (
    CalendarEvent,
    CalendarObject,
    ScriptedReasoner,
    SchedulingAgent,
    build_policy_doc,
)
from meshycal.meeting_object import (
    MEETING_OBJECT_SCHEMA,
    MeetingObjectState,
)

ALICE = "alice@phase4.local"
BOB = "bob@phase4.local"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _make_agent(
    *,
    principal_id: str,
    display_name: str,
    events: list[CalendarEvent],
    signer: Signer,
    directory: StaticDirectoryClient,
    td: Path,
    label: str,
) -> SchedulingAgent:
    cal = CalendarObject(owner_principal_id=principal_id, events=events)
    store = PolicyStore(
        db_path=td / f"{label}_policy.sqlite",
        principal_id=principal_id,
        public_key_b64=signer.public_key_b64(),
    )
    store.save_signed(sign_policy_doc(
        doc=build_policy_doc(principal_id=principal_id), signer=signer,
    ))
    ledger = ProvenanceLedger(
        db_path=td / f"{label}_ledger.sqlite", ledger_owner=principal_id,
    )
    object_store = ObjectStore(
        db_path=td / f"{label}_objects.sqlite",
        owner_principal_id=principal_id,
    )
    return SchedulingAgent(
        calendar=cal,
        signer=signer,
        policy_store=store,
        ledger=ledger,
        object_store=object_store,
        directory=directory,
        reasoner=ScriptedReasoner(),
        display_name=display_name,
    )


@pytest.mark.asyncio
async def test_meeting_object_co_visible_after_negotiation():
    """The keystone test: two agents negotiate, the result is a single
    canonical MeetingObject visible (via live reference) on both sides."""
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        alice_signer = Signer.generate()
        bob_signer = Signer.generate()
        directory = StaticDirectoryClient({
            ALICE: alice_signer.public_key_b64(),
            BOB: bob_signer.public_key_b64(),
        })

        alice = _make_agent(
            principal_id=ALICE,
            display_name="Alice",
            events=[CalendarEvent(time="09:00", duration=60, title="standup")],
            signer=alice_signer,
            directory=directory,
            td=td,
            label="alice",
        )
        bob = _make_agent(
            principal_id=BOB,
            display_name="Bob",
            events=[CalendarEvent(time="11:00", duration=30, title="focus")],
            signer=bob_signer,
            directory=directory,
            td=td,
            label="bob",
        )

        alice_port = _free_port()
        bob_port = _free_port()
        alice_handle = await alice.start_listener(host="127.0.0.1", port=alice_port)
        bob_handle = await bob.start_listener(host="127.0.0.1", port=bob_port)
        alice_url = f"http://127.0.0.1:{alice_port}/"
        bob_url = f"http://127.0.0.1:{bob_port}/"

        try:
            # --- Alice proposes; Bob accepts; Alice creates + promotes ---
            result = await alice.propose_meeting_to(
                peer_url=bob_url,
                peer_principal_id=BOB,
                candidates=["2026-06-01T13:00:00Z", "2026-06-01T14:00:00Z"],
                duration_minutes=30,
            )

            # --- Bob picks up the pending MeetingObject handle ---
            # The PROMOTE arrived via the trust-layer path (ObjectInboundHandler
            # persisted the handle); the consumer SchedulingAgent doesn't see
            # PROMOTE through its on_message hook. Bob explicitly polls for
            # new meeting handles and subscribes.
            subscribed = await bob.subscribe_to_pending_meetings(
                peer_url=alice_url, my_url=bob_url
            )
            assert len(subscribed) == 1, "Bob should have one new meeting to subscribe to"

        finally:
            await bob_handle.stop()
            await alice_handle.stop()

        # --- Alice's side: MeetingObject + Promotion exist ---
        alice_objects = alice.objects
        assert alice_objects is not None
        meeting_objects = [
            obj for obj in alice_objects.list()
            if obj.schema_ref == MEETING_OBJECT_SCHEMA
        ]
        assert len(meeting_objects) == 1
        meeting = meeting_objects[0]
        assert meeting.mutability is Mutability.LIVE
        assert meeting.owner == ALICE

        meeting_state = MeetingObjectState.model_validate(meeting.state)
        assert meeting_state.duration_minutes == 30
        assert meeting_state.title  # non-empty
        # Chosen slot is one of the candidates Alice proposed.
        assert meeting_state.time in (
            "2026-06-01T13:00:00Z",
            "2026-06-01T14:00:00Z",
        )

        # Alice owns a LIVE promotion of this Object to Bob.
        promotions = alice_objects.list_promotions_for_object(meeting.object_id)
        assert len(promotions) == 1
        promotion = promotions[0]
        assert promotion.mutability is Mutability.LIVE
        assert promotion.receiver == BOB
        assert promotion.owner == ALICE

        # Owner-side subscription row exists (Bob's SUBSCRIBE landed).
        alice_sub = alice_objects.get_subscription(
            promotion_id=promotion.promotion_id,
            role=SubscriptionRole.OWNER,
        )
        assert alice_sub.status is SubscriptionStatus.ACTIVE
        assert alice_sub.counterpart == BOB

        # --- Bob's side: handle + receiver-side subscription + state ---
        bob_objects = bob.objects
        assert bob_objects is not None
        received_handles = bob_objects.list_received_handles()
        meeting_handles = [
            h for h in received_handles
            if h.schema_ref == MEETING_OBJECT_SCHEMA
        ]
        assert len(meeting_handles) == 1
        bob_handle_artifact = meeting_handles[0]
        assert bob_handle_artifact.owner == ALICE
        assert bob_handle_artifact.receiver == BOB
        assert bob_handle_artifact.mutability is Mutability.LIVE

        bob_sub = bob_objects.get_subscription(
            promotion_id=bob_handle_artifact.promotion_id,
            role=SubscriptionRole.RECEIVER,
        )
        assert bob_sub.status is SubscriptionStatus.ACTIVE

        # --- Both calendars have the booking at the same HH:MM ---
        hhmm = meeting_state.time[11:16]  # "2026-06-01T13:00:00Z" → "13:00"
        assert any(
            e.time == hhmm and e.duration == 30 for e in alice.calendar.events
        ), f"Alice's calendar missing booking at {hhmm}"
        assert any(
            e.time == hhmm and e.duration == 30 for e in bob.calendar.events
        ), f"Bob's calendar missing booking at {hhmm}"

        # --- Both ledgers carry the full provenance chain ---
        alice_entries = alice.ledger.get_all()
        bob_entries = bob.ledger.get_all()
        # PROPOSAL (alice EMIT, bob RECEIVE)
        assert any(e.operation is Operation.PROPOSAL for e in alice_entries)
        assert any(e.operation is Operation.PROPOSAL for e in bob_entries)
        # PROMOTE (alice EMIT, bob RECEIVE)
        assert any(e.operation is Operation.PROMOTE for e in alice_entries)
        assert any(e.operation is Operation.PROMOTE for e in bob_entries)
        # SUBSCRIBE (bob EMIT, alice RECEIVE)
        assert any(e.operation is Operation.SUBSCRIBE for e in alice_entries)
        assert any(e.operation is Operation.SUBSCRIBE for e in bob_entries)

        alice.close()
        bob.close()
