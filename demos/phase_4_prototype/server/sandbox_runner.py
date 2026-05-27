"""Thin sandbox runner that wires MeshyCal Delegations together.

This module is intentionally small. All the trust + domain logic lives
in ``meshycal.*`` — CalendarObject owns calendar state, SchedulingAgent
wraps it and talks to Mesherra. This runner just:

  1. Translates a sandbox API request (SandboxRunResult shapes) into
     two MeshyCal Delegations (Calendar + Agent for each principal).
  2. Wires the two agents to a shared in-process Directory.
  3. Asks the sender's agent to propose to the recipient's agent.
  4. Reshapes the result back into a SandboxRunResult the UI can render.

Per CLAUDE.md Rule 7: this is hand-rolled for MeshyCal specifically.
When a second Delegation exists, a shared "two-party negotiation runner"
helper can be extracted from this + scenarios.run_two_party.
"""

from __future__ import annotations

import logging
import socket
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mesherra.crypto.primitives import Signer, canonical_json, content_hash
from mesherra.identity import StaticDirectoryClient
from mesherra.object.store import ObjectStore
from mesherra.policy import PolicyStore, sign_policy_doc
from mesherra.provenance.ledger import ProvenanceLedger

from meshycal import (
    CalendarEvent,
    CalendarObject,
    SchedulingAgent,
    build_policy_doc,
    build_reasoner,
    reasoner_label,
)
from meshycal.policy_template import PROPOSAL_SCHEMA

from .sandbox_models import (
    SandboxCalendarDelta,
    SandboxExchange,
    SandboxPrincipal,
    SandboxRequestSpec,
    SandboxResidue,
    SandboxRunResult,
)

logger = logging.getLogger(__name__)


class SandboxRunnerError(Exception):
    """Raised when a sandbox run can't proceed for a structured reason."""


# --- Helpers --------------------------------------------------------------


def _slot_key(principal_id: str, time_hhmm: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in principal_id.lower()).strip("-")
    return f"{slug}-{time_hhmm.replace(':', '')}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "T" in s and len(s.split("T")[1]) == 5:
        s = s + ":00+00:00"
    elif "+" not in s and len(s) <= 19:
        s = s + "+00:00"
    return datetime.fromisoformat(s)


def _hhmm_from_iso(iso: str) -> str:
    dt = _parse_iso(iso)
    return f"{dt.hour:02d}:{dt.minute:02d}"


def _principal_to_calendar(principal: SandboxPrincipal) -> CalendarObject:
    """Lift the SandboxPrincipal's calendar list into a CalendarObject."""
    events = [
        CalendarEvent(
            time=e.time,
            duration=e.duration,
            title=e.title,
            attendees=e.attendees,
            is_blocking=e.is_blocking,
        )
        for e in principal.calendar
    ]
    return CalendarObject(
        owner_principal_id=principal.id,
        events=events,
        timezone="UTC",
    )


def _build_agent(
    *,
    principal: SandboxPrincipal,
    signer: Signer,
    directory: StaticDirectoryClient,
    td: Path,
    api_key: str | None,
    label: str,
) -> SchedulingAgent:
    """Construct a SchedulingAgent for one principal: PolicyDoc, signed,
    saved; per-principal Ledger; per-principal SDK; configured reasoner."""
    calendar = _principal_to_calendar(principal)

    policy_doc = build_policy_doc(
        principal_id=principal.id,
        outbound_allow=list(principal.policy.outbound_allow),
        outbound_block=list(principal.policy.outbound_block),
        inbound_allow=list(principal.policy.inbound_allow),
    )
    policy_store = PolicyStore(
        db_path=td / f"{label}_policy.sqlite",
        principal_id=principal.id,
        public_key_b64=signer.public_key_b64(),
    )
    policy_store.save_signed(sign_policy_doc(doc=policy_doc, signer=signer))

    ledger = ProvenanceLedger(
        db_path=td / f"{label}_ledger.sqlite",
        ledger_owner=principal.id,
    )

    object_store = ObjectStore(
        db_path=td / f"{label}_objects.sqlite",
        owner_principal_id=principal.id,
    )

    reasoner = build_reasoner(
        provider=principal.reasoner.provider,
        model=principal.reasoner.model,
        api_key=api_key,
        base_url=principal.reasoner.base_url or None,
    )

    return SchedulingAgent(
        calendar=calendar,
        signer=signer,
        policy_store=policy_store,
        ledger=ledger,
        object_store=object_store,
        directory=directory,
        reasoner=reasoner,
        display_name=principal.display_name,
        # Sandbox: in-process simulation that doesn't start the sender's
        # listener. Opt in to the legacy "skip LIVE promotion" fallback;
        # the keystone MeetingObject flow is exercised by
        # meshycal/tests/test_meeting_object_roundtrip.py which uses
        # real HTTP listeners on both sides.
        single_process_mode=True,
    )


def _strip_per_policy(rich: dict[str, Any], allow: list[str]) -> dict[str, Any]:
    """Mirror the airlock's strip locally so the orchestrator can surface
    rich and scoped payloads side-by-side without trusting in-process
    Mesherra state."""
    allowed = set(allow)
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


# --- The runner -----------------------------------------------------------


async def run_sandbox_two_party(
    *,
    sender: SandboxPrincipal,
    recipient: SandboxPrincipal,
    request: SandboxRequestSpec,
    api_keys: dict[str, str],
) -> SandboxRunResult:
    """Run a real 2-party MeshyCal negotiation between two sandbox principals.

    Generates fresh per-user Mesherra identities, builds a MeshyCal
    Delegation (CalendarObject + SchedulingAgent + signed PolicyDoc +
    Ledger) for each, wires them through a shared StaticDirectoryClient,
    fires the proposal, and returns a SandboxRunResult with real signed
    Residue entries on both sides.
    """
    if sender.id == recipient.id:
        raise SandboxRunnerError("sender and recipient must differ")

    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="meshycal-sandbox-") as td_str:
        td = Path(td_str)

        # 1. Per-user identities + shared Directory
        sender_signer = Signer.generate()
        recipient_signer = Signer.generate()
        directory = StaticDirectoryClient(
            {
                sender.id: sender_signer.public_key_b64(),
                recipient.id: recipient_signer.public_key_b64(),
            }
        )

        # 2. Two MeshyCal Delegations
        sender_agent = _build_agent(
            principal=sender,
            signer=sender_signer,
            directory=directory,
            td=td,
            api_key=api_keys.get(sender.id),
            label="sender",
        )
        recipient_agent = _build_agent(
            principal=recipient,
            signer=recipient_signer,
            directory=directory,
            td=td,
            api_key=api_keys.get(recipient.id),
            label="recipient",
        )

        # 3. Build candidates from the sender's free slots
        earliest = _parse_iso(request.earliest)
        latest = _parse_iso(request.latest)
        if earliest >= latest:
            raise SandboxRunnerError("earliest must be before latest")
        candidates = sender_agent.calendar.free_slots(
            earliest=earliest,
            latest=latest,
            duration_minutes=request.duration,
        )

        # Compute rich + scoped payloads the UI surfaces (the wire-true
        # scoped bytes come from Mesherra; this mirror is for the UI's
        # rich/scoped side-by-side panels).
        rich_payload = sender_agent.build_rich_payload(
            candidates=candidates,
            duration_minutes=request.duration,
        )
        scoped_expected = _strip_per_policy(
            rich_payload, list(sender.policy.outbound_allow)
        )
        rich_hash = content_hash(canonical_json(rich_payload))
        scoped_hash = content_hash(canonical_json(scoped_expected))

        # 4. Start recipient's listener + send proposal
        port = _free_port()
        recipient_handle = await recipient_agent.start_listener(host="127.0.0.1", port=port)
        try:
            send_result = await sender_agent.propose_meeting_to(
                peer_url=f"http://127.0.0.1:{port}/",
                peer_principal_id=recipient.id,
                candidates=candidates,
                duration_minutes=request.duration,
            )
        finally:
            await recipient_handle.stop()

        # 5. Build the RunResult from agent state + real Residue entries
        verdict = recipient_agent.last_verdict
        accepted = bool(verdict and verdict.accept and verdict.chosen_slot)

        acceptance_payload = (
            {
                "candidates": [verdict.chosen_slot],
                "duration_minutes": request.duration,
            }
            if verdict and verdict.chosen_slot
            else {"candidates": [], "duration_minutes": request.duration}
        )
        acceptance_hash = content_hash(canonical_json(acceptance_payload))

        sender_entries = sorted(
            sender_agent.ledger.get_by_task(send_result.task_id),
            key=lambda r: r.sequence,
        )
        recipient_entries = sorted(
            recipient_agent.ledger.get_by_task(send_result.task_id),
            key=lambda r: r.sequence,
        )

        sender_label = reasoner_label(
            provider=sender.reasoner.provider,
            model=sender.reasoner.model,
            api_key=api_keys.get(sender.id),
            base_url=sender.reasoner.base_url or None,
        )
        recipient_label = reasoner_label(
            provider=recipient.reasoner.provider,
            model=recipient.reasoner.model,
            api_key=api_keys.get(recipient.id),
            base_url=recipient.reasoner.base_url or None,
        )

        narrative = [
            f"{sender.display_name} asks their agent for a {request.duration}-minute meeting with {recipient.display_name}.",
            f"{sender.display_name}'s agent strips blocked fields per their privacy policy. Rich payload stays home.",
            f"The scoped payload crosses the wire to {recipient.display_name}'s agent.",
            f"{recipient.display_name}'s agent ({recipient_label}) evaluates the candidates against their CalendarObject.",
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

        deltas: list[SandboxCalendarDelta] = []
        if accepted and verdict and verdict.chosen_slot:
            hhmm = _hhmm_from_iso(verdict.chosen_slot)
            deltas.append(
                SandboxCalendarDelta(
                    principal_id=sender.id,
                    delta_type="add",
                    slot_id=_slot_key(sender.id, hhmm),
                    time=hhmm,
                    title=f"meeting with {recipient.display_name}",
                    attendees=f"signed · {request.duration} min",
                )
            )
            deltas.append(
                SandboxCalendarDelta(
                    principal_id=recipient.id,
                    delta_type="add",
                    slot_id=_slot_key(recipient.id, hhmm),
                    time=hhmm,
                    title=f"meeting with {sender.display_name}",
                    attendees=f"signed · {request.duration} min",
                )
            )

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
                recipient.id: [
                    _residue_to_dto(r, i) for i, r in enumerate(recipient_entries)
                ],
            },
            scoped_payloads={
                sender.id: rich_payload,
                recipient.id: scoped_expected,
            },
            rich_payload_hash=rich_hash,
            scoped_payload_hash=scoped_hash,
            calendar_deltas=deltas,
            narrative_beats=narrative,
            reasoner_trace=None,
            duration_ms=int((time.monotonic() - started) * 1000),
            reasoner_summary={
                sender.id: sender_label,
                recipient.id: recipient_label,
            },
        )

        # 6. Cleanup — release sqlite handles before tempdir teardown.
        sender_agent.close()
        recipient_agent.close()
        return result
