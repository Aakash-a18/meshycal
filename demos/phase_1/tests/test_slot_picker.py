"""Unit tests for the deterministic slot picker.

These cover the "free slot finder" contract that Agent A relies on
pre-send and that Agent B relies on for accept-or-counter.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from slot_picker import find_free_candidates, pick_acceptable_slot


# A Monday at 08:00 UTC — well before the workday so the first slot
# generated is 09:00 of the same day. Using a fixed reference makes every
# assertion below independent of when the test runs.
_MONDAY_08_UTC = datetime(2026, 5, 25, 8, 0, tzinfo=timezone.utc)


class TestFindFreeCandidates:
    def test_empty_calendar_returns_first_three_workday_slots(self) -> None:
        candidates = find_free_candidates(
            busy=[], duration_minutes=30, reference_time=_MONDAY_08_UTC
        )
        assert candidates == [
            "2026-05-25T09:00:00Z",
            "2026-05-25T09:30:00Z",
            "2026-05-25T10:00:00Z",
        ]

    def test_skips_busy_intervals(self) -> None:
        busy = [
            {"start_utc": "2026-05-25T09:00:00Z", "end_utc": "2026-05-25T10:00:00Z"},
        ]
        candidates = find_free_candidates(
            busy=busy, duration_minutes=30, reference_time=_MONDAY_08_UTC
        )
        assert candidates[0] == "2026-05-25T10:00:00Z"
        # 09:00 and 09:30 are both consumed by the busy block.
        assert "2026-05-25T09:00:00Z" not in candidates
        assert "2026-05-25T09:30:00Z" not in candidates

    def test_respects_meeting_duration(self) -> None:
        # A 09:30 busy block leaves only 09:00 free for a 30-min meeting,
        # but ZERO free slots for a 60-min meeting starting before 10:00.
        busy = [
            {"start_utc": "2026-05-25T09:30:00Z", "end_utc": "2026-05-25T10:00:00Z"},
        ]
        thirty = find_free_candidates(
            busy=busy, duration_minutes=30, reference_time=_MONDAY_08_UTC
        )
        assert thirty[0] == "2026-05-25T09:00:00Z"

        sixty = find_free_candidates(
            busy=busy, duration_minutes=60, reference_time=_MONDAY_08_UTC
        )
        # First valid 60-min slot is 10:00 (since 09:00 collides at 09:30).
        assert sixty[0] == "2026-05-25T10:00:00Z"

    def test_skips_weekends(self) -> None:
        # Friday 16:00 → only one 30-min slot left Friday (16:00-16:30),
        # one more starting 16:30, then nothing until Monday at 09:00.
        friday = datetime(2026, 5, 29, 16, 0, tzinfo=timezone.utc)
        candidates = find_free_candidates(
            busy=[], duration_minutes=30, reference_time=friday, num_candidates=4
        )
        assert candidates == [
            "2026-05-29T16:00:00Z",
            "2026-05-29T16:30:00Z",
            "2026-06-01T09:00:00Z",  # Monday
            "2026-06-01T09:30:00Z",
        ]

    def test_meeting_cannot_overflow_workday_end(self) -> None:
        # 16:45 reference, 30-min meeting → first valid start is 17:00? No —
        # 17:00 + 30 = 17:30 which exceeds workday end (17:00). So the first
        # candidate must be 09:00 next day.
        late = datetime(2026, 5, 25, 16, 45, tzinfo=timezone.utc)
        candidates = find_free_candidates(
            busy=[], duration_minutes=30, reference_time=late
        )
        assert candidates[0] == "2026-05-26T09:00:00Z"

    def test_deterministic_same_inputs_same_outputs(self) -> None:
        busy = [{"start_utc": "2026-05-25T10:00:00Z", "end_utc": "2026-05-25T11:00:00Z"}]
        first = find_free_candidates(
            busy=busy, duration_minutes=45, reference_time=_MONDAY_08_UTC
        )
        second = find_free_candidates(
            busy=busy, duration_minutes=45, reference_time=_MONDAY_08_UTC
        )
        assert first == second

    def test_rejects_naive_reference_time(self) -> None:
        naive = datetime(2026, 5, 25, 9, 0)  # no tzinfo
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            find_free_candidates(busy=[], duration_minutes=30, reference_time=naive)

    def test_returns_empty_when_calendar_is_fully_busy(self) -> None:
        # Block out every workday slot in the next 7 days.
        busy = []
        for day_offset in range(7):
            day = datetime(2026, 5, 25, tzinfo=timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            from datetime import timedelta
            day = day + timedelta(days=day_offset)
            if day.weekday() < 5:
                busy.append(
                    {
                        "start_utc": day.replace(hour=9).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "end_utc": day.replace(hour=17).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                )
        assert find_free_candidates(
            busy=busy, duration_minutes=30, reference_time=_MONDAY_08_UTC
        ) == []


class TestPickAcceptableSlot:
    def test_picks_first_free_candidate(self) -> None:
        busy = [
            {"start_utc": "2026-05-25T09:00:00Z", "end_utc": "2026-05-25T10:00:00Z"},
        ]
        candidates = [
            "2026-05-25T09:00:00Z",  # B is busy
            "2026-05-25T10:30:00Z",  # B is free — accept this
            "2026-05-25T14:00:00Z",  # also free, but the first match wins
        ]
        picked = pick_acceptable_slot(
            busy=busy, candidates=candidates, duration_minutes=30
        )
        assert picked == "2026-05-25T10:30:00Z"

    def test_returns_none_when_all_candidates_conflict(self) -> None:
        busy = [
            {"start_utc": "2026-05-25T09:00:00Z", "end_utc": "2026-05-25T18:00:00Z"},
        ]
        candidates = [
            "2026-05-25T09:30:00Z",
            "2026-05-25T11:00:00Z",
            "2026-05-25T14:00:00Z",
        ]
        assert (
            pick_acceptable_slot(busy=busy, candidates=candidates, duration_minutes=30)
            is None
        )

    def test_respects_duration_when_checking_conflict(self) -> None:
        # B is busy 10:30–11:00. Candidate 10:00 + 30 min is fine; 10:00 + 60
        # min collides.
        busy = [
            {"start_utc": "2026-05-25T10:30:00Z", "end_utc": "2026-05-25T11:00:00Z"},
        ]
        assert (
            pick_acceptable_slot(
                busy=busy,
                candidates=["2026-05-25T10:00:00Z"],
                duration_minutes=30,
            )
            == "2026-05-25T10:00:00Z"
        )
        assert (
            pick_acceptable_slot(
                busy=busy,
                candidates=["2026-05-25T10:00:00Z"],
                duration_minutes=60,
            )
            is None
        )
