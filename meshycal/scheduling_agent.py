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
from datetime import UTC, datetime, timedelta
from typing import Any

from mesherra.a2a_adapter import A2AAdapter
from mesherra.crypto.primitives import Signer, canonical_json, content_hash
from mesherra.gateways.inbound import IncomingMessage, OutgoingResponse
from mesherra.identity import StaticDirectoryClient
from mesherra.models.primitives import LayerKind, Mutability, Operation, PromotionHandle
from mesherra.object.store import ObjectStore
from mesherra.policy import PolicyStore
from mesherra.provenance.ledger import ProvenanceLedger
from mesherra.sdk import Mesherra

from meshycal.calendar_object import CalendarObject
from meshycal.meeting_object import MEETING_OBJECT_SCHEMA, MeetingObjectState
from meshycal.policy_template import PROPOSAL_SCHEMA
from meshycal.reasoners.base import ProposalVerdict, SchedulingReasoner

logger = logging.getLogger(__name__)

PROMOTION_HANDLE_SCHEMA = "mesherra.object/promotion-handle-v1"


def default_candidate_slots(
    when_window: str, *, count: int = 3,
) -> list[str]:
    """Pick `count` weekday slots starting tomorrow at 14:00 UTC.

    The naive default used when the caller (e.g. MeshyCal's
    submit-meeting flow) doesn't yet have an LLM-backed reasoner that
    can parse `when_window` semantically. M2's calendar-aware reasoner
    will replace this with real intent parsing; the ScriptedReasoner
    path keeps using these defaults.

    Lives on the agent side (CLAUDE.md rule 5) so a future second
    Delegation's renderer doesn't have to know what "a sensible
    candidate slot" means for scheduling.
    """
    base = (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=14, minute=0, second=0, microsecond=0,
    )
    slots: list[str] = []
    cursor = base
    while len(slots) < count:
        if cursor.weekday() < 5:  # Mon-Fri only
            slots.append(cursor.strftime("%Y-%m-%dT%H:%M:%SZ"))
        cursor += timedelta(days=1)
    return slots

# Scoped fields the MeetingObject's live-reference promotion exposes to
# the counterpart. The full MeetingObjectState is wider; per CLAUDE.md
# Rule 5 / ARCH §3.2, only these fields cross the boundary by default.
MEETING_SCOPE_FIELDS = [
    "time",
    "duration_minutes",
    "timezone",
    "title",
    "location",
    "agreement_hash",
    "provenance_pointer",
]


class SchedulingAgent:
    """One per user. Wraps a CalendarObject + Mesherra primitives + reasoner."""

    def __init__(
        self,
        *,
        calendar: CalendarObject,
        signer: Signer,
        policy_store: PolicyStore,
        ledger: ProvenanceLedger,
        object_store: ObjectStore,
        directory: StaticDirectoryClient,
        reasoner: SchedulingReasoner,
        display_name: str,
        single_process_mode: bool = False,
    ) -> None:
        self.calendar = calendar
        self.display_name = display_name
        self._signer = signer
        self._reasoner = reasoner
        self._policy_store = policy_store
        self._ledger = ledger
        self._object_store = object_store
        self._sdk = Mesherra(
            principal_id=calendar.owner_principal_id,
            signer=signer,
            ledger=ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=policy_store,
            object_store=object_store,
        )
        self._sdk.on_message(self._handle_incoming)
        self._sdk.on_object_update(self._handle_object_update)
        self._last_verdict: ProposalVerdict | None = None
        # Receiver-side: track which received MeetingObject handles we've
        # already subscribed+fetched+booked. Idempotency for
        # subscribe_to_pending_meetings.
        self._processed_meeting_handles: set[str] = set()
        # Receiver-side cache of fetched MeetingObjectState by promotion_id.
        # Populated by subscribe_to_pending_meetings after the SDK
        # fetch_object call. The cache lets a renderer (or anyone reading
        # the agent's substrate) show the agreed slot/title/hash without
        # re-fetching from the owner on every read. Lost on restart —
        # M2's persistent storage stage will materialize this in SQLite.
        self._received_meeting_states: dict[str, MeetingObjectState] = {}
        # Listener URL — populated by start_listener. Carried so the
        # SchedulingAgent can advertise its own URL in subscribe requests
        # (so owners know where to push) and in propose_meeting_to (so
        # counterparts can promote MeetingObjects to us via PROMOTE).
        self._my_url: str | None = None
        # In-process simulation flag. When True, propose_meeting_to is
        # allowed to skip the LIVE promotion step if no listener is
        # set (the sandbox runner uses this). Production callers leave
        # it False so a missing start_listener() raises rather than
        # silently degrading the §3.2 keystone flow.
        self._single_process_mode = single_process_mode

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
    def objects(self) -> ObjectStore:
        """The per-principal ObjectStore. Holds Mesherra Objects this
        agent owns (CalendarObject is hand-rolled, not yet in here;
        MeetingObjects ARE in here once Alice creates them) and
        PromotionHandles this agent has received from others."""
        return self._object_store

    @property
    def last_verdict(self) -> ProposalVerdict | None:
        return self._last_verdict

    @property
    def my_url(self) -> str | None:
        """The listener URL this agent is reachable at. None until
        :meth:`start_listener` is called."""
        return self._my_url

    @property
    def received_meeting_states(self) -> dict[str, MeetingObjectState]:
        """Receiver-side cache of fetched MeetingObjectStates by
        promotion_id. Read-only copy. Populated by
        :meth:`subscribe_to_pending_meetings`."""
        return dict(self._received_meeting_states)

    # --- network lifecycle --------------------------------------------

    async def start_listener(self, *, host: str, port: int) -> Any:
        """Open the inbound HTTP endpoint. Returns a handle the caller
        must .stop() in a finally block. Stores the resulting URL on
        ``self._my_url`` so SUBSCRIBE requests can advertise it."""
        slug = self.calendar.owner_principal_id.split("@", 1)[0]
        listener_handle = await self._sdk.start_listener(
            host=host, port=port, agent_name=f"meshycal-{slug}"
        )
        self._my_url = f"http://{host}:{port}/"
        return listener_handle

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
        the bytes cross the wire.

        On a successful ACCEPTANCE response (per ARCH §8 step 9), creates
        a canonical MeetingObject as a real Mesherra Object, promotes it
        LIVE to the counterpart, ships the handle via PROMOTE, and books
        the meeting on this side's CalendarObject. The MeetingObject is
        the singular shared agreement both sides reference; the previous
        "each side books independently" pattern is replaced.
        """
        rich_payload = self.build_rich_payload(
            candidates=candidates,
            duration_minutes=duration_minutes,
            constraint_hints=constraint_hints,
        )
        result = await self._sdk.send_to(
            peer_url=peer_url,
            peer_principal_id=peer_principal_id,
            payload=rich_payload,
            payload_schema=PROPOSAL_SCHEMA,
            operation=Operation.PROPOSAL,
        )

        # If the counterpart's response is an ACCEPTANCE with a chosen
        # slot, promote a MeetingObject. Otherwise the negotiation is
        # done (rejection or counter to be handled by the caller).
        acceptance = _extract_acceptance(result)
        if acceptance is None:
            return result
        chosen_slot, accepted_duration = acceptance

        # Build the canonical MeetingObject as a real Mesherra Object.
        agreement_hash = content_hash(
            canonical_json(_canonical_agreement_payload(
                chosen_slot=chosen_slot,
                duration_minutes=accepted_duration,
            ))
        )
        state = MeetingObjectState(
            time=chosen_slot,
            duration_minutes=accepted_duration,
            timezone=self.calendar.timezone,
            title=f"meeting with {peer_principal_id}",
            location=None,
            attendees=[self.calendar.owner_principal_id, peer_principal_id],
            agreement_hash=agreement_hash,
            provenance_pointer=getattr(result, "context_id", None),
        )
        meeting_obj = self._sdk.create_object(
            state=state.model_dump(),
            home_layer=LayerKind.PERSONAL,
            mutability=Mutability.LIVE,
            schema_ref=MEETING_OBJECT_SCHEMA,
        )

        # Promote the MeetingObject LIVE to the counterpart. The
        # fetch_endpoint_base must point at THIS agent's listener so the
        # counterpart can fetch the initial state. Without my_url set
        # (e.g., the in-process sandbox runner that has no HTTP
        # listener), skip the promotion entirely — the agreement still
        # exists as a Mesherra Object on this side but cannot be shared
        # live until a listener is wired. Production callers should
        # start_listener() before propose_meeting_to() to enable the
        # full §3.2 flow.
        if self._my_url is None:
            if not self._single_process_mode:
                raise RuntimeError(
                    "propose_meeting_to: this agent has no listener URL. "
                    "Call start_listener(...) first so the counterpart "
                    "can fetch the MeetingObject. (For in-process "
                    "simulation that does not exercise the §3.2 LIVE "
                    "flow, construct SchedulingAgent with "
                    "single_process_mode=True.)"
                )
            logger.debug(
                "single_process_mode: skipping LIVE promotion of "
                "MeetingObject %s — booking locally only.",
                meeting_obj.object_id,
            )
            hhmm = _hhmm_from_iso(chosen_slot)
            self.calendar.book(
                time=hhmm,
                duration=accepted_duration,
                title=f"meeting with {peer_principal_id}",
                attendees=f"signed · {accepted_duration} min",
            )
            return result
        expiry = (datetime.now(UTC) + timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        _promotion, signed_handle = self._sdk.promote(
            object_id=meeting_obj.object_id,
            receiver=peer_principal_id,
            scope={"fields": MEETING_SCOPE_FIELDS},
            expiry=expiry,
            mutability=Mutability.LIVE,
            fetch_endpoint_base=self._my_url.rstrip("/"),
        )

        # Ship the handle via PROMOTE. The counterpart's
        # ObjectInboundHandler will persist it; the SchedulingAgent on
        # that side picks it up via subscribe_to_pending_meetings().
        await self._sdk.send_to(
            peer_url=peer_url,
            peer_principal_id=peer_principal_id,
            payload=signed_handle.model_dump(),
            payload_schema=PROMOTION_HANDLE_SCHEMA,
            operation=Operation.PROMOTE,
        )

        # Book on this side's calendar — the initiator is the canonical
        # owner of the MeetingObject AND books the slot locally.
        hhmm = _hhmm_from_iso(chosen_slot)
        self.calendar.book(
            time=hhmm,
            duration=accepted_duration,
            title=f"meeting with {peer_principal_id}",
            attendees=f"signed · {accepted_duration} min",
        )
        return result

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

    async def _handle_incoming(self, message: IncomingMessage) -> OutgoingResponse:
        """Ask the reasoner what to do, send a signed acceptance back.

        Per ARCH §3.2: the counterpart does NOT book locally on accept.
        The canonical agreement is the MeetingObject the initiator
        promotes after this acceptance reaches them. The counterpart's
        calendar booking happens via :meth:`subscribe_to_pending_meetings`
        once Alice's PROMOTE arrives and Bob fetches the initial state.
        """
        try:
            duration = int(message.payload.get("duration_minutes", 30))
        except (TypeError, ValueError):
            duration = 30
        verdict: ProposalVerdict = await self._reasoner.evaluate_proposal(
            candidate_slots=list(message.payload.get("candidates", [])),
            duration_minutes=duration,
            my_calendar=self.calendar,
            my_display_name=self.display_name,
        )
        self._last_verdict = verdict

        if verdict.accept and verdict.chosen_slot:
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

    async def _handle_object_update(
        self,
        handle: PromotionHandle,
        new_state: dict[str, Any],
        object_version: int,
    ) -> None:
        """Receiver-side callback: an owner pushed a new state for a live
        promotion we subscribed to.

        For MeetingObject schemas, the state changes most often reflect
        reschedules or cancellations the initiator made. Slice 1 of the
        MeshyCal MeetingObject flow does NOT auto-book on update push
        beyond the initial subscribe-and-fetch step (handled in
        :meth:`subscribe_to_pending_meetings`); the consumer of the
        SchedulingAgent decides how to surface live changes to the user.
        We record the latest state so a polling caller can observe it
        through the ObjectStore.
        """
        # Slice 1 (consumer-MVP): no-op beyond what the trust layer's
        # bookkeeping already does (bumps last_pushed_object_version,
        # writes paired residue). Reschedule / cancel UX lives in the
        # renderer; ARCH §12 open question 7.
        if handle.schema_ref == MEETING_OBJECT_SCHEMA:
            logger.debug(
                "MeetingObject update for promotion %s v=%s state=%s",
                handle.promotion_id, object_version, new_state,
            )

    async def subscribe_to_pending_meetings(
        self,
        *,
        peer_url: str,
        my_url: str | None = None,
    ) -> list[str]:
        """Pick up any received MeetingObject handles, subscribe, fetch
        the initial state, and book the meeting on this side's calendar.

        Returns the list of promotion_ids newly processed.

        The trust-layer PROMOTE dispatch persists incoming handles in
        the receiver's ObjectStore but does not notify the consumer —
        SchedulingAgent's ``on_message`` callback only fires for non-
        trust-layer operations. The consumer (this method, or a polling
        loop in production) is responsible for picking up new handles
        and acting on them. Idempotent: a handle already in
        :attr:`_processed_meeting_handles` is skipped.

        ``my_url`` defaults to :attr:`my_url` (set by start_listener);
        callers can override for tests that don't go through the
        listener path.
        """
        if my_url is None:
            my_url = self._my_url

        newly_processed: list[str] = []
        for handle in self._object_store.list_received_handles():
            if handle.schema_ref != MEETING_OBJECT_SCHEMA:
                continue
            if handle.promotion_id in self._processed_meeting_handles:
                continue

            # Subscribe so future owner-side mutations push to us.
            await self._sdk.subscribe_to_object(
                handle=handle, peer_url=peer_url, my_url=my_url,
            )
            # Fetch the initial state — subscription itself does not
            # backfill; pushes only fire on future mutations.
            initial_state_dict = await self._sdk.fetch_object(
                handle=handle, peer_url=peer_url,
            )
            state = MeetingObjectState.model_validate(initial_state_dict)

            # Cache the fetched state so renderers (and other consumers
            # of this agent's substrate) can read it without re-fetching
            # from the owner on every inbox render.
            self._received_meeting_states[handle.promotion_id] = state

            # Book on this side's calendar.
            hhmm = _hhmm_from_iso(state.time)
            self.calendar.book(
                time=hhmm,
                duration=state.duration_minutes,
                title=state.title,
                attendees=(
                    f"signed · {state.duration_minutes} min"
                ),
            )
            self._processed_meeting_handles.add(handle.promotion_id)
            newly_processed.append(handle.promotion_id)
        return newly_processed

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
        try:
            self._object_store.close()
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


def _extract_acceptance(send_result: Any) -> tuple[str, int] | None:
    """Inspect an OutboundResult from a PROPOSAL send. If the response is
    an ACCEPTANCE with at least one chosen slot, return (chosen_slot,
    duration_minutes); otherwise None.

    Defensive on shape: the wire payload may have been narrowed by the
    receiver's outbound policy, so we accept a partial dict.
    """
    op = getattr(send_result, "response_operation", None)
    if op is None or op is not Operation.ACCEPTANCE:
        return None
    payload = getattr(send_result, "response_payload", None) or {}
    candidates = payload.get("candidates") or []
    if not candidates:
        return None  # empty candidates = rejection
    chosen = candidates[0]
    try:
        duration = int(payload.get("duration_minutes", 30))
    except (TypeError, ValueError):
        duration = 30
    return chosen, duration


def _canonical_agreement_payload(
    *, chosen_slot: str, duration_minutes: int
) -> dict[str, Any]:
    """The agreement_hash on a MeetingObject commits to the agreed
    Proposal that produced it. Slice 1 of MeshyCal hashes a minimal
    canonical pair (chosen_slot + duration_minutes); the full Proposal
    chain is reachable via the residue ledger pointer (provenance_pointer).
    """
    return {
        "chosen_slot": chosen_slot,
        "duration_minutes": int(duration_minutes),
    }
