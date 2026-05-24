"""Agent A — the initiating scheduling agent.

Per SPEC §6 (Agent A — pre-send / on response):

1. Read its own busy calendar fixture.
2. Compute three free candidate slots in the next 7 days (deterministic;
   no LLM, no randomness) via :func:`slot_picker.find_free_candidates`.
3. Build a proposal payload conforming to ``meshycal.scheduling/proposal-v1``.
4. Send it to Agent B's listener via the Mesherra SDK. The SDK signs the
   SendClaim pre-send and verifies B's SendClaim on the response, writes
   both residues, and returns the outcome.

The SDK is the only Mesherra surface touched here; trust-layer concerns
(signing, verification, hash-chain integrity) live behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mesherra import Mesherra
from mesherra.gateways.outbound import OutboundResult
from mesherra.models.primitives import Operation

from slot_picker import find_free_candidates
from synthetic_calendar import read_calendar

PAYLOAD_SCHEMA = "meshycal.scheduling/proposal-v1"


@dataclass(frozen=True)
class RunAgentAResult:
    """What ``run_agent_a`` returns.

    Carries both A's proposal payload (the bytes A signed and sent) and
    the OutboundGateway result (B's response + the now-known task_id).
    The orchestrator needs both to write payload sidecars for the cold-
    reload semantic assertion (SPEC §5 #13) — the residue only stores
    payload_hash, so reconstructing "candidate X was in the proposal"
    post-process requires the orchestrator to persist the original bytes
    somewhere on disk.
    """

    proposal: dict[str, Any]
    outbound: OutboundResult


async def run_agent_a(
    *,
    mesherra: Mesherra,
    peer_url: str,
    peer_principal_id: str,
    calendar_path: Path,
    duration_minutes: int = 30,
    num_candidates: int = 3,
    reference_time: datetime | None = None,
) -> RunAgentAResult:
    """Drive Agent A through one full initiate→response cycle.

    Args:
        mesherra: A's wired Mesherra SDK handle.
        peer_url: URL of B's A2A listener (e.g., ``http://127.0.0.1:8002/``).
        peer_principal_id: B's principal id; must be in A's public-key directory.
        calendar_path: Path to A's synthetic calendar JSON fixture.
        duration_minutes: Meeting length to propose.
        num_candidates: How many candidate slots to include.
        reference_time: UTC anchor for "now". Default ``datetime.now(timezone.utc)``.

    Returns:
        A :class:`RunAgentAResult` carrying the proposal payload A built
        and the :class:`OutboundResult` (B's response + assigned task_id).

    Raises:
        ValueError: A's calendar fixture is empty of free slots in the
            7-day lookahead window — Phase 1 demo terminates rather than
            extending lookahead.
    """
    now = reference_time or datetime.now(timezone.utc)

    calendar = read_calendar(calendar_path)
    candidates = find_free_candidates(
        busy=calendar["busy"],
        duration_minutes=duration_minutes,
        reference_time=now,
        num_candidates=num_candidates,
    )
    if not candidates:
        raise ValueError(
            f"Agent A could not find any free {duration_minutes}-minute slot "
            f"in the 7-day window after {now.isoformat()}. Phase 1 demo "
            "terminates here — a real agent would extend lookahead or "
            "renegotiate scope."
        )

    # Phase 3: A's *internal* proposal payload also carries calendar
    # titles, attendee emails, and constraint hints — the kind of context
    # a real scheduling agent would have access to internally. The
    # default MeshyCal outbound policy blocks calendar_titles and
    # attendee_emails; only candidates, duration_minutes, and
    # constraint_hints cross the wire. These literals stand in for what
    # a real agent would derive from its full calendar context.
    proposal: dict[str, Any] = {
        "candidates": candidates,
        "duration_minutes": duration_minutes,
        "calendar_titles": [
            "synthetic-team-sync",
            "synthetic-1-on-1",
        ],
        "attendee_emails": [
            "synthetic-attendee@example.invalid",
        ],
        "constraint_hints": {
            "tz": "UTC",
            "preferred_window": {"start_hour": 9, "end_hour": 17},
        },
    }
    outbound = await mesherra.send_to(
        peer_url=peer_url,
        peer_principal_id=peer_principal_id,
        payload=proposal,
        payload_schema=PAYLOAD_SCHEMA,
        operation=Operation.PROPOSAL,
    )
    return RunAgentAResult(proposal=proposal, outbound=outbound)
