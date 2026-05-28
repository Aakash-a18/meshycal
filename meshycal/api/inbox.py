"""In-memory inbox store used by the skeleton.

One instance per FastAPI app, held on `app.state.inbox`. This is the
single source of truth for both the list endpoint, the detail endpoint,
and the new-meeting endpoint, so they cannot drift out of sync.

Step 4 replaces this whole module with an adapter over
`SchedulingAgent` + `ProvenanceLedger` + `ObjectStore`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from meshycal.api.models import (
    LedgerEntry,
    MeetingCard,
    MeetingDetail,
    MeetingStatus,
    NewMeetingRequest,
)

_STATUS_ORDER = {
    MeetingStatus.PENDING: 0,
    MeetingStatus.ACCEPTED: 1,
    MeetingStatus.DECLINED: 2,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _card_from_detail(detail: MeetingDetail) -> MeetingCard:
    return MeetingCard.model_validate(
        detail.model_dump(include=set(MeetingCard.model_fields.keys()))
    )


class InMemoryInbox:
    def __init__(self, seed: list[MeetingDetail] | None = None) -> None:
        self._by_id: dict[str, MeetingDetail] = {}
        self._order: list[str] = []
        for detail in seed or []:
            self._by_id[detail.id] = detail
            self._order.append(detail.id)

    def list_cards(self) -> list[MeetingCard]:
        details = [self._by_id[mid] for mid in self._order]
        details.sort(key=lambda d: _STATUS_ORDER[d.status])
        return [_card_from_detail(d) for d in details]

    def find_detail(self, meeting_id: str) -> MeetingDetail | None:
        return self._by_id.get(meeting_id)

    def submit_new(self, req: NewMeetingRequest) -> MeetingDetail:
        meeting_id = f"m-new-{uuid.uuid4().hex[:8]}"
        now = _now_iso()
        detail = MeetingDetail(
            id=meeting_id,
            status=MeetingStatus.PENDING,
            counterparty_name=req.counterparty_name,
            counterparty_principal_id=req.counterparty_principal_id,
            proposed_time=None,
            duration_minutes=req.duration_minutes,
            title=req.title,
            last_updated=now,
            agreement_hash=None,
            ledger=[
                LedgerEntry(
                    timestamp=now,
                    actor="you",
                    operation="proposal",
                    action=f"requested meeting (window: {req.when_window})",
                    payload_hash_preview="pending",
                ),
            ],
            reasoning=(
                f"Your butler is reaching out to {req.counterparty_name} "
                "now to find a slot."
            ),
        )
        self._by_id[meeting_id] = detail
        self._order.append(meeting_id)
        return detail
