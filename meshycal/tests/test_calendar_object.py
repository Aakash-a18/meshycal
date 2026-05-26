"""Unit tests for CalendarObject — owner-bound, canonical hash, free slots."""

from __future__ import annotations

from datetime import UTC, datetime

from meshycal import CalendarEvent, CalendarObject


def _cal(pid: str = "iris@sandbox.local", events=None) -> CalendarObject:
    return CalendarObject(owner_principal_id=pid, events=events or [])


def test_owner_principal_id_is_bound():
    c = _cal("iris@sandbox.local")
    assert c.owner_principal_id == "iris@sandbox.local"


def test_canonical_hash_is_deterministic_under_event_order():
    """Two calendars with the same events in different orders must hash
    to the same value — the sorting in to_signing_payload() is what
    makes this safe."""
    a = _cal(events=[
        CalendarEvent(time="09:00", duration=30, title="standup"),
        CalendarEvent(time="11:00", duration=60, title="review"),
    ])
    b = _cal(events=[
        CalendarEvent(time="11:00", duration=60, title="review"),
        CalendarEvent(time="09:00", duration=30, title="standup"),
    ])
    assert a.canonical_hash() == b.canonical_hash()


def test_canonical_hash_changes_on_mutation():
    c = _cal()
    h0 = c.canonical_hash()
    c.book(time="13:00", duration=30, title="new")
    h1 = c.canonical_hash()
    assert h0 != h1


def test_canonical_hash_changes_when_owner_changes():
    a = _cal("iris@sandbox.local", [CalendarEvent(time="09:00", duration=30, title="x")])
    b = _cal("marius@sandbox.local", [CalendarEvent(time="09:00", duration=30, title="x")])
    assert a.canonical_hash() != b.canonical_hash()


def test_canonical_hash_changes_when_version_changes():
    a = CalendarObject(owner_principal_id="i@x", events=[], version=0)
    b = CalendarObject(owner_principal_id="i@x", events=[], version=1)
    assert a.canonical_hash() != b.canonical_hash()


def test_book_bumps_version():
    c = _cal()
    assert c.version == 0
    c.book(time="13:00", duration=30, title="t1")
    assert c.version == 1
    c.book(time="14:00", duration=30, title="t2")
    assert c.version == 2


def test_remove_event_bumps_version_on_hit():
    c = _cal(events=[CalendarEvent(time="13:00", duration=30, title="t1")])
    v0 = c.version
    assert c.remove_event(time="13:00", title="t1") is True
    assert c.version == v0 + 1
    assert c.remove_event(time="13:00", title="t1") is False  # already gone
    assert c.version == v0 + 1


def test_is_busy_at_detects_overlap():
    c = _cal(events=[CalendarEvent(time="10:00", duration=60, title="x")])
    base = datetime(2026, 5, 26, tzinfo=UTC)
    # Same start as event → busy
    assert c.is_busy_at(
        slot_start=base.replace(hour=10, minute=0), duration_minutes=30
    ) is True
    # Inside the event window → busy
    assert c.is_busy_at(
        slot_start=base.replace(hour=10, minute=30), duration_minutes=30
    ) is True
    # Right after the event ends → free
    assert c.is_busy_at(
        slot_start=base.replace(hour=11, minute=0), duration_minutes=30
    ) is False
    # Right before → free
    assert c.is_busy_at(
        slot_start=base.replace(hour=9, minute=0), duration_minutes=30
    ) is False


def test_free_slots_filters_conflicts():
    c = _cal(events=[
        CalendarEvent(time="09:00", duration=60, title="morning"),
        CalendarEvent(time="11:00", duration=30, title="focus"),
    ])
    earliest = datetime(2026, 5, 26, 9, 0, tzinfo=UTC)
    latest = datetime(2026, 5, 26, 18, 0, tzinfo=UTC)
    candidates = c.free_slots(
        earliest=earliest, latest=latest, duration_minutes=30
    )
    # 09:00 should be filtered (conflict). 11:00 should be filtered too.
    # 10:00 / 12:00 / 13:00 should appear.
    assert all("T09:00" not in s for s in candidates)
    assert all("T11:00" not in s for s in candidates)
    assert any("T10:00" in s for s in candidates)


def test_free_slots_falls_back_when_all_busy():
    """If every step in the window is busy, fall back to the unfiltered
    list so the recipient's reasoner can do the rejection cleanly."""
    c = _cal(events=[CalendarEvent(time=f"{h:02d}:00", duration=60, title=f"e{h}")
                     for h in range(9, 18)])
    earliest = datetime(2026, 5, 26, 9, 0, tzinfo=UTC)
    latest = datetime(2026, 5, 26, 18, 0, tzinfo=UTC)
    candidates = c.free_slots(
        earliest=earliest, latest=latest, duration_minutes=30
    )
    assert len(candidates) > 0  # not empty


def test_free_slots_respects_max_candidates():
    c = _cal()
    earliest = datetime(2026, 5, 26, 9, 0, tzinfo=UTC)
    latest = datetime(2026, 5, 26, 18, 0, tzinfo=UTC)
    candidates = c.free_slots(
        earliest=earliest, latest=latest, duration_minutes=30, max_candidates=3
    )
    assert len(candidates) == 3
