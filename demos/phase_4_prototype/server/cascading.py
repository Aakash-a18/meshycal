"""Phase 4 prototype Scenario 3 — cascading reschedule.

Three principals (Iris, Marius, Atlas) run real Mesherra instances on
localhost. Iris asks Marius for a meeting at a slot Marius has already
committed to Atlas. Marius' inbound handler invokes a scripted
:class:`SchedulingReasoner`, decides to move the Atlas meeting, calls
``await marius_sdk.send_to(atlas_url, ...)`` **before returning to Iris**,
gets Atlas' acceptance, then returns acceptance to Iris.

The cascade is composed of three signed bilateral exchanges chained over
two A2A task IDs:

* Exchange A — Iris→Marius proposal           (task_id_1, seq Iris=0 / Marius=0)
* Exchange B — Marius↔Atlas reschedule        (task_id_2, seq Marius=1,2 / Atlas=0,1)
* Exchange C — Marius→Iris acceptance         (task_id_1, seq Marius=3 / Iris=1)

Marius' ledger is one hash chain across both task IDs (4 entries total).

The Mesherra :class:`InboundGateway` awaits the consumer handler
(``outgoing = await self._consumer(incoming)``), so the Atlas
sub-negotiation completes before Marius' acceptance response travels back
to Iris. This file does not modify Mesherra; the cascade is just the
existing :meth:`Mesherra.send_to` called twice in the right order from
inside the inbound handler.

Persistence is tempdir-scoped — nothing survives the call.
"""

from __future__ import annotations

import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mesherra.a2a_adapter import A2AAdapter
from mesherra.crypto.primitives import Signer
from mesherra.gateways.inbound import IncomingMessage, OutgoingResponse
from mesherra.identity import StaticDirectoryClient
from mesherra.models.primitives import Operation
from mesherra.policy import (
    Direction,
    Match,
    PolicyDoc,
    PolicyStore,
    Rule,
    sign_policy_doc,
)
from mesherra.provenance.ledger import ProvenanceLedger
from mesherra.sdk import Mesherra

from .reasoner import (
    CalendarEvent,
    RescheduleProposal,
    SchedulingReasoner,
    ScriptedReasoner,
)
from .scenarios import (
    PAYLOAD_SCHEMA,
    ResidueDTO,
    _free_port,
    _residue_to_dto,
    _strip_blocked_fields,
)


# -- Principals & synthetic calendar fixtures ------------------------------

IRIS = "iris@meshycal.demo"
MARIUS = "marius@meshycal.demo"
ATLAS = "atlas@meshycal.demo"


IRIS_SYNTHETIC_CALENDAR: list[CalendarEvent] = [
    CalendarEvent("2026-06-02T09:00:00Z", 60, "synthetic-morning-standup", []),
    CalendarEvent("2026-06-02T11:00:00Z", 30, "synthetic-focus-block", []),
]


MARIUS_SYNTHETIC_CALENDAR: list[CalendarEvent] = [
    CalendarEvent("2026-06-02T10:00:00Z", 60, "synthetic-weekly-review", []),
    CalendarEvent("2026-06-02T14:00:00Z", 45, "synthetic-project-sync", [ATLAS]),
    CalendarEvent("2026-06-02T15:30:00Z", 30, "synthetic-1-on-1", []),
]


ATLAS_INFERRED_FREE_SLOTS: list[str] = [
    "2026-06-02T16:00:00Z",
    "2026-06-02T17:00:00Z",
]


# -- Wire / response shapes ------------------------------------------------


class BilateralExchangeDTO(BaseModel):
    """Cryptographic evidence for one completed bilateral exchange."""

    model_config = ConfigDict(extra="forbid")

    exchange_label: str
    initiator: str
    responder: str
    proposal_payload_hash: str
    acceptance_payload_hash: str
    task_id: str


class ReasonerTraceDTO(BaseModel):
    """Marius' agent's reasoning output. Rendered verbatim in the UI."""

    model_config = ConfigDict(extra="forbid")

    requested_slot: str
    blocking_event_title: str
    blocking_event_attendee: str
    proposed_new_slot: str
    reason: str


class CalendarEventDTO(BaseModel):
    """Wire-safe projection of CalendarEvent for the UI.

    ``attendee_principal_ids`` is intentionally omitted per scoping
    discipline — co-attendee identities are internal to the reasoner.
    """

    model_config = ConfigDict(extra="forbid")

    slot_start: str
    duration_minutes: int
    title: str


class CalendarStateDTO(BaseModel):
    """Principal's calendar before and after the cascade."""

    model_config = ConfigDict(extra="forbid")

    principal_id: str
    before: list[CalendarEventDTO]
    after: list[CalendarEventDTO]


class CascadingResult(BaseModel):
    """Complete structured output of the cascading-reschedule scenario."""

    model_config = ConfigDict(extra="forbid")

    iris_principal_id: str
    marius_principal_id: str
    atlas_principal_id: str

    reasoner_trace: ReasonerTraceDTO

    exchange_iris_marius_proposal: BilateralExchangeDTO
    exchange_marius_atlas: BilateralExchangeDTO
    exchange_marius_iris_acceptance: BilateralExchangeDTO

    iris_scoped_proposal: dict[str, Any]
    marius_reschedule_proposal: dict[str, Any]
    atlas_acceptance_payload: dict[str, Any]
    marius_acceptance_to_iris: dict[str, Any]

    iris_ledger: list[ResidueDTO]
    marius_ledger: list[ResidueDTO]
    atlas_ledger: list[ResidueDTO]

    iris_calendar: CalendarStateDTO
    marius_calendar: CalendarStateDTO
    atlas_calendar: CalendarStateDTO

    policy_doc_iris: dict[str, Any]
    duration_ms: int


# -- Exceptions ------------------------------------------------------------


class CascadeAbortedError(RuntimeError):
    """Raised when the cascade cannot complete (reasoner None, Atlas
    declines, etc.). The endpoint surfaces this as a 500."""


# -- Policy helper ---------------------------------------------------------


def _cascading_policy(principal_id: str) -> PolicyDoc:
    """Same default MeshyCal policy template as scenario 1, per-principal.

    Outbound blocks ``calendar_titles`` + ``attendee_emails``; inbound
    allows the standard proposal fields. Mirroring scenario 1 keeps the
    scoping discipline identical across all three principals.
    """
    return PolicyDoc(
        principal_id=principal_id,
        version=1,
        issued_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rules=[
            Rule(
                match=Match(schema=PAYLOAD_SCHEMA, direction=Direction.OUTBOUND),
                outbound_allow=[
                    "candidates",
                    "duration_minutes",
                    "constraint_hints",
                ],
                outbound_block=["calendar_titles", "attendee_emails"],
                max_array_size={"candidates": 5},
            ),
            Rule(
                match=Match(schema=PAYLOAD_SCHEMA, direction=Direction.INBOUND),
                inbound_allow=[
                    "candidates",
                    "duration_minutes",
                    "constraint_hints",
                ],
            ),
        ],
    )


# -- Calendar delta helpers (pure; no I/O) --------------------------------


def _event_to_dto(event: CalendarEvent) -> CalendarEventDTO:
    return CalendarEventDTO(
        slot_start=event.slot_start,
        duration_minutes=event.duration_minutes,
        title=event.title,
    )


def _events_to_dtos(events: list[CalendarEvent]) -> list[CalendarEventDTO]:
    return [_event_to_dto(e) for e in events]


def _calendar_after_move(
    events: list[CalendarEvent], *, moved_title: str, new_slot: str
) -> list[CalendarEvent]:
    """Return a new list with the event titled ``moved_title`` re-anchored
    to ``new_slot``. All other events unchanged; original list untouched.
    """
    out: list[CalendarEvent] = []
    for e in events:
        if e.title == moved_title:
            out.append(
                CalendarEvent(
                    slot_start=new_slot,
                    duration_minutes=e.duration_minutes,
                    title=e.title,
                    attendee_principal_ids=list(e.attendee_principal_ids),
                )
            )
        else:
            out.append(e)
    return out


def _calendar_after_add(
    events: list[CalendarEvent], *, new_event: CalendarEvent
) -> list[CalendarEvent]:
    """Return a new list with ``new_event`` appended. Original untouched."""
    return [*events, new_event]


# -- Orchestrator ----------------------------------------------------------


async def run_cascading(
    reasoner: SchedulingReasoner | None = None,
) -> CascadingResult:
    """Run the three-principal cascading-reschedule scenario.

    Everything is real: real Ed25519 keys, real signed envelopes, real
    PolicyStore enforcement, real SHA-256(JCS()) hashes, two real A2A
    listeners (Marius, Atlas). Persistence is to a tempdir deleted on
    exit.

    ``reasoner`` defaults to :class:`ScriptedReasoner`. Inject a custom
    implementation to exercise the alternative branches (None →
    :class:`CascadeAbortedError`).

    Raises:
        CascadeAbortedError: reasoner returned None, or Atlas declined,
            or an unexpected non-acceptance response came back.
    """
    started = time.monotonic()
    active_reasoner = reasoner if reasoner is not None else ScriptedReasoner()

    with tempfile.TemporaryDirectory(prefix="meshycal-phase4-cascading-") as td:
        td_path = Path(td)

        # -- Keys and directory --------------------------------------
        iris_signer = Signer.generate()
        marius_signer = Signer.generate()
        atlas_signer = Signer.generate()
        directory = StaticDirectoryClient(
            {
                IRIS: iris_signer.public_key_b64(),
                MARIUS: marius_signer.public_key_b64(),
                ATLAS: atlas_signer.public_key_b64(),
            }
        )

        # -- Per-principal PolicyStores ------------------------------
        iris_store = PolicyStore(
            db_path=td_path / "iris_policy.sqlite",
            principal_id=IRIS,
            public_key_b64=iris_signer.public_key_b64(),
        )
        marius_store = PolicyStore(
            db_path=td_path / "marius_policy.sqlite",
            principal_id=MARIUS,
            public_key_b64=marius_signer.public_key_b64(),
        )
        atlas_store = PolicyStore(
            db_path=td_path / "atlas_policy.sqlite",
            principal_id=ATLAS,
            public_key_b64=atlas_signer.public_key_b64(),
        )

        iris_policy_signed = sign_policy_doc(
            doc=_cascading_policy(IRIS), signer=iris_signer
        )
        marius_policy_signed = sign_policy_doc(
            doc=_cascading_policy(MARIUS), signer=marius_signer
        )
        atlas_policy_signed = sign_policy_doc(
            doc=_cascading_policy(ATLAS), signer=atlas_signer
        )
        iris_store.save_signed(iris_policy_signed)
        marius_store.save_signed(marius_policy_signed)
        atlas_store.save_signed(atlas_policy_signed)

        # -- Per-principal ledgers -----------------------------------
        iris_ledger = ProvenanceLedger(
            db_path=td_path / "iris_ledger.sqlite", ledger_owner=IRIS
        )
        marius_ledger = ProvenanceLedger(
            db_path=td_path / "marius_ledger.sqlite", ledger_owner=MARIUS
        )
        atlas_ledger = ProvenanceLedger(
            db_path=td_path / "atlas_ledger.sqlite", ledger_owner=ATLAS
        )

        # -- SDK instances -------------------------------------------
        iris_sdk = Mesherra(
            principal_id=IRIS,
            signer=iris_signer,
            ledger=iris_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=iris_store,
        )
        marius_sdk = Mesherra(
            principal_id=MARIUS,
            signer=marius_signer,
            ledger=marius_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=marius_store,
        )
        atlas_sdk = Mesherra(
            principal_id=ATLAS,
            signer=atlas_signer,
            ledger=atlas_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=atlas_store,
        )

        # -- Captured state across handlers --------------------------
        captured_atlas_acceptance: dict[str, Any] = {}
        captured_marius_acceptance_to_iris: dict[str, Any] = {}
        captured_marius_reschedule_proposal: dict[str, Any] = {}
        captured_proposal: dict[str, Any] = {}
        captured_marius_atlas_task_id: dict[str, str] = {}
        # Initialize as None — set inside marius_handler. Plain box.
        reasoner_proposal_box: dict[str, RescheduleProposal] = {}

        # -- Atlas handler: accepts the first candidate unconditionally
        async def atlas_handler(msg: IncomingMessage) -> OutgoingResponse:
            chosen = msg.payload["candidates"][0]
            duration = int(msg.payload["duration_minutes"])
            acceptance = {
                "candidates": [chosen],
                "duration_minutes": duration,
            }
            captured_atlas_acceptance.update(acceptance)
            return OutgoingResponse(
                payload=acceptance,
                operation=Operation.ACCEPTANCE,
                payload_schema=PAYLOAD_SCHEMA,
            )

        # -- Marius handler: the cascade pivot.
        #    Runs the reasoner, calls send_to(atlas_url, ...) BEFORE
        #    returning. Mesherra's InboundGateway awaits this handler so
        #    the Atlas round-trip completes before our acceptance is
        #    emitted back to Iris.
        async def marius_handler(msg: IncomingMessage) -> OutgoingResponse:
            captured_proposal.update(dict(msg.payload))

            requested_slot = msg.payload["candidates"][0]
            requested_duration = int(msg.payload["duration_minutes"])

            try:
                proposal = active_reasoner.propose_reschedule_target(
                    requested_slot=requested_slot,
                    requested_duration_minutes=requested_duration,
                    current_calendar=MARIUS_SYNTHETIC_CALENDAR,
                    atlas_principal_id=ATLAS,
                    atlas_inferred_free_slots=ATLAS_INFERRED_FREE_SLOTS,
                )
            except Exception as e:  # pragma: no cover - re-raise as cascade abort
                raise CascadeAbortedError(
                    f"reasoner raised while evaluating slot {requested_slot}: {e!r}"
                ) from e

            if proposal is None:
                raise CascadeAbortedError(
                    f"reasoner found no viable reschedule slot for "
                    f"requested slot {requested_slot}; cannot accept "
                    "Iris' proposal"
                )

            reasoner_proposal_box["proposal"] = proposal

            # Look up the blocking event so we can carry its real
            # duration into the reschedule proposal.
            blocking_event: CalendarEvent | None = None
            for e in MARIUS_SYNTHETIC_CALENDAR:
                if e.slot_start == requested_slot:
                    blocking_event = e
                    break
            blocking_duration = (
                blocking_event.duration_minutes if blocking_event is not None else 45
            )

            reschedule_payload = {
                "candidates": [proposal.new_slot],
                "duration_minutes": blocking_duration,
                "constraint_hints": {
                    "reason": "synthetic-reschedule-for-new-request",
                },
            }
            captured_marius_reschedule_proposal.update(reschedule_payload)

            # The cascade pivot. Held open inside marius_handler; the
            # Atlas exchange becomes task_id_2, distinct from Iris↔Marius's
            # task_id_1.
            atlas_result = await marius_sdk.send_to(
                peer_url=atlas_url,
                peer_principal_id=ATLAS,
                payload=reschedule_payload,
                payload_schema=PAYLOAD_SCHEMA,
                operation=Operation.PROPOSAL,
            )

            if atlas_result.response_operation is not Operation.ACCEPTANCE:
                raise CascadeAbortedError(
                    f"atlas declined the reschedule proposal for "
                    f"{proposal.new_slot}; cannot free the requested slot"
                )

            captured_marius_atlas_task_id["task_id"] = atlas_result.task_id

            # Now accept Iris' original request.
            iris_acceptance_payload = {
                "candidates": [requested_slot],
                "duration_minutes": requested_duration,
            }
            captured_marius_acceptance_to_iris.update(iris_acceptance_payload)
            return OutgoingResponse(
                payload=iris_acceptance_payload,
                operation=Operation.ACCEPTANCE,
                payload_schema=PAYLOAD_SCHEMA,
            )

        marius_sdk.on_message(marius_handler)
        atlas_sdk.on_message(atlas_handler)
        # Iris is purely outbound here, but A2AAdapter still requires a
        # handler to be registered.
        iris_sdk.on_message(lambda msg: None)  # type: ignore[arg-type]

        # -- Boot listeners (both Marius and Atlas; Iris is outbound only).
        # URLs are bound BEFORE start_listener so marius_handler's closure
        # over atlas_url is never UnboundLocalError-able if listener startup
        # raises mid-sequence. The handler is registered above; if any code
        # path tries to invoke it before listener startup, atlas_url is
        # already a valid string.
        marius_port = _free_port()
        atlas_port = _free_port()
        marius_url = f"http://127.0.0.1:{marius_port}/"
        atlas_url = f"http://127.0.0.1:{atlas_port}/"
        marius_handle = await marius_sdk.start_listener(
            host="127.0.0.1",
            port=marius_port,
            agent_name="meshycal-marius",
        )
        atlas_handle = await atlas_sdk.start_listener(
            host="127.0.0.1",
            port=atlas_port,
            agent_name="meshycal-atlas",
        )

        try:
            # -- Iris' rich proposal (pre-airlock) --------------------
            iris_rich_proposal: dict[str, Any] = {
                "candidates": ["2026-06-02T14:00:00Z"],
                "duration_minutes": 30,
                "calendar_titles": ["synthetic-morning-standup"],
                "attendee_emails": ["synthetic-iris-attendee@example.invalid"],
                "constraint_hints": {
                    "tz": "Europe/Paris",
                    "preferred_window": {"start_hour": 9, "end_hour": 18},
                },
            }
            iris_scoped_proposal_expected = _strip_blocked_fields(iris_rich_proposal)

            try:
                iris_result = await iris_sdk.send_to(
                    peer_url=marius_url,
                    peer_principal_id=MARIUS,
                    payload=iris_rich_proposal,
                    payload_schema=PAYLOAD_SCHEMA,
                    operation=Operation.PROPOSAL,
                )
            except Exception as e:
                # marius_handler may have raised CascadeAbortedError
                # (reasoner returned None, atlas declined, etc.). The A2A
                # framework wraps handler exceptions as an InternalError on
                # the caller side. Surface a CascadeAbortedError to the
                # orchestrator's caller verbatim, preserving the original
                # reason string when present.
                if isinstance(e, CascadeAbortedError):
                    raise
                msg = str(e)
                if "reasoner found no viable reschedule slot" in msg:
                    raise CascadeAbortedError(
                        "reasoner found no viable reschedule slot; "
                        "cannot free the requested slot"
                    ) from e
                if "atlas declined" in msg.lower():
                    raise CascadeAbortedError(
                        f"atlas declined the reschedule proposal; {msg}"
                    ) from e
                raise CascadeAbortedError(
                    f"cascade aborted during iris->marius send: {e!r}"
                ) from e
        finally:
            await marius_handle.stop()
            await atlas_handle.stop()

        # -- Result accounting --------------------------------------
        if iris_result.response_operation is not Operation.ACCEPTANCE:
            raise CascadeAbortedError(
                "marius did not return ACCEPTANCE to iris; "
                f"got {iris_result.response_operation.value}"
            )

        if "proposal" not in reasoner_proposal_box:
            # Should be unreachable on the happy path; defensive.
            raise CascadeAbortedError(
                "reasoner_proposal_box missing 'proposal' after iris_result; "
                "marius_handler did not run as expected"
            )
        proposal = reasoner_proposal_box["proposal"]

        task_id_1 = iris_result.task_id
        task_id_2 = captured_marius_atlas_task_id["task_id"]

        # -- Ledger projection --------------------------------------
        iris_entries = sorted(
            iris_ledger.get_by_task(task_id_1), key=lambda r: r.sequence
        )
        marius_entries_t1 = list(marius_ledger.get_by_task(task_id_1))
        marius_entries_t2 = list(marius_ledger.get_by_task(task_id_2))
        # Marius keeps ONE hash chain across both task IDs; sort by the
        # ledger sequence so the entries arrive in chain order
        # (receive-iris, emit-atlas, receive-atlas, emit-iris).
        marius_entries = sorted(
            [*marius_entries_t1, *marius_entries_t2], key=lambda r: r.sequence
        )
        atlas_entries = sorted(
            atlas_ledger.get_by_task(task_id_2), key=lambda r: r.sequence
        )

        # Use the residue's own ``sequence`` field, not the enumerate index.
        # The two coincide for contiguous ledgers but the spec assertion
        # (#9 marius_ledger_hash_chain) verifies the real ledger sequences;
        # passing enumerate would silently coerce mismatches.
        iris_dtos = [_residue_to_dto(r, r.sequence) for r in iris_entries]
        marius_dtos = [_residue_to_dto(r, r.sequence) for r in marius_entries]
        atlas_dtos = [_residue_to_dto(r, r.sequence) for r in atlas_entries]

        # -- Bilateral exchange DTOs --------------------------------
        # Exchange A — Iris→Marius proposal (part of task_id_1)
        #   proposal_hash : Marius' seq-0 receive == Iris' seq-0 emit
        #   acceptance_hash: re-used on the C row; here we record the
        #                    proposal hash twice as 'no acceptance yet'.
        # Per the design, we model A and C as their own exchanges with
        # distinct labels — both share task_id_1.
        iris_emit_hash = iris_dtos[0].payload_hash
        marius_receive_iris_hash = marius_dtos[0].payload_hash
        marius_emit_iris_hash = marius_dtos[3].payload_hash
        iris_receive_marius_hash = iris_dtos[1].payload_hash
        marius_emit_atlas_hash = marius_dtos[1].payload_hash
        atlas_receive_hash = atlas_dtos[0].payload_hash
        atlas_emit_hash = atlas_dtos[1].payload_hash
        marius_receive_atlas_hash = marius_dtos[2].payload_hash

        exchange_iris_marius_proposal = BilateralExchangeDTO(
            exchange_label="iris-to-marius",
            initiator=IRIS,
            responder=MARIUS,
            proposal_payload_hash=iris_emit_hash,
            # The acceptance for this exchange is the Iris-side receive of
            # Marius' final response; identical to exchange C's acceptance
            # hash. Both rows are exposed so the UI can render the three
            # tessera-fits independently.
            acceptance_payload_hash=iris_receive_marius_hash,
            task_id=task_id_1,
        )

        exchange_marius_atlas = BilateralExchangeDTO(
            exchange_label="marius-to-atlas",
            initiator=MARIUS,
            responder=ATLAS,
            proposal_payload_hash=marius_emit_atlas_hash,
            acceptance_payload_hash=atlas_emit_hash,
            task_id=task_id_2,
        )

        exchange_marius_iris_acceptance = BilateralExchangeDTO(
            exchange_label="marius-accepts-iris",
            initiator=MARIUS,
            responder=IRIS,
            # Symmetric framing for the UI: the "proposal_payload_hash"
            # slot carries Iris' original request hash; the
            # "acceptance_payload_hash" slot carries Marius' acceptance
            # hash. Same task_id_1 as exchange A.
            proposal_payload_hash=marius_receive_iris_hash,
            acceptance_payload_hash=marius_emit_iris_hash,
            task_id=task_id_1,
        )

        # -- Reasoner trace -----------------------------------------
        reasoner_trace = ReasonerTraceDTO(
            requested_slot=iris_rich_proposal["candidates"][0],
            blocking_event_title=proposal.blocked_event_title,
            blocking_event_attendee=ATLAS,
            proposed_new_slot=proposal.new_slot,
            reason=proposal.reason,
        )

        # -- Calendar deltas (computed; no actual writes) -----------
        # Marius: move synthetic-project-sync from 14:00 to 16:00.
        marius_after = _calendar_after_move(
            MARIUS_SYNTHETIC_CALENDAR,
            moved_title=proposal.blocked_event_title,
            new_slot=proposal.new_slot,
        )
        # Iris: gains the new Iris↔Marius meeting at 14:00.
        new_iris_meeting = CalendarEvent(
            slot_start=iris_rich_proposal["candidates"][0],
            duration_minutes=int(iris_rich_proposal["duration_minutes"]),
            title="synthetic-iris-marius-meeting",
            attendee_principal_ids=[MARIUS],
        )
        iris_after = _calendar_after_add(
            IRIS_SYNTHETIC_CALENDAR, new_event=new_iris_meeting
        )
        # Atlas: starts empty (Atlas' internal calendar is not modeled in
        # v0); gains the rescheduled synthetic-project-sync at 16:00.
        atlas_before: list[CalendarEvent] = []
        atlas_after = _calendar_after_add(
            atlas_before,
            new_event=CalendarEvent(
                slot_start=proposal.new_slot,
                duration_minutes=45,
                title=proposal.blocked_event_title,
                attendee_principal_ids=[MARIUS],
            ),
        )

        iris_policy_doc = iris_policy_signed.doc.to_signing_payload()

        # -- Close stores + ledgers before tempdir teardown ---------
        iris_store.close()
        marius_store.close()
        atlas_store.close()
        iris_ledger.close()
        marius_ledger.close()
        atlas_ledger.close()

        duration_ms = int((time.monotonic() - started) * 1000)

        return CascadingResult(
            iris_principal_id=IRIS,
            marius_principal_id=MARIUS,
            atlas_principal_id=ATLAS,
            reasoner_trace=reasoner_trace,
            exchange_iris_marius_proposal=exchange_iris_marius_proposal,
            exchange_marius_atlas=exchange_marius_atlas,
            exchange_marius_iris_acceptance=exchange_marius_iris_acceptance,
            iris_scoped_proposal=iris_scoped_proposal_expected,
            marius_reschedule_proposal=dict(captured_marius_reschedule_proposal),
            atlas_acceptance_payload=dict(captured_atlas_acceptance),
            marius_acceptance_to_iris=dict(captured_marius_acceptance_to_iris),
            iris_ledger=iris_dtos,
            marius_ledger=marius_dtos,
            atlas_ledger=atlas_dtos,
            iris_calendar=CalendarStateDTO(
                principal_id=IRIS,
                before=_events_to_dtos(IRIS_SYNTHETIC_CALENDAR),
                after=_events_to_dtos(iris_after),
            ),
            marius_calendar=CalendarStateDTO(
                principal_id=MARIUS,
                before=_events_to_dtos(MARIUS_SYNTHETIC_CALENDAR),
                after=_events_to_dtos(marius_after),
            ),
            atlas_calendar=CalendarStateDTO(
                principal_id=ATLAS,
                before=_events_to_dtos(atlas_before),
                after=_events_to_dtos(atlas_after),
            ),
            policy_doc_iris=iris_policy_doc,
            duration_ms=duration_ms,
        )
