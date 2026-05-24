"""Deterministic slot-picking logic for the Phase 1 scheduling demo.

Per SPEC §6: scheduling agents compute candidate / accepted slots from a
private busy-calendar with NO LLM, NO randomness. Same inputs always
produce the same output — replayable from the residue ledger.

Two functions:

* :func:`find_free_candidates` — Agent A's role. Given A's own busy calendar
  and a duration, walk the working-hour grid starting from a reference
  time and return the first ``num_candidates`` slots that don't conflict
  with A's calendar.
* :func:`pick_acceptable_slot` — Agent B's role. Given B's busy calendar
  and a list of candidates A proposed, return the first candidate B is
  free for; return None if B is busy for every candidate (then B's agent
  will counter-propose using ``find_free_candidates`` against B's calendar).

Slot grid: weekdays only (Mon–Fri), 09:00–17:00 UTC, 30-minute increments.
A slot is "free" only if the entire [slot_start, slot_start + duration]
interval is clear of every busy block. Working-hour discipline lives here
so the agents can't disagree on what "free" means.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime, time, timedelta, timezone

_WORKDAY_START = time(9, 0, tzinfo=timezone.utc)
_WORKDAY_END = time(17, 0, tzinfo=timezone.utc)
_SLOT_GRANULARITY = timedelta(minutes=30)
_LOOKAHEAD_DAYS = 7


def find_free_candidates(
    *,
    busy: Iterable[dict[str, str]],
    duration_minutes: int,
    reference_time: datetime,
    num_candidates: int = 3,
) -> list[str]:
    """Return the first ``num_candidates`` free slots after ``reference_time``.

    Args:
        busy: This agent's busy intervals, each ``{"start_utc": iso, "end_utc": iso}``.
        duration_minutes: Length of the meeting being proposed.
        reference_time: Earliest moment we'll consider — typically ``datetime.now(timezone.utc)``
            in the agent process. Must be timezone-aware UTC.
        num_candidates: How many free slots to return. Default 3 per SPEC §6.

    Returns:
        ISO-8601 UTC strings (suffix ``Z``) for slot starts, ordered earliest first.
        Empty list if no free slots exist in the 7-day lookahead — caller decides
        how to handle (Phase 1 demo terminates; a real agent would extend lookahead).
    """
    _require_utc(reference_time, name="reference_time")
    duration = timedelta(minutes=duration_minutes)
    busy_intervals = _parse_busy(busy)

    candidates: list[str] = []
    for slot_start in _iter_workday_slots(reference_time):
        slot_end = slot_start + duration
        if slot_end.timetz() > _WORKDAY_END:
            continue
        if _overlaps_any(slot_start, slot_end, busy_intervals):
            continue
        candidates.append(_to_iso_z(slot_start))
        if len(candidates) >= num_candidates:
            break
    return candidates


def pick_acceptable_slot(
    *,
    busy: Iterable[dict[str, str]],
    candidates: list[str],
    duration_minutes: int,
) -> str | None:
    """Return the first candidate this agent is free for, or None.

    A returned slot is one this agent can honor; None signals the agent's
    domain logic that a counter-proposal is needed.
    """
    duration = timedelta(minutes=duration_minutes)
    busy_intervals = _parse_busy(busy)
    for iso in candidates:
        slot_start = _parse_iso_z(iso)
        slot_end = slot_start + duration
        if not _overlaps_any(slot_start, slot_end, busy_intervals):
            return iso
    return None


def _iter_workday_slots(reference_time: datetime) -> Iterator[datetime]:
    """Yield 30-minute slot starts within working hours for the next 7 days.

    Slots earlier than ``reference_time`` are skipped. Weekends are skipped.
    """
    end_window = reference_time + timedelta(days=_LOOKAHEAD_DAYS)
    cursor = _round_up_to_slot(reference_time)
    while cursor < end_window:
        if cursor.weekday() >= 5:  # Sat/Sun
            cursor = _start_of_next_workday(cursor)
            continue
        if cursor.timetz() < _WORKDAY_START:
            cursor = cursor.replace(hour=9, minute=0, second=0, microsecond=0)
        if cursor.timetz() >= _WORKDAY_END:
            cursor = _start_of_next_workday(cursor)
            continue
        yield cursor
        cursor = cursor + _SLOT_GRANULARITY


def _round_up_to_slot(dt: datetime) -> datetime:
    """Round ``dt`` up to the next 30-minute boundary."""
    minute = dt.minute
    if dt.second == 0 and dt.microsecond == 0 and minute % 30 == 0:
        return dt
    bumped_minute = ((minute // 30) + 1) * 30
    if bumped_minute >= 60:
        return (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return dt.replace(minute=bumped_minute, second=0, microsecond=0)


def _start_of_next_workday(dt: datetime) -> datetime:
    """Return 09:00 UTC of the next weekday after ``dt``."""
    next_day = dt + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day = next_day + timedelta(days=1)
    return next_day.replace(hour=9, minute=0, second=0, microsecond=0)


def _parse_busy(busy: Iterable[dict[str, str]]) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    for entry in busy:
        start = _parse_iso_z(entry["start_utc"])
        end = _parse_iso_z(entry["end_utc"])
        if end <= start:
            raise ValueError(
                f"Busy interval has end_utc <= start_utc: {entry!r}. "
                "Calendar fixtures must contain non-empty intervals in chronological order."
            )
        intervals.append((start, end))
    return intervals


def _overlaps_any(
    slot_start: datetime,
    slot_end: datetime,
    intervals: list[tuple[datetime, datetime]],
) -> bool:
    for busy_start, busy_end in intervals:
        if slot_start < busy_end and busy_start < slot_end:
            return True
    return False


def _parse_iso_z(iso: str) -> datetime:
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    parsed = datetime.fromisoformat(iso)
    _require_utc(parsed, name="iso string")
    return parsed


def _to_iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_utc(dt: datetime, *, name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ValueError(
            f"{name} must be timezone-aware UTC (got tzinfo={dt.tzinfo!r}). "
            "Phase 1 fixes everything to UTC; local-time conversion is a "
            "Phase 3 problem (it touches scoped disclosure)."
        )
