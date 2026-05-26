"""Pluggable reasoners that decide what a SchedulingAgent does with an
incoming proposal.

Scripted by default (deterministic, no network). Anthropic-backed when
the user supplies a key. The protocol is async so LLM-backed
implementations can do their network call without blocking the agent's
inbound handler.
"""

from meshycal.reasoners.anthropic import AnthropicReasoner
from meshycal.reasoners.base import ProposalVerdict, SchedulingReasoner
from meshycal.reasoners.factory import build_reasoner, reasoner_label
from meshycal.reasoners.scripted import ScriptedReasoner

__all__ = [
    "AnthropicReasoner",
    "ProposalVerdict",
    "SchedulingReasoner",
    "ScriptedReasoner",
    "build_reasoner",
    "reasoner_label",
]
