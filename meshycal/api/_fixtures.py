"""Synthetic seed data for the skeleton.

Replaced in step 4 by a real adapter over SchedulingAgent + ledger.
Names follow the CLAUDE.md rule: no real user data, ever. All
addresses use the `sandbox.local` domain so they cannot collide with
real ones.

Source of truth here is `seed_details()`. The inbox list view
derives its cards from the same details so the two endpoints can
never disagree about the underlying meeting.

Hash and operation values are chosen to match the real substrate's
shape (64-hex agreement_hash, Mesherra-`Operation`-enum strings) so
that step 4's real adapter is a drop-in.
"""

from __future__ import annotations

from meshycal.api.models import (
    LedgerEntry,
    MeetingCard,
    MeetingDetail,
    MeetingStatus,
)


def seed_details() -> list[MeetingDetail]:
    return [
        MeetingDetail(
            id="m-pending-001",
            status=MeetingStatus.PENDING,
            counterparty_name="Bob Lin",
            counterparty_principal_id="bob@sandbox.local",
            proposed_time="2026-06-02T14:00:00Z",
            duration_minutes=30,
            title="Coffee chat",
            last_updated="2026-05-27T09:12:00Z",
            agreement_hash=None,
            ledger=[
                LedgerEntry(
                    timestamp="2026-05-27T09:12:00Z",
                    actor="Bob Lin",
                    operation="proposal",
                    action="proposed three slots",
                    payload_hash_preview="9f3a4c1b22e5c8d0",
                ),
            ],
            reasoning="Bob's agent suggested 3 windows. Your butler is "
            "waiting for your call on which to accept.",
        ),
        MeetingDetail(
            id="m-accepted-001",
            status=MeetingStatus.ACCEPTED,
            counterparty_name="Sara Park",
            counterparty_principal_id="sara@sandbox.local",
            proposed_time="2026-05-29T11:00:00Z",
            duration_minutes=45,
            title="Design review",
            last_updated="2026-05-26T18:04:00Z",
            agreement_hash=(
                "b7c1e4a9d22f60185df1c0a3e8b5f7d4"
                "4ce21a900e7fb38c91d5a26f0e3b14a8"
            ),
            ledger=[
                LedgerEntry(
                    timestamp="2026-05-26T17:58:00Z",
                    actor="you",
                    operation="proposal",
                    action="proposed Wed 11:00",
                    payload_hash_preview="3a91d50e7b4c2f88",
                ),
                LedgerEntry(
                    timestamp="2026-05-26T18:03:55Z",
                    actor="Sara Park",
                    operation="acceptance",
                    action="accepted",
                    payload_hash_preview="b7c1e4a9d22f6018",
                ),
                LedgerEntry(
                    timestamp="2026-05-26T18:04:00Z",
                    actor="you",
                    operation="promote",
                    action="signed canonical agreement",
                    payload_hash_preview="b7c1e4a9d22f6018",
                ),
            ],
            reasoning="Sara's agent accepted on the first slot your "
            "calendar allowed. Booking written to your calendar.",
        ),
        MeetingDetail(
            id="m-declined-001",
            status=MeetingStatus.DECLINED,
            counterparty_name="Marco Diaz",
            counterparty_principal_id="marco@sandbox.local",
            proposed_time="2026-06-04T16:00:00Z",
            duration_minutes=60,
            title="Vendor pitch",
            last_updated="2026-05-25T08:21:00Z",
            agreement_hash=None,
            ledger=[
                LedgerEntry(
                    timestamp="2026-05-25T08:19:00Z",
                    actor="Marco Diaz",
                    operation="proposal",
                    action="proposed Thu 16:00",
                    payload_hash_preview="ca77ed1f0934b2a6",
                ),
                LedgerEntry(
                    timestamp="2026-05-25T08:21:00Z",
                    actor="you",
                    operation="rejection",
                    action="declined (policy: vendor pitches off by default)",
                    payload_hash_preview="ca77ed1f0934b2a6",
                ),
            ],
            reasoning="Your butler declined per your standing policy: "
            "vendor pitches require your explicit approval.",
        ),
    ]


def seed_cards() -> list[MeetingCard]:
    """Cards are a projection of details — never edit independently."""
    return [
        MeetingCard.model_validate(
            d.model_dump(include=set(MeetingCard.model_fields.keys()))
        )
        for d in seed_details()
    ]


def find_detail(meeting_id: str) -> MeetingDetail | None:
    return next((d for d in seed_details() if d.id == meeting_id), None)
