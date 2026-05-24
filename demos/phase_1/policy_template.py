"""MeshyCal default Policy template.

Per Mesherra demos/phase_3/SPEC.md §4. One template, used for both A and B
in the demo. The orchestrator wraps it per-principal at boot: stamps
``principal_id``, ``version=1``, ``issued_at=now``, then signs with that
principal's Ed25519 key and persists to that principal's PolicyStore.

The two rules express the demo's core proposition in plain English:

* Outbound: "Send candidates, duration, and timezone hints. Never send
  calendar titles or attendee emails. Cap candidate lists at 5."
* Inbound: "Accept the same fields. Refuse any payload whose schema or
  fields aren't on this list."

The template lives in MeshyCal (the Delegation), not in mesherra (the
trust layer). Per CLAUDE.md rule #1: domain-specific content stays in
consumers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mesherra.policy import Direction, Match, PolicyDoc, Rule

PAYLOAD_SCHEMA = "meshycal.scheduling/proposal-v1"


def build_default_meshycal_policy(*, principal_id: str) -> PolicyDoc:
    """Construct the per-principal default MeshyCal policy document.

    The doc is unsigned — the caller (orchestrator) signs it with the
    principal's Ed25519 key and persists the SignedPolicyDoc into the
    principal's :class:`PolicyStore`.
    """
    return PolicyDoc(
        principal_id=principal_id,
        version=1,
        issued_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rules=[
            Rule(
                match=Match(schema=PAYLOAD_SCHEMA, direction=Direction.OUTBOUND),
                outbound_allow=["candidates", "duration_minutes", "constraint_hints"],
                outbound_block=["calendar_titles", "attendee_emails"],
                max_array_size={"candidates": 5},
            ),
            Rule(
                match=Match(schema=PAYLOAD_SCHEMA, direction=Direction.INBOUND),
                inbound_allow=["candidates", "duration_minutes", "constraint_hints"],
            ),
        ],
    )
