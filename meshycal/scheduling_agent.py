"""SchedulingAgent — the per-user MeshyCal agent.

One agent per user. It wraps:
  - a CalendarObject (the user's owned domain object)
  - Mesherra primitives (Signer, PolicyStore, ProvenanceLedger, the
    Mesherra SDK, an A2A adapter, a directory client)
  - a reasoner (scripted or LLM-backed)

The agent is the only thing in MeshyCal that talks to Mesherra. It:
  - proposes meetings (signs + sends via Mesherra)
  - handles incoming proposals (consults the reasoner, signs + sends
    the acceptance / rejection, and books accepted meetings on its own
    CalendarObject)
  - exposes its ledger entries so the orchestrator can surface them

Identity discipline:
  - Each agent owns one Mesherra identity (via the Signer it was
    constructed with). The Mesherra SDK signs every wire artefact with
    that key.

Privacy discipline:
  - The agent never reads its own PolicyStore directly. The Mesherra
    airlock enforces it at send-time. The agent just builds the rich
    payload; Mesherra strips it down before it crosses the wire.
"""

from __future__ import annotations

import logging
from typing import Any

from mesherra.a2a_adapter import A2AAdapter
from mesherra.crypto.primitives import Signer
from mesherra.gateways.inbound import IncomingMessage, OutgoingResponse
from mesherra.identity import StaticDirectoryClient
from mesherra.models.primitives import Operation
from mesherra.policy import PolicyStore
from mesherra.provenance.ledger import ProvenanceLedger
from mesherra.sdk import Mesherra

from meshycal.calendar_object import CalendarObject
from meshycal.policy_template import PROPOSAL_SCHEMA
from meshycal.reasoners.base import ProposalVerdict, SchedulingReasoner

logger = logging.getLogger(__name__)


class SchedulingAgent:
    """One per user. Wraps a CalendarObject + Mesherra primitives + reasoner."""

    def __init__(
        self,
        *,
        calendar: CalendarObject,
        signer: Signer,
        policy_store: PolicyStore,
        ledger: ProvenanceLedger,
        directory: StaticDirectoryClient,
        reasoner: SchedulingReasoner,
        display_name: str,
    ) -> None:
        self.calendar = calendar
        self.display_name = display_name
        self._signer = signer
        self._reasoner = reasoner
        self._policy_store = policy_store
        self._ledger = ledger
        self._sdk = Mesherra(
            principal_id=calendar.owner_principal_id,
            signer=signer,
            ledger=ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=policy_store,
        )
        self._sdk.on_message(self._handle_incoming)
        self._last_verdict: ProposalVerdict | None = None

    # --- identity / accessors -----------------------------------------

    @property
    def principal_id(self) -> str:
        return self.calendar.owner_principal_id

    @property
    def ledger(self) -> ProvenanceLedger:
        """The Residue ledger this agent writes to. Read-only access for
        the orchestrator's RunResult assembly."""
        return self._ledger

    @property
    def last_verdict(self) -> ProposalVerdict | None:
        return self._last_verdict

    # --- network lifecycle --------------------------------------------

    async def start_listener(self, *, host: str, port: int) -> Any:
        """Open the inbound HTTP endpoint. Returns a handle the caller
        must .stop() in a finally block."""
        slug = self.calendar.owner_principal_id.split("@", 1)[0]
        return await self._sdk.start_listener(
            host=host, port=port, agent_name=f"meshycal-{slug}"
        )

    # --- outbound -----------------------------------------------------

    async def propose_meeting_to(
        self,
        *,
        peer_url: str,
        peer_principal_id: str,
        candidates: list[str],
        duration_minutes: int,
        constraint_hints: dict[str, Any] | None = None,
    ) -> Any:
        """Build the rich proposal payload from calendar context, fire
        it through Mesherra. The airlock strips blocked fields before
        the bytes cross the wire."""
        rich_payload = self.build_rich_payload(
            candidates=candidates,
            duration_minutes=duration_minutes,
            constraint_hints=constraint_hints,
        )
        return await self._sdk.send_to(
            peer_url=peer_url,
            peer_principal_id=peer_principal_id,
            payload=rich_payload,
            payload_schema=PROPOSAL_SCHEMA,
            operation=Operation.PROPOSAL,
        )

    def build_rich_payload(
        self,
        *,
        candidates: list[str],
        duration_minutes: int,
        constraint_hints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The 'internal' payload the agent constructs before scoped
        disclosure. Includes the blocked fields so the airlock has
        something real to strip — that's the visual story of scoped
        disclosure."""
        return {
            "candidates": list(candidates),
            "duration_minutes": int(duration_minutes),
            "calendar_titles": [e.title for e in self.calendar.events if e.title],
            "attendee_emails": list({e.attendees for e in self.calendar.events if e.attendees}),
            "constraint_hints": dict(constraint_hints or {"tz": self.calendar.timezone}),
        }

    # --- inbound ------------------------------------------------------

    async def _handle_incoming(self, msg: IncomingMessage) -> OutgoingResponse:
        """Ask the reasoner what to do, book the meeting on accept,
        return a signed acceptance (or empty acceptance on reject)."""
        try:
            duration = int(msg.payload.get("duration_minutes", 30))
        except (TypeError, ValueError):
            duration = 30
        verdict: ProposalVerdict = await self._reasoner.evaluate_proposal(
            candidate_slots=list(msg.payload.get("candidates", [])),
            duration_minutes=duration,
            my_calendar=self.calendar,
            my_display_name=self.display_name,
        )
        self._last_verdict = verdict

        if verdict.accept and verdict.chosen_slot:
            # Book on our own calendar — the agent owns this side of
            # the relationship.
            hhmm = _hhmm_from_iso(verdict.chosen_slot)
            self.calendar.book(
                time=hhmm,
                duration=duration,
                title=f"meeting with {msg.sender_principal_id}",
                attendees=f"signed · {duration} min",
            )
            return OutgoingResponse(
                payload={
                    "candidates": [verdict.chosen_slot],
                    "duration_minutes": duration,
                },
                operation=Operation.ACCEPTANCE,
                payload_schema=PROPOSAL_SCHEMA,
            )
        # Rejection — empty candidates means "none accepted."
        return OutgoingResponse(
            payload={"candidates": [], "duration_minutes": duration},
            operation=Operation.ACCEPTANCE,
            payload_schema=PROPOSAL_SCHEMA,
        )

    # --- cleanup ------------------------------------------------------

    def close(self) -> None:
        """Release sqlite handles. Call after a run completes."""
        try:
            self._policy_store.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._ledger.close()
        except Exception:  # noqa: BLE001
            pass


def _hhmm_from_iso(iso: str) -> str:
    """Extract HH:MM from an ISO 8601 string. Falls back to '00:00' on
    parse failure rather than raising — the agent should never crash
    on a weird wire value."""
    try:
        # Just slice — we know our own candidate format.
        # "2026-05-26T13:00:00Z" → "13:00"
        return iso.split("T", 1)[1][:5]
    except (IndexError, AttributeError):
        return "00:00"
