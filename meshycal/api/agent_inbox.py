"""SchedulingAgentInbox — Milestone 1 read adapter.

Replaces the skeleton's `InMemoryInbox` with one that pulls data from a
real `SchedulingAgent`'s substrate:

- `MeetingObject`s in the `ObjectStore` → accepted meetings (the
  canonical agreement exists).
- Residue entries in the `ProvenanceLedger` → the ledger we show in
  the receipt detail view.

This adapter handles the OWNER perspective only (Alice, who initiated
the negotiation, owns the MeetingObject). Receiver-side cards (Bob,
who got a promoted handle) come in M1.3 when the submit path is wired.

`submit_new()` is a stub here — wiring it to
`SchedulingAgent.propose_meeting_to` is M1.3's job. The read path
must work first.
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

if TYPE_CHECKING:
    from mesherra.models.primitives import Object, Residue

    from meshycal.scheduling_agent import SchedulingAgent


def _humanize_principal(principal_id: str) -> str:
    """`bob@sandbox.local` → `Bob`. Local part, capitalized."""
    local = principal_id.split("@", 1)[0]
    # Hyphens and dots split into words; rejoin capitalized.
    return " ".join(p.capitalize() for p in local.replace(".", "-").split("-"))


def _other_attendee(attendees: list[str], me: str) -> str:
    """Pick the counterparty from MeetingObjectState.attendees."""
    for a in attendees:
        if a != me:
            return a
    # Self-meeting (unusual but possible) — surface me as counterparty.
    return me


def _residue_to_ledger_entry(residue: Residue, me: str) -> LedgerEntry:
    """Project one Mesherra `Residue` into a renderer-facing LedgerEntry.

    The substrate-shaped `operation` carries the raw Mesherra Operation
    value; `action` is pre-composed prose for the default web renderer.
    Second renderers may compose their own prose from `operation`.
    """
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


def _card_from_object(obj: Object, me: str) -> MeetingCard:
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


class SchedulingAgentInbox:
    """Reads inbox state from a real SchedulingAgent."""

    def __init__(self, agent: SchedulingAgent) -> None:
        self._agent = agent

    def list_cards(self) -> list[MeetingCard]:
        me = self._agent.principal_id
        cards = [
            _card_from_object(obj, me)
            for obj in self._agent.objects.list()
            if _is_meeting_object(obj)
        ]
        # Owner-only for M1.1; pending and declined will pull from
        # the proposal_store + ledger in M1.3.
        return cards

    def find_detail(self, meeting_id: str) -> MeetingDetail | None:
        me = self._agent.principal_id
        try:
            obj = self._agent.objects.get(meeting_id)
        except Exception:
            return None
        if not _is_meeting_object(obj):
            return None
        state = MeetingObjectState.model_validate(obj.state)
        counterparty_pid = _other_attendee(state.attendees, me)
        ledger_entries: list[LedgerEntry] = []
        if state.provenance_pointer:
            # Pull the residue chain that backed this meeting's
            # negotiation. Only present when the MeetingObject came
            # from a real propose_meeting_to flow.
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
                f"Agreement signed. Both your and "
                f"{_humanize_principal(counterparty_pid)}'s agents see "
                "the same canonical record."
            ),
        )

    def submit_new(self, req: NewMeetingRequest) -> MeetingDetail:
        """Wired to SchedulingAgent.propose_meeting_to in M1.3."""
        raise NotImplementedError(
            "M1.3 wires submit to SchedulingAgent.propose_meeting_to. "
            "M1.1 only implements the read adapter."
        )
