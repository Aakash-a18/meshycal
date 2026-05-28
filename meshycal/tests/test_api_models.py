"""Tests for meshycal.api.models — wire-shape models the renderer
consumes. These are validation rules that don't depend on a running
api; they're properties of the model classes themselves."""

from __future__ import annotations

import pytest

from meshycal.api.models import (
    LedgerEntry,
    MeetingCard,
    MeetingDetail,
    MeetingStatus,
)


def _detail_kwargs(**overrides: object) -> dict[str, object]:
    base = {
        "id": "m-x",
        "status": MeetingStatus.ACCEPTED,
        "counterparty_name": "Bob",
        "counterparty_principal_id": "bob@sandbox.local",
        "proposed_time": "2026-06-01T13:00:00Z",
        "duration_minutes": 30,
        "title": "Coffee chat",
        "last_updated": "2026-05-27T09:00:00Z",
    }
    base.update(overrides)
    return base


def test_meeting_status_round_trip():
    for s in ("pending", "accepted", "declined"):
        assert MeetingStatus(s).value == s


def test_agreement_hash_must_be_64_hex():
    """A 32-hex value (the OLD skeleton-fixture shape) must NOT
    validate against MeetingDetail — proves the api projection cannot
    silently lie about the real canonical hash length, which the
    underlying MeetingObjectState enforces as 64 hex."""
    short_hash = "b7c1e4a9d22f60185df1c0a3e8b5f7d4"  # 32 hex
    assert len(short_hash) == 32
    with pytest.raises(Exception):
        MeetingDetail(**_detail_kwargs(agreement_hash=short_hash))


def test_agreement_hash_accepts_full_64_hex():
    full_hash = "a" * 64
    detail = MeetingDetail(**_detail_kwargs(agreement_hash=full_hash))
    assert detail.agreement_hash == full_hash


def test_agreement_hash_none_is_allowed():
    """Pending and declined meetings have no canonical agreement yet."""
    detail = MeetingDetail(**_detail_kwargs(
        status=MeetingStatus.PENDING, agreement_hash=None,
    ))
    assert detail.agreement_hash is None


def test_meeting_card_requires_positive_duration():
    with pytest.raises(Exception):
        MeetingCard(
            id="x",
            status=MeetingStatus.PENDING,
            counterparty_name="Bob",
            counterparty_principal_id="bob@sandbox.local",
            proposed_time=None,
            duration_minutes=0,
            title="t",
            last_updated="2026-05-27T09:00:00Z",
        )


def test_ledger_entry_carries_operation_and_action():
    """The substrate-shaped operation and the renderer-side action
    both ride on every entry — a second host surface can choose to
    humanize from operation directly and ignore action's prose."""
    entry = LedgerEntry(
        timestamp="2026-05-27T09:00:00Z",
        actor="you",
        operation="proposal",
        action="sent proposal",
        payload_hash_preview="abcd1234abcd1234",
    )
    assert entry.operation == "proposal"
    assert entry.action == "sent proposal"
