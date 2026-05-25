"""Scheduling reasoner Protocol and scripted v0 implementation.

The Protocol is the seam between the v0 scripted demo and a future LLM-backed
implementation. Any object satisfying :class:`SchedulingReasoner` can be
injected into ``run_cascading()`` without changing the orchestrator.

LLM swap-in contract (documented, not enforced at runtime):
  An :class:`LLMReasoner` implementing this Protocol would:
  1. Accept an LLM client (Anthropic/OpenAI SDK instance) at construction.
  2. Build a structured prompt from the keyword arguments.
  3. Call the model with structured-output mode targeting
     :class:`RescheduleProposal`.
  4. Return :class:`RescheduleProposal` on success, ``None`` when no viable
     slot exists.
  The orchestrator never changes; the ``reason`` field is the model's
  verbatim natural-language explanation.

This module is deliberately stdlib-only (``dataclasses``, ``typing``).
No Mesherra imports — the reasoner is a pure domain helper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class CalendarEvent:
    """A synthetic calendar entry. No real user data."""

    slot_start: str  # ISO 8601 UTC
    duration_minutes: int
    title: str  # synthetic label
    attendee_principal_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RescheduleProposal:
    """What the reasoner proposes when it decides to move an existing meeting."""

    new_slot: str
    blocked_event_title: str
    reason: str


class SchedulingReasoner(Protocol):
    """Interface all reasoner implementations must satisfy.

    Pure function semantics; no I/O, no randomness, no side effects.
    Keyword-only arguments so new optional inputs are backward-compatible.
    """

    def propose_reschedule_target(
        self,
        *,
        requested_slot: str,
        requested_duration_minutes: int,
        current_calendar: list[CalendarEvent],
        atlas_principal_id: str,
        atlas_inferred_free_slots: list[str],
    ) -> RescheduleProposal | None:
        ...


class ScriptedReasoner:
    """Deterministic v0 implementation.

    Algorithm:
    1. Find the event in ``current_calendar`` at ``requested_slot``.
    2. Confirm ``atlas_principal_id`` is a co-attendee.
    3. Pick the first slot in ``atlas_inferred_free_slots`` that doesn't
       collide with ``current_calendar``.
    4. Return :class:`RescheduleProposal` with a formatted reason string.
    Returns ``None`` on any miss (no conflict; wrong attendee; no viable
    slot).
    """

    def propose_reschedule_target(
        self,
        *,
        requested_slot: str,
        requested_duration_minutes: int,
        current_calendar: list[CalendarEvent],
        atlas_principal_id: str,
        atlas_inferred_free_slots: list[str],
    ) -> RescheduleProposal | None:
        blocking: CalendarEvent | None = None
        for event in current_calendar:
            if event.slot_start == requested_slot:
                blocking = event
                break
        if blocking is None:
            return None
        if atlas_principal_id not in blocking.attendee_principal_ids:
            return None
        occupied = {e.slot_start for e in current_calendar}
        for candidate in atlas_inferred_free_slots:
            if candidate not in occupied:
                return RescheduleProposal(
                    new_slot=candidate,
                    blocked_event_title=blocking.title,
                    reason=(
                        f"busy at requested slot {requested_slot} with "
                        f"{atlas_principal_id} for \"{blocking.title}\"; "
                        f"proposing to move that meeting to {candidate}, "
                        "which is free on both calendars"
                    ),
                )
        return None


class LLMReasoner:
    """Future Phase 4.5 implementation. Documented seam only.

    Calling :meth:`propose_reschedule_target` raises
    :class:`NotImplementedError`. Inject :class:`ScriptedReasoner` for v0.
    """

    def propose_reschedule_target(self, **kwargs: object) -> RescheduleProposal | None:
        raise NotImplementedError(
            "LLMReasoner is the Phase 4.5 implementation. "
            "Inject ScriptedReasoner() for v0."
        )
