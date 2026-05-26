"""MeshyCal's default policy template.

The plain-English privacy toggles a user sees in the editor (in the
sandbox UI, but also in any future MeshyCal client) collapse into a
Mesherra PolicyDoc with two rules: one OUTBOUND (controls what the
sender's airlock will let across the wire) and one INBOUND (controls
what the recipient will accept).

The defaults match the original Phase 3 MeshyCal demo: share enough to
schedule (candidates + duration + tz hints), block what would leak
private context (existing meeting titles, attendee emails).
"""

from __future__ import annotations

from datetime import UTC, datetime

from mesherra.policy import Direction, Match, PolicyDoc, Rule

PROPOSAL_SCHEMA = "meshycal.scheduling/proposal-v1"

DEFAULT_OUTBOUND_ALLOW: list[str] = [
    "candidates",
    "duration_minutes",
    "constraint_hints",
]
DEFAULT_OUTBOUND_BLOCK: list[str] = [
    "calendar_titles",
    "attendee_emails",
]
DEFAULT_INBOUND_ALLOW: list[str] = [
    "candidates",
    "duration_minutes",
    "constraint_hints",
]

MAX_CANDIDATES = 5


def build_policy_doc(
    *,
    principal_id: str,
    outbound_allow: list[str] | None = None,
    outbound_block: list[str] | None = None,
    inbound_allow: list[str] | None = None,
    max_candidates: int = MAX_CANDIDATES,
) -> PolicyDoc:
    """Construct a MeshyCal PolicyDoc bound to principal_id.

    None for any field means "use the default template list". Pass [] to
    explicitly empty a list."""
    return PolicyDoc(
        principal_id=principal_id,
        version=1,
        issued_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rules=[
            Rule(
                match=Match(schema=PROPOSAL_SCHEMA, direction=Direction.OUTBOUND),
                outbound_allow=(
                    list(outbound_allow)
                    if outbound_allow is not None
                    else list(DEFAULT_OUTBOUND_ALLOW)
                ),
                outbound_block=(
                    list(outbound_block)
                    if outbound_block is not None
                    else list(DEFAULT_OUTBOUND_BLOCK)
                ),
                max_array_size={"candidates": max_candidates},
            ),
            Rule(
                match=Match(schema=PROPOSAL_SCHEMA, direction=Direction.INBOUND),
                inbound_allow=(
                    list(inbound_allow)
                    if inbound_allow is not None
                    else list(DEFAULT_INBOUND_ALLOW)
                ),
            ),
        ],
    )
