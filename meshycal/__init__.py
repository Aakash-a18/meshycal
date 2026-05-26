"""MeshyCal — the first Delegation on Mesherra.

The trust layer (identity, signed wire format, scoped disclosure, Residue
ledger) lives in mesherra. MeshyCal is the domain layer on top: calendars
as owner-bound Objects, scheduling agents that wrap them, and the policy
template + reasoners that make a scheduling-specific agent possible.

A MeshyCal Delegation for one user is the triple:

    (CalendarObject, SchedulingAgent, PolicyDoc)

  - CalendarObject owns the calendar state (events, timezone, version)
    and exposes a canonical_hash() so an agent can attest "this is what
    my calendar said when I made this proposal."
  - SchedulingAgent wraps the CalendarObject and uses Mesherra primitives
    to sign and send proposals, evaluate incoming ones (via a Reasoner),
    and book accepted meetings back onto the calendar.
  - PolicyDoc declares what the agent is allowed to share on the wire.
    The Mesherra airlock enforces it.

Per CLAUDE.md Rule 7: this code is hand-crafted for MeshyCal specifically.
Reusable Delegation helpers are deferred until a second Delegation exists
to inform them.
"""

from meshycal.calendar_object import CalendarEvent, CalendarObject
from meshycal.policy_template import (
    DEFAULT_INBOUND_ALLOW,
    DEFAULT_OUTBOUND_ALLOW,
    DEFAULT_OUTBOUND_BLOCK,
    PROPOSAL_SCHEMA,
    build_policy_doc,
)
from meshycal.reasoners import (
    AnthropicReasoner,
    ProposalVerdict,
    SchedulingReasoner,
    ScriptedReasoner,
    build_reasoner,
    reasoner_label,
)
from meshycal.scheduling_agent import SchedulingAgent

__all__ = [
    "CalendarEvent",
    "CalendarObject",
    "SchedulingAgent",
    "SchedulingReasoner",
    "ScriptedReasoner",
    "AnthropicReasoner",
    "ProposalVerdict",
    "build_reasoner",
    "reasoner_label",
    "build_policy_doc",
    "PROPOSAL_SCHEMA",
    "DEFAULT_OUTBOUND_ALLOW",
    "DEFAULT_OUTBOUND_BLOCK",
    "DEFAULT_INBOUND_ALLOW",
]
