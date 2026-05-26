"""ScriptedReasoner — deterministic first-fit picker.

Walks the candidates in order and accepts the first one that does not
overlap with any existing event on the calendar. No network, no
randomness, fully reproducible.
"""

from __future__ import annotations

from datetime import datetime

from meshycal.calendar_object import CalendarObject
from meshycal.reasoners.base import ProposalVerdict


class ScriptedReasoner:
    async def evaluate_proposal(
        self,
        *,
        candidate_slots: list[str],
        duration_minutes: int,
        my_calendar: CalendarObject,
        my_display_name: str,
    ) -> ProposalVerdict:
        for candidate in candidate_slots:
            slot_dt = _parse_iso(candidate)
            if not my_calendar.is_busy_at(
                slot_start=slot_dt, duration_minutes=duration_minutes
            ):
                return ProposalVerdict(
                    accept=True,
                    chosen_slot=candidate,
                    reason=(
                        f"scripted first-fit: {candidate} is the first candidate "
                        f"clear of {my_display_name}'s calendar"
                    ),
                )
        return ProposalVerdict(
            accept=False,
            chosen_slot=None,
            reason=(
                f"scripted: all candidates conflict with "
                f"{my_display_name}'s existing events"
            ),
        )


def _parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
