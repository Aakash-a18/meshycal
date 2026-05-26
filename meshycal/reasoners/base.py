"""Reasoner Protocol + verdict shape.

Every reasoner (scripted, anthropic, openai, ...) takes the same
arguments and returns the same ProposalVerdict. The SchedulingAgent
doesn't know or care which one is plugged in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from meshycal.calendar_object import CalendarObject


@dataclass(frozen=True)
class ProposalVerdict:
    """The reasoner's decision about an incoming proposal."""

    accept: bool
    chosen_slot: str | None
    reason: str


@runtime_checkable
class SchedulingReasoner(Protocol):
    """How a SchedulingAgent decides what to do with an incoming proposal.

    Returning ``accept=False`` means "no candidate fits"; the agent will
    send a rejection back. Returning ``accept=True`` requires
    chosen_slot to be one of the exact strings in ``candidate_slots``;
    LLM-backed implementations must guard against hallucinated slots.
    """

    async def evaluate_proposal(
        self,
        *,
        candidate_slots: list[str],
        duration_minutes: int,
        my_calendar: "CalendarObject",
        my_display_name: str,
    ) -> ProposalVerdict:
        ...
