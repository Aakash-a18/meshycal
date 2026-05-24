"""Unit tests for the synthetic calendar fixture generator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from synthetic_calendar import (
    generate_calendar,
    read_calendar,
    write_calendar,
)

_MONDAY_UTC = datetime(2026, 5, 25, 0, 0, tzinfo=timezone.utc)


class TestGenerateCalendar:
    def test_same_seed_produces_byte_identical_output(self) -> None:
        a = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=42,
        )
        b = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=42,
        )
        assert a == b

    def test_different_seeds_produce_different_calendars(self) -> None:
        a = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=1,
        )
        b = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=2,
        )
        assert a["busy"] != b["busy"]

    def test_owner_field_is_embedded(self) -> None:
        cal = generate_calendar(
            owner_principal_id="user-b@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=7,
        )
        assert cal["owner_principal_id"] == "user-b@phase1.local"

    def test_no_busy_blocks_on_weekends(self) -> None:
        cal = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=7,
            lookahead_days=14,
        )
        for entry in cal["busy"]:
            start = datetime.fromisoformat(entry["start_utc"].replace("Z", "+00:00"))
            assert start.weekday() < 5, (
                f"weekend busy block produced: {entry!r}"
            )

    def test_busy_blocks_stay_within_lookahead_window(self) -> None:
        cal = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=7,
            lookahead_days=7,
        )
        window_end = _MONDAY_UTC + timedelta(days=7)
        for entry in cal["busy"]:
            end = datetime.fromisoformat(entry["end_utc"].replace("Z", "+00:00"))
            assert end <= window_end

    def test_busy_intervals_are_non_empty(self) -> None:
        cal = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=7,
        )
        for entry in cal["busy"]:
            start = datetime.fromisoformat(entry["start_utc"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(entry["end_utc"].replace("Z", "+00:00"))
            assert end > start

    def test_no_titles_or_attendees_in_fixture(self) -> None:
        """Privacy posture: fixture carries only start/end. The wire schema
        (proposal-v1) is the same — calendar contents never travel."""
        cal = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=7,
        )
        for entry in cal["busy"]:
            assert set(entry.keys()) == {"start_utc", "end_utc"}

    def test_rejects_naive_reference_time(self) -> None:
        naive = datetime(2026, 5, 25, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            generate_calendar(
                owner_principal_id="user-a@phase1.local",
                reference_time=naive,
                seed=1,
            )


class TestWriteRead:
    def test_round_trip(self, tmp_path: Path) -> None:
        cal = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=42,
        )
        target = tmp_path / "cal.json"
        write_calendar(cal, target)
        assert read_calendar(target) == cal

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        cal = generate_calendar(
            owner_principal_id="user-a@phase1.local",
            reference_time=_MONDAY_UTC,
            seed=42,
        )
        deep = tmp_path / "nested" / "dir" / "cal.json"
        write_calendar(cal, deep)
        assert deep.exists()
