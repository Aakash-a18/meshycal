"""SchedulingAgentInbox — Milestone 1 inbox adapter.

Reads from a real `SchedulingAgent`'s substrate to produce
renderer-facing MeetingCards/MeetingDetails. Writes via
`SchedulingAgent.propose_meeting_to` (M1.3).

Covers both perspectives:
- OWNER (initiator): MeetingObject lives in the agent's ObjectStore.
- RECEIVER (counterpart): PromotionHandle is in the ObjectStore + a
  cached MeetingObjectState was filled by
  `subscribe_to_pending_meetings`.

Cards from both sides carry the SAME id (the canonical object_id) so
the two inboxes' detail URLs point at the same agreement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from meshycal.api.models import (
    LedgerEntry,
    MeetingCard,
    MeetingDetail,
    MeetingStatus,
    NewMeetingRequest,
)
from meshycal.meeting_object import MEETING_OBJECT_SCHEMA, MeetingObjectState
from meshycal.scheduling_agent import default_candidate_slots

if TYPE_CHECKING:
    from mesherra.models.primitives import Object, PromotionHandle, Residue

    from meshycal.api.principals import PrincipalSession
    from meshycal.scheduling_agent import SchedulingAgent


# --- helpers ----------------------------------------------------------


def _humanize_principal(principal_id: str) -> str:
    """`bob@sandbox.local` → `Bob`. Local part, capitalized."""
    local = principal_id.split("@", 1)[0]
    return " ".join(p.capitalize() for p in local.replace(".", "-").split("-"))


def _other_attendee(attendees: list[str], me: str) -> str:
    for a in attendees:
        if a != me:
            return a
    return me


def _residue_to_ledger_entry(residue: Residue, me: str) -> LedgerEntry:
    direction = residue.action_type.value  # "emit" | "receive"
    operation = residue.operation.value
    is_outbound = direction == "emit"
    actor = "you" if is_outbound else _humanize_principal(residue.counterpart)
    verb = "sent" if is_outbound else "received"
    return LedgerEntry(
        timestamp=residue.timestamp,
        actor=actor,
        operation=operation,
        action=f"{verb} {operation}",
        payload_hash_preview=residue.payload_hash[:16],
    )


def _is_meeting_object(obj: Object) -> bool:
    return obj.schema_ref == MEETING_OBJECT_SCHEMA


def _card_from_owned_object(obj: Object, me: str) -> MeetingCard:
    state = MeetingObjectState.model_validate(obj.state)
    counterparty_pid = _other_attendee(state.attendees, me)
    return MeetingCard(
        id=obj.object_id,
        status=MeetingStatus.ACCEPTED,
        counterparty_name=_humanize_principal(counterparty_pid),
        counterparty_principal_id=counterparty_pid,
        proposed_time=state.time,
        duration_minutes=state.duration_minutes,
        title=state.title,
        last_updated=obj.updated_at,
    )


def _card_from_received_handle(
    handle: PromotionHandle, state: MeetingObjectState, me: str,
) -> MeetingCard:
    # Receiver-side: the counterparty is the handle's owner. The scoped
    # MeetingObjectState's `attendees` is NOT populated for receivers
    # (it's excluded from MEETING_SCOPE_FIELDS by design — owner does
    # not leak its full attendee list).
    counterparty_pid = handle.owner
    return MeetingCard(
        id=handle.object_id,
        status=MeetingStatus.ACCEPTED,
        counterparty_name=_humanize_principal(counterparty_pid),
        counterparty_principal_id=counterparty_pid,
        proposed_time=state.time,
        duration_minutes=state.duration_minutes,
        title=state.title,
        last_updated=handle.issued_at,
    )


# --- adapter ----------------------------------------------------------


class SchedulingAgentInbox:
    """Reads inbox state from a real SchedulingAgent."""

    def __init__(self, agent: SchedulingAgent) -> None:
        self._agent = agent

    def list_cards(self) -> list[MeetingCard]:
        me = self._agent.principal_id
        cards: list[MeetingCard] = [
            _card_from_owned_object(obj, me)
            for obj in self._agent.objects.list()
            if _is_meeting_object(obj)
        ]
        # Receiver-side: PromotionHandles whose state we've fetched.
        cached_states = self._agent.received_meeting_states
        for handle in self._agent.objects.list_received_handles():
            if handle.schema_ref != MEETING_OBJECT_SCHEMA:
                continue
            state = cached_states.get(handle.promotion_id)
            if state is None:
                # Not yet subscribed/fetched. The caller is expected to
                # have triggered subscribe_to_pending_meetings before
                # reading the inbox.
                continue
            cards.append(_card_from_received_handle(handle, state, me))
        return cards

    def find_detail(self, meeting_id: str) -> MeetingDetail | None:
        me = self._agent.principal_id
        # Owner side first.
        try:
            obj = self._agent.objects.get(meeting_id)
        except Exception:
            obj = None
        if obj is not None and _is_meeting_object(obj):
            return self._detail_from_owned(obj, me)
        # Receiver side.
        for handle in self._agent.objects.list_received_handles():
            if handle.object_id != meeting_id:
                continue
            if handle.schema_ref != MEETING_OBJECT_SCHEMA:
                continue
            state = self._agent.received_meeting_states.get(handle.promotion_id)
            if state is None:
                continue
            return self._detail_from_received(handle, state, me)
        return None

    def _detail_from_owned(self, obj: Object, me: str) -> MeetingDetail:
        state = MeetingObjectState.model_validate(obj.state)
        counterparty_pid = _other_attendee(state.attendees, me)
        ledger_entries: list[LedgerEntry] = []
        if state.provenance_pointer:
            for residue in self._agent.ledger.get_by_context(
                state.provenance_pointer
            ):
                ledger_entries.append(_residue_to_ledger_entry(residue, me))
        return MeetingDetail(
            id=obj.object_id,
            status=MeetingStatus.ACCEPTED,
            counterparty_name=_humanize_principal(counterparty_pid),
            counterparty_principal_id=counterparty_pid,
            proposed_time=state.time,
            duration_minutes=state.duration_minutes,
            title=state.title,
            last_updated=obj.updated_at,
            agreement_hash=state.agreement_hash,
            ledger=ledger_entries,
            reasoning=(
                f"You proposed; {_humanize_principal(counterparty_pid)}'s "
                "agent accepted. Both sides share the same signed agreement."
            ),
        )

    def _detail_from_received(
        self, handle: PromotionHandle, state: MeetingObjectState, me: str,
    ) -> MeetingDetail:
        counterparty_pid = handle.owner
        ledger_entries: list[LedgerEntry] = []
        if state.provenance_pointer:
            for residue in self._agent.ledger.get_by_context(
                state.provenance_pointer
            ):
                ledger_entries.append(_residue_to_ledger_entry(residue, me))
        return MeetingDetail(
            id=handle.object_id,
            status=MeetingStatus.ACCEPTED,
            counterparty_name=_humanize_principal(counterparty_pid),
            counterparty_principal_id=counterparty_pid,
            proposed_time=state.time,
            duration_minutes=state.duration_minutes,
            title=state.title,
            last_updated=handle.issued_at,
            agreement_hash=state.agreement_hash,
            ledger=ledger_entries,
            reasoning=(
                f"{_humanize_principal(counterparty_pid)} proposed; your "
                "agent accepted. Both sides share the same signed agreement."
            ),
        )

    async def submit_new(
        self,
        req: NewMeetingRequest,
        *,
        peer_session: PrincipalSession,
    ) -> MeetingDetail:
        """Drive a real negotiation through the agent.

        `peer_session` is the counterparty's PrincipalSession in the
        same process — needed because the agent has to (a) know the
        peer's listener URL and (b) trigger `subscribe_to_pending_meetings`
        on the peer side so the receiver inbox sees the agreement
        immediately.

        M2 replaces the `peer_session` parameter with a directory
        lookup over real principals.
        """
        if peer_session.listener_url is None:
            raise RuntimeError(
                f"counterparty {peer_session.principal_id} has no listener URL — "
                "the registry's start_all_listeners() must run before submit."
            )
        candidates = default_candidate_slots(req.when_window)
        await self._agent.propose_meeting_to(
            peer_url=peer_session.listener_url,
            peer_principal_id=peer_session.principal_id,
            candidates=candidates,
            duration_minutes=req.duration_minutes,
        )
        # Trigger receiver-side subscribe + fetch so both inboxes
        # render the agreement immediately.
        if self._agent.my_url is not None:
            await peer_session.agent.subscribe_to_pending_meetings(
                peer_url=self._agent.my_url,
                my_url=peer_session.listener_url,
            )
        # Find the freshly-created MeetingObject — newest one with
        # this counterparty as the other attendee.
        me = self._agent.principal_id
        candidates_objs = [
            obj for obj in self._agent.objects.list()
            if _is_meeting_object(obj)
            and peer_session.principal_id in MeetingObjectState.model_validate(
                obj.state
            ).attendees
        ]
        if not candidates_objs:
            raise RuntimeError(
                "propose_meeting_to returned but no MeetingObject "
                "was created — counterparty likely rejected."
            )
        newest = max(candidates_objs, key=lambda o: o.updated_at)
        detail = self.find_detail(newest.object_id)
        assert detail is not None
        return detail
