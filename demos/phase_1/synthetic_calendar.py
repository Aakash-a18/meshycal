"""Synthetic calendar fixture generator for the Phase 1 demo.

Per MeshyCal CLAUDE.md rule 3: NO real user data, ever — synthetic only.
Per SPEC §6: Agent A reads ``agent_a_calendar.json`` and Agent B reads
``agent_b_calendar.json``. This module produces those files deterministically
from a seed so the demo is reproducible.

What the fixture contains:

* ``owner_principal_id`` — the agent's principal (e.g., ``user-a@phase1.local``).
* ``reference_time`` — the UTC instant the calendar was generated against.
  Embedded so the slot picker uses the same "now" the fixture was anchored to.
* ``busy`` — a list of busy intervals (start_utc / end_utc only). NO titles,
  NO attendees, NO descriptions. The privacy posture is structural: there is
  nothing in the fixture that could leak even if it were exfiltrated.

The generator is deterministic given (seed, reference_time, owner). Calling
``generate_calendar`` twice with the same args returns byte-identical output.
The demo orchestrator regenerates fixtures at start so they always describe
"the next 7 days" relative to the demo run, never going stale on disk.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Working-hour grid the slot picker walks. Kept consistent with slot_picker
# so generated busy blocks land on slot boundaries.
_BUSY_BLOCK_OPTIONS_HOURS = [
    (9, 10),    # mid-morning 1h
    (10, 11),   # late-morning 1h
    (11, 12),   # pre-lunch 1h
    (13, 14),   # post-lunch 1h
    (14, 15),   # mid-afternoon 1h
    (15, 16),   # late-afternoon 1h
    (16, 17),   # end-of-day 1h
]


def generate_calendar(
    *,
    owner_principal_id: str,
    reference_time: datetime,
    seed: int,
    busy_blocks_per_day: int = 2,
    lookahead_days: int = 7,
) -> dict:
    """Generate a synthetic busy calendar deterministically.

    Args:
        owner_principal_id: Principal id this calendar belongs to.
        reference_time: UTC anchor; busy blocks are generated for the next
            ``lookahead_days`` weekdays starting from this time.
        seed: Per-owner RNG seed. Different owners get different calendars
            even with the same reference_time.
        busy_blocks_per_day: How many busy blocks each weekday gets (default 2).
        lookahead_days: Calendar coverage horizon (default 7).

    Returns:
        ``{"owner_principal_id": ..., "reference_time": iso,
           "busy": [{"start_utc": iso, "end_utc": iso}, ...]}``.
    """
    if reference_time.tzinfo is None or reference_time.utcoffset() != timedelta(0):
        raise ValueError(
            f"reference_time must be timezone-aware UTC; got tzinfo="
            f"{reference_time.tzinfo!r}"
        )

    rng = random.Random(seed)
    busy: list[dict[str, str]] = []
    day_cursor = reference_time.replace(hour=0, minute=0, second=0, microsecond=0)
    days_covered = 0
    while days_covered < lookahead_days:
        if day_cursor.weekday() < 5:  # Mon-Fri only
            chosen = rng.sample(
                _BUSY_BLOCK_OPTIONS_HOURS,
                k=min(busy_blocks_per_day, len(_BUSY_BLOCK_OPTIONS_HOURS)),
            )
            # Sort by start-of-block so the fixture is human-readable.
            for start_h, end_h in sorted(chosen):
                start = day_cursor.replace(hour=start_h)
                end = day_cursor.replace(hour=end_h)
                busy.append(
                    {
                        "start_utc": _to_iso_z(start),
                        "end_utc": _to_iso_z(end),
                    }
                )
        day_cursor = day_cursor + timedelta(days=1)
        days_covered += 1

    return {
        "owner_principal_id": owner_principal_id,
        "reference_time": _to_iso_z(reference_time),
        "busy": busy,
    }


def write_calendar(calendar: dict, path: Path) -> None:
    """Write a calendar dict to disk as pretty-printed JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calendar, indent=2) + "\n", encoding="utf-8")


def read_calendar(path: Path) -> dict:
    """Load a calendar fixture from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def _to_iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
