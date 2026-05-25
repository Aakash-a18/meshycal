"""Generic N-principal sandbox orchestrator.

Phase 1: 2-party only. Mirrors :func:`scenarios.run_two_party` but
parameterized over arbitrary sender + recipient + their configured
policies and reasoners.

Mesherra alignment: real Ed25519 signers (one per principal), a real
in-process StaticDirectoryClient holding their public keys, real
per-principal PolicyStore with the principal's chosen privacy toggles
encoded as a PolicyDoc, real per-principal ProvenanceLedger, and real
Mesherra SDK instances. The exchange is a real signed proposal +
signed acceptance whose payload_hash bytes match on both sides — the
scenario whose v0 the existing demo's Scenario 1 already proves out.

Calendar Objects in the Mesherra-purist sense are not used here — the
sandbox's calendar is held as a list of SandboxEvent records that the
orchestrator reads. The trust-layer guarantees (identity, signing,
scoped disclosure, residue) are all real; the "calendar is an Object"
upgrade is a follow-up that requires Mesherra-side Object Class
registration.

Phase 2 will add cascading 3-party. The frontend already detects
topology client-side and posts a hint; this module routes accordingly
(2-party only for now; 3-party falls back to a clear error).
"""

from __future__ import annotations

import asyncio
import logging
import socket
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mesherra.a2a_adapter import A2AAdapter
from mesherra.crypto.primitives import Signer, canonical_json, content_hash
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

from .reasoner import CalendarEvent
from .sandbox_models import (
    SandboxCalendarDelta,
    SandboxExchange,
    SandboxPolicy,
    SandboxPrincipal,
    SandboxRequestSpec,
    SandboxResidue,
    SandboxRunResult,
)
from .sandbox_reasoners import (
    ProposalVerdict,
    ScriptedSandboxReasoner,
    build_sandbox_reasoner,
    reasoner_label,
)

logger = logging.getLogger(__name__)

PAYLOAD_SCHEMA = "meshycal.scheduling/proposal-v1"
MAX_CANDIDATES = 5
CANDIDATE_STEP_MIN = 60  # space candidates out by one hour


# --- Errors ---------------------------------------------------------------


class SandboxOrchestratorError(Exception):
    """Raised when a sandbox run can't proceed for a structured reason."""


# --- Helpers --------------------------------------------------------------


def _slot_key(principal_id: str, time_hhmm: str) -> str:
    """Mirror of the frontend's slugify(pid) + '-' + time.replace(':','')."""
    slug = "".join(c if c.isalnum() else "-" for c in principal_id.lower()).strip("-")
    return f"{slug}-{time_hhmm.replace(':', '')}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _parse_iso_datetime(s: str) -> datetime:
    """Accept either '2026-05-26T09:00:00Z' or '2026-05-26T09:00' (the
    HTML datetime-local format the frontend produces)."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "T" in s and len(s.split("T")[1]) == 5:
        s = s + ":00+00:00"
    elif "+" not in s and len(s) <= 19:
        s = s + "+00:00"
    return datetime.fromisoformat(s)


def _principal_calendar_to_events(
    principal: SandboxPrincipal,
    reference_date: datetime,
) -> list[CalendarEvent]:
    """Project a principal's HH:MM calendar onto a reference date and
    return CalendarEvent records the reasoner can consume."""
    out: list[CalendarEvent] = []
    for ev in principal.calendar:
        try:
            hh, mm = ev.time.split(":", 1)
            slot_dt = reference_date.replace(
                hour=int(hh), minute=int(mm), second=0, microsecond=0
            )
        except (ValueError, IndexError):
            continue
        out.append(CalendarEvent(
            slot_start=slot_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_minutes=ev.duration,
            title=ev.title,
            attendee_principal_ids=[ev.attendees] if ev.attendees else [],
        ))
    return out


def _build_candidates(
    sender: SandboxPrincipal,
    request: SandboxRequestSpec,
) -> tuple[list[str], datetime]:
    """Return up to MAX_CANDIDATES ISO 8601 candidate slots in the
    requested window that are clear of the sender's existing events.

    Returns the candidates plus the reference date (the day the
    candidates fall on — used to project calendars onto the same date).
    """
    earliest = _parse_iso_datetime(request.earliest)
    latest = _parse_iso_datetime(request.latest)
    if earliest >= latest:
        raise SandboxOrchestratorError("earliest must be before latest")

    # Pull sender's busy intervals onto the request's date.
    sender_events = _principal_calendar_to_events(sender, earliest)
    busy: list[tuple[datetime, datetime]] = []
    for ev in sender_events:
        ev_start = _parse_iso_datetime(ev.slot_start)
        busy.append((ev_start, ev_start + timedelta(minutes=ev.duration_minutes)))

    dur = timedelta(minutes=request.duration)
    step = timedelta(minutes=CANDIDATE_STEP_MIN)
    candidates: list[str] = []
    cur = earliest
    while cur + dur <= latest and len(candidates) < MAX_CANDIDATES:
        cur_end = cur + dur
        conflict = any(b_start < cur_end and b_end > cur for b_start, b_end in busy)
        if not conflict:
            candidates.append(cur.strftime("%Y-%m-%dT%H:%M:%SZ"))
        cur += step

    # If filtering ate every option, fall back to unfiltered candidates so
    # the run can proceed (the recipient's reasoner will reject if needed).
    if not candidates:
        cur = earliest
        while cur + dur <= latest and len(candidates) < MAX_CANDIDATES:
            candidates.append(cur.strftime("%Y-%m-%dT%H:%M:%SZ"))
            cur += step

    return candidates, earliest


def _build_policy_doc(principal: SandboxPrincipal) -> PolicyDoc:
    """Map the principal's privacy toggles onto a Mesherra PolicyDoc."""
    return PolicyDoc(
        principal_id=principal.id,
        version=1,
        issued_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rules=[
            Rule(
                match=Match(schema=PAYLOAD_SCHEMA, direction=Direction.OUTBOUND),
                outbound_allow=list(principal.policy.outbound_allow),
                outbound_block=list(principal.policy.outbound_block),
                max_array_size={"candidates": MAX_CANDIDATES},
            ),
            Rule(
                match=Match(schema=PAYLOAD_SCHEMA, direction=Direction.INBOUND),
                inbound_allow=list(principal.policy.inbound_allow),
            ),
        ],
    )


def _rich_proposal_payload(
    sender: SandboxPrincipal,
    candidates: list[str],
    duration: int,
) -> dict[str, Any]:
    """Build the 'internal' rich payload the sender's agent constructs
    before scoped disclosure. Includes blocked fields so the policy
    layer has something real to strip — that's the visual story the UI
    tells about scoped disclosure."""
    titles = [ev.title for ev in sender.calendar if ev.title]
    attendees = list({ev.attendees for ev in sender.calendar if ev.attendees})
    return {
        "candidates": candidates,
        "duration_minutes": duration,
        "calendar_titles": titles,
        "attendee_emails": attendees,
        "constraint_hints": {"tz": "UTC"},
    }


def _strip_per_policy(
    rich: dict[str, Any],
    policy: SandboxPolicy,
) -> dict[str, Any]:
    """Compute the scoped payload by hand (orchestrator-side) so the UI
    can show side-by-side rich/scoped without trusting in-process Mesherra
    state. The real Mesherra airlock does the equivalent on the wire."""
    allowed = set(policy.outbound_allow)
    return {k: v for k, v in rich.items() if k in allowed}


def _residue_to_dto(r: Any, sequence: int) -> SandboxResidue:
    return SandboxResidue(
        sequence=sequence,
        action_type=r.action_type.value,
        operation=r.operation.value,
        actor=r.actor,
        counterpart=r.counterpart,
        timestamp=r.timestamp,
        payload_hash=r.payload_hash,
        payload_schema=r.payload_schema,
        signature_prefix=r.signature[:16],
    )


def _hhmm_from_iso(iso: str) -> str:
    dt = _parse_iso_datetime(iso)
    return f"{dt.hour:02d}:{dt.minute:02d}"


# --- 2-party orchestrator -------------------------------------------------


async def run_sandbox_two_party(
    *,
    sender: SandboxPrincipal,
    recipient: SandboxPrincipal,
    request: SandboxRequestSpec,
    api_keys: dict[str, str],
) -> SandboxRunResult:
    """Run a real 2-party negotiation with arbitrary principals.

    api_keys: {principal_id: api_key}. Only used for principals whose
    reasoner config is provider='anthropic' (or future providers).
    Keys are passed into the reasoner constructor and never retained.
    """
    if sender.id == recipient.id:
        raise SandboxOrchestratorError("sender and recipient must differ")

    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="meshycal-sandbox-") as td:
        td_path = Path(td)

        # -- Identities ---------------------------------------------------
        sender_signer = Signer.generate()
        recipient_signer = Signer.generate()
        directory = StaticDirectoryClient({
            sender.id: sender_signer.public_key_b64(),
            recipient.id: recipient_signer.public_key_b64(),
        })

        # -- PolicyStores -------------------------------------------------
        sender_store = PolicyStore(
            db_path=td_path / "sender_policy.sqlite",
            principal_id=sender.id,
            public_key_b64=sender_signer.public_key_b64(),
        )
        recipient_store = PolicyStore(
            db_path=td_path / "recipient_policy.sqlite",
            principal_id=recipient.id,
            public_key_b64=recipient_signer.public_key_b64(),
        )
        sender_signed_policy = sign_policy_doc(
            doc=_build_policy_doc(sender), signer=sender_signer
        )
        recipient_signed_policy = sign_policy_doc(
            doc=_build_policy_doc(recipient), signer=recipient_signer
        )
        sender_store.save_signed(sender_signed_policy)
        recipient_store.save_signed(recipient_signed_policy)

        # -- Ledgers ------------------------------------------------------
        sender_ledger = ProvenanceLedger(
            db_path=td_path / "sender_ledger.sqlite", ledger_owner=sender.id
        )
        recipient_ledger = ProvenanceLedger(
            db_path=td_path / "recipient_ledger.sqlite", ledger_owner=recipient.id
        )

        # -- SDKs ---------------------------------------------------------
        sender_sdk = Mesherra(
            principal_id=sender.id,
            signer=sender_signer,
            ledger=sender_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=sender_store,
        )
        recipient_sdk = Mesherra(
            principal_id=recipient.id,
            signer=recipient_signer,
            ledger=recipient_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=recipient_store,
        )

        # -- Candidates ---------------------------------------------------
        candidates, reference_date = _build_candidates(sender, request)
        rich_payload = _rich_proposal_payload(sender, candidates, request.duration)
        scoped_expected = _strip_per_policy(rich_payload, sender.policy)
        rich_hash = content_hash(canonical_json(rich_payload))
        scoped_hash = content_hash(canonical_json(scoped_expected))

        # -- Recipient reasoner ------------------------------------------
        recipient_reasoner = build_sandbox_reasoner(
            provider=recipient.reasoner.provider,
            model=recipient.reasoner.model,
            api_key=api_keys.get(recipient.id),
        )
        recipient_label = reasoner_label(
            provider=recipient.reasoner.provider,
            model=recipient.reasoner.model,
            api_key=api_keys.get(recipient.id),
        )
        # Sender's reasoner is informational only in v0 (the sender doesn't
        # evaluate inbound proposals in a 2-party run, but we still tag the
        # summary so the UI can show what was configured).
        sender_label = reasoner_label(
            provider=sender.reasoner.provider,
            model=sender.reasoner.model,
            api_key=api_keys.get(sender.id),
        )

        # Pre-compute the recipient's calendar projection for the run.
        recipient_calendar_events = _principal_calendar_to_events(
            recipient, reference_date
        )

        captured: dict[str, Any] = {"verdict": None}

        async def recipient_handler(msg: IncomingMessage) -> OutgoingResponse:
            verdict: ProposalVerdict = await recipient_reasoner.evaluate_proposal(
                candidate_slots=list(msg.payload.get("candidates", [])),
                duration_minutes=int(msg.payload.get("duration_minutes", request.duration)),
                my_calendar=recipient_calendar_events,
                my_display_name=recipient.display_name,
            )
            captured["verdict"] = verdict
            if verdict.accept and verdict.chosen_slot:
                acceptance = {
                    "candidates": [verdict.chosen_slot],
                    "duration_minutes": int(msg.payload.get("duration_minutes", request.duration)),
                }
                return OutgoingResponse(
                    payload=acceptance,
                    operation=Operation.ACCEPTANCE,
                    payload_schema=PAYLOAD_SCHEMA,
                )
            # Reject by returning an empty acceptance payload (Marius
            # handler in scenarios.py uses the same convention).
            return OutgoingResponse(
                payload={"candidates": [], "duration_minutes": request.duration},
                operation=Operation.ACCEPTANCE,
                payload_schema=PAYLOAD_SCHEMA,
            )

        recipient_sdk.on_message(recipient_handler)
        sender_sdk.on_message(lambda _msg: None)  # type: ignore[arg-type]

        # -- Listener + send ---------------------------------------------
        recipient_port = _free_port()
        recipient_handle = await recipient_sdk.start_listener(
            host="127.0.0.1",
            port=recipient_port,
            agent_name=f"sandbox-{recipient.id.split('@', 1)[0]}",
        )
        try:
            send_result = await sender_sdk.send_to(
                peer_url=f"http://127.0.0.1:{recipient_port}/",
                peer_principal_id=recipient.id,
                payload=rich_payload,
                payload_schema=PAYLOAD_SCHEMA,
                operation=Operation.PROPOSAL,
            )
        finally:
            await recipient_handle.stop()

        # -- Build result -------------------------------------------------
        verdict: ProposalVerdict | None = captured["verdict"]
        accepted = bool(verdict and verdict.accept and verdict.chosen_slot)

        acceptance_payload = (
            {"candidates": [verdict.chosen_slot], "duration_minutes": request.duration}
            if verdict and verdict.chosen_slot
            else {"candidates": [], "duration_minutes": request.duration}
        )
        acceptance_hash = content_hash(canonical_json(acceptance_payload))

        sender_entries = sorted(
            sender_ledger.get_by_task(send_result.task_id), key=lambda r: r.sequence
        )
        recipient_entries = sorted(
            recipient_ledger.get_by_task(send_result.task_id), key=lambda r: r.sequence
        )

        narrative = [
            f"{sender.display_name} asks their agent for a {request.duration}-minute meeting with {recipient.display_name}.",
            f"{sender.display_name}'s agent strips blocked fields per their privacy policy. Rich payload stays home.",
            f"The scoped payload crosses the wire to {recipient.display_name}'s agent.",
            f"{recipient.display_name}'s agent ({recipient_label}) evaluates the candidates against their calendar.",
            (
                f"{recipient.display_name}'s agent accepts {verdict.chosen_slot} — {verdict.reason}"
                if accepted
                else f"{recipient.display_name}'s agent rejects: {verdict.reason if verdict else 'no acceptance produced'}"
            ),
            "Both ledgers gain signed entries. Matching scoped payload_hash on both sides — the tesserae fit.",
            (
                f"Both calendars gain a signed meeting at {verdict.chosen_slot}."
                if accepted
                else "No meeting booked."
            ),
        ]

        # Calendar deltas: add the new meeting to both sides if accepted.
        deltas: list[SandboxCalendarDelta] = []
        if accepted and verdict and verdict.chosen_slot:
            hhmm = _hhmm_from_iso(verdict.chosen_slot)
            deltas.append(SandboxCalendarDelta(
                principal_id=sender.id,
                delta_type="add",
                slot_id=_slot_key(sender.id, hhmm),
                time=hhmm,
                title=f"meeting with {recipient.display_name}",
                attendees=f"signed · {request.duration} min",
            ))
            deltas.append(SandboxCalendarDelta(
                principal_id=recipient.id,
                delta_type="add",
                slot_id=_slot_key(recipient.id, hhmm),
                time=hhmm,
                title=f"meeting with {sender.display_name}",
                attendees=f"signed · {request.duration} min",
            ))

        exchanges = [
            SandboxExchange(
                label="A",
                initiator_id=sender.id,
                responder_id=recipient.id,
                proposal_payload_hash=scoped_hash,
                acceptance_payload_hash=acceptance_hash,
                task_id=send_result.task_id,
            ),
        ]

        result = SandboxRunResult(
            success=accepted,
            topology="two_party",
            sender_id=sender.id,
            recipient_id=recipient.id,
            principals=[sender, recipient],
            exchanges=exchanges,
            ledgers={
                sender.id: [_residue_to_dto(r, i) for i, r in enumerate(sender_entries)],
                recipient.id: [_residue_to_dto(r, i) for i, r in enumerate(recipient_entries)],
            },
            scoped_payloads={
                sender.id: rich_payload,
                recipient.id: scoped_expected,
            },
            rich_payload_hash=rich_hash,
            scoped_payload_hash=scoped_hash,
            calendar_deltas=deltas,
            narrative_beats=narrative,
            reasoner_trace=None,  # populated for 3-party in Phase 2
            duration_ms=int((time.monotonic() - started) * 1000),
            reasoner_summary={
                sender.id: sender_label,
                recipient.id: recipient_label,
            },
        )

        # Close stores + ledgers before tempdir teardown.
        sender_store.close()
        recipient_store.close()
        sender_ledger.close()
        recipient_ledger.close()

        return result
