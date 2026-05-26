"""CalendarObject — a user's calendar as an owner-bound Mesherra-aligned Object.

The Object Class abstraction documented in
``mesherra/docs/ARCHITECTURE.md`` isn't yet implemented as a first-class
primitive on the Mesherra side. MeshyCal builds it on top: a per-user
object that holds the calendar state, exposes a canonical hash (so the
agent can attest to a specific state when signing a proposal), and bumps
its version on every mutation.

The canonical_hash() bytes are produced via Mesherra's own canonical_json
+ content_hash so they share the JCS / SHA-256 discipline of every other
hash MeshyCal puts on the wire.

This file imports nothing from MeshyCal itself — only Mesherra primitives
and stdlib. That keeps the dependency direction CLAUDE.md Rule 1 demands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from mesherra.crypto.primitives import canonical_json, content_hash


@dataclass
class CalendarEvent:
    """One calendar entry. Synthetic data only (CLAUDE.md Rule 3).

    Mutable so the agent can update titles / attendees after a successful
    exchange. ``is_blocking=True`` flags an event that a 3-party cascade
    would try to reschedule.
    """

    time: str          # "HH:MM" 24h local
    duration: int      # minutes
    title: str = ""
    attendees: str = ""
    is_blocking: bool = False

    def to_signing_payload(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "duration": int(self.duration),
            "title": self.title,
            "attendees": self.attendees,
            "is_blocking": bool(self.is_blocking),
        }


class CalendarObject:
    """A user's calendar — owner-bound, canonically hashable, mutable.

    The owner_principal_id is the binding to a Mesherra identity. The
    canonical_hash() is the snapshot proof: "this is what my calendar
    said at this version."

    free_slots() / is_busy_at() are the read API the SchedulingAgent
    uses when building proposal candidates.

    book() / remove_event() are the write API; both bump version.
    """

    def __init__(
        self,
        *,
        owner_principal_id: str,
        events: list[CalendarEvent] | None = None,
        timezone: str = "UTC",
        version: int = 0,
    ) -> None:
        self.owner_principal_id = owner_principal_id
        self.events: list[CalendarEvent] = list(events or [])
        self.timezone = timezone
        self.version = version

    # --- canonical state ----------------------------------------------

    def to_signing_payload(self) -> dict[str, Any]:
        """Stable, JCS-canonicalizable representation. Events sorted by
        (time, title) so the hash is order-independent."""
        return {
            "owner": self.owner_principal_id,
            "events": sorted(
                [e.to_signing_payload() for e in self.events],
                key=lambda d: (d["time"], d["title"]),
            ),
            "timezone": self.timezone,
            "version": int(self.version),
        }

    def canonical_hash(self) -> str:
        """SHA-256(JCS(to_signing_payload())) — the trust artefact the
        agent attests to when sending a proposal."""
        return content_hash(canonical_json(self.to_signing_payload()))

    # --- mutations ----------------------------------------------------

    def book(
        self,
        *,
        time: str,
        duration: int,
        title: str,
        attendees: str = "",
    ) -> CalendarEvent:
        """Append a meeting after a successful exchange. Bumps version."""
        ev = CalendarEvent(
            time=time, duration=duration,
            title=title, attendees=attendees, is_blocking=False,
        )
        self.events.append(ev)
        self.version += 1
        return ev

    def remove_event(self, *, time: str, title: str) -> bool:
        """Remove first event matching (time, title). Bumps version on hit."""
        for i, e in enumerate(self.events):
            if e.time == time and e.title == title:
                self.events.pop(i)
                self.version += 1
                return True
        return False

    # --- read API the agent + reasoners use ---------------------------

    def is_busy_at(
        self,
        *,
        slot_start: datetime,
        duration_minutes: int,
    ) -> bool:
        """True if any existing event overlaps [slot_start, slot_start + duration)."""
        slot_end = slot_start + timedelta(minutes=duration_minutes)
        ref_date = slot_start.replace(hour=0, minute=0, second=0, microsecond=0)
        for ev in self.events:
            ev_start = self._event_datetime(ev, ref_date)
            ev_end = ev_start + timedelta(minutes=ev.duration)
            if ev_start < slot_end and ev_end > slot_start:
                return True
        return False

    def free_slots(
        self,
        *,
        earliest: datetime,
        latest: datetime,
        duration_minutes: int,
        step_minutes: int = 60,
        max_candidates: int = 5,
    ) -> list[str]:
        """ISO 8601 candidate slot strings in [earliest, latest] where
        this calendar has no overlap for the requested duration. Falls
        back to the unfiltered list if no free slot fits — the recipient
        side's reasoner will handle the rejection cleanly."""
        candidates: list[str] = []
        cur = earliest
        step = timedelta(minutes=step_minutes)
        dur_td = timedelta(minutes=duration_minutes)
        while cur + dur_td <= latest and len(candidates) < max_candidates:
            if not self.is_busy_at(slot_start=cur, duration_minutes=duration_minutes):
                candidates.append(cur.strftime("%Y-%m-%dT%H:%M:%SZ"))
            cur += step
        if not candidates:
            cur = earliest
            while cur + dur_td <= latest and len(candidates) < max_candidates:
                candidates.append(cur.strftime("%Y-%m-%dT%H:%M:%SZ"))
                cur += step
        return candidates

    def busy_intervals_on(self, *, reference_date: datetime) -> list[tuple[datetime, datetime]]:
        """Project events onto a date and return their occupied intervals.
        Useful for reasoners that take a list of busy windows."""
        out: list[tuple[datetime, datetime]] = []
        ref = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
        for ev in self.events:
            ev_start = self._event_datetime(ev, ref)
            out.append((ev_start, ev_start + timedelta(minutes=ev.duration)))
        return out

    # --- internal -----------------------------------------------------

    @staticmethod
    def _event_datetime(ev: CalendarEvent, reference_date: datetime) -> datetime:
        hh, mm = ev.time.split(":", 1)
        return reference_date.replace(
            hour=int(hh), minute=int(mm), second=0, microsecond=0
        )
