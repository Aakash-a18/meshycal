"""Agent B — the receiving scheduling agent.

Per SPEC §6 (Agent B — on receive):

1. Receive A's signed proposal via the Mesherra Inbound Gateway. By the
   time the consumer handler runs, the SendClaim signature has already
   been verified and B's receive Residue has been written; this module
   only sees the verified business-level payload.
2. Schema-validate the payload against ``meshycal.scheduling/proposal-v1``.
3. Pick the first candidate B is free for (:func:`slot_picker.pick_acceptable_slot`).
4. If a slot is acceptable: return an :class:`OutgoingResponse` with
   ``operation=ACCEPTANCE`` and a one-slot payload.
5. If none is acceptable: counter-propose with B's own free slots
   (operation=COUNTER). The Phase 1 demo's primary success path is
   acceptance; counter is exercised when calendars overlap.

The trust layer handles the rest (sign the response SendClaim, write B's
emit Residue, return the wire response).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from mesherra import Mesherra
from mesherra.gateways.inbound import IncomingMessage, OutgoingResponse
from mesherra.models.primitives import Operation

from slot_picker import find_free_candidates, pick_acceptable_slot
from synthetic_calendar import read_calendar

PAYLOAD_SCHEMA = "meshycal.scheduling/proposal-v1"
_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "proposal_v1.json"
_DEFAULT_NUM_COUNTER_CANDIDATES = 3


def _load_schema_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


async def configure_agent_b(
    *,
    mesherra: Mesherra,
    calendar_path: Path,
    listener_host: str,
    listener_port: int,
    reference_time: datetime | None = None,
) -> Any:
    """Wire B's consumer handler into Mesherra and start B's A2A listener.

    Args:
        mesherra: B's wired Mesherra SDK handle.
        calendar_path: Path to B's synthetic calendar JSON fixture.
        listener_host: Host to bind (e.g., ``127.0.0.1``).
        listener_port: Port to bind (e.g., ``8002``).
        reference_time: UTC anchor used when generating counter-proposal
            slots. Default ``datetime.now(timezone.utc)`` at handler-call time.

    Returns:
        The :class:`ListenerHandle` for graceful shutdown by the orchestrator.
    """
    validator = _load_schema_validator()
    calendar = read_calendar(calendar_path)
    busy = calendar["busy"]

    async def handler(message: IncomingMessage) -> OutgoingResponse | None:
        # Step 2: schema-validate the payload. The Inbound Gateway already
        # verified the SendClaim; this catches malformed business payloads.
        validator.validate(message.payload)

        duration = int(message.payload["duration_minutes"])
        candidates = list(message.payload["candidates"])

        picked = pick_acceptable_slot(
            busy=busy, candidates=candidates, duration_minutes=duration
        )
        if picked is not None:
            return OutgoingResponse(
                payload={"candidates": [picked], "duration_minutes": duration},
                operation=Operation.ACCEPTANCE,
                payload_schema=PAYLOAD_SCHEMA,
            )

        # No acceptable slot — counter-propose from B's own calendar.
        now = reference_time or datetime.now(timezone.utc)
        counter = find_free_candidates(
            busy=busy,
            duration_minutes=duration,
            reference_time=now,
            num_candidates=_DEFAULT_NUM_COUNTER_CANDIDATES,
        )
        if not counter:
            # B is fully booked too; surface that as a REJECTION rather than
            # silently dropping. A's orchestrator can choose how to handle it.
            return OutgoingResponse(
                payload={"candidates": candidates, "duration_minutes": duration},
                operation=Operation.REJECTION,
                payload_schema=PAYLOAD_SCHEMA,
            )
        return OutgoingResponse(
            payload={"candidates": counter, "duration_minutes": duration},
            operation=Operation.COUNTER,
            payload_schema=PAYLOAD_SCHEMA,
        )

    mesherra.on_message(handler)
    return await mesherra.start_listener(
        host=listener_host,
        port=listener_port,
        agent_name="meshycal-agent-b",
    )
