"""Wire-shape models the web renderer consumes.

These are NOT Mesherra Objects. They're projections — what one card
looks like in the inbox UI, and what the receipt view shows when you
click into one. The fields here are deliberately renderer-facing
(display names, human time strings, short-hash previews); the
substrate that backs them (CalendarObject, MeetingObject,
ProvenanceLedger) is not exposed.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MeetingStatus(str, Enum):
    """Lifecycle of one meeting from the user's inbox point of view.

    pending  — agent surfaced this to the user; needs their call
    accepted — both sides agreed; sitting on the user's calendar
    declined — one side said no; here for auditability
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class MeetingCard(BaseModel):
    """One row in the inbox list view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: MeetingStatus
    counterparty_name: str = Field(description="Display name shown on the card.")
    counterparty_principal_id: str = Field(
        description="Mesherra principal ID — used internally, not shown."
    )
    proposed_time: str | None = Field(
        default=None,
        description="ISO-8601 instant of the proposed slot. None when the "
        "agent has not yet negotiated a slot.",
    )
    duration_minutes: int = Field(gt=0)
    title: str
    last_updated: str = Field(description="ISO-8601 instant the card last changed.")


class LedgerEntry(BaseModel):
    """One residue line in the receipt view.

    Carries BOTH the substrate-shaped `operation` (matches Mesherra's
    `Operation` enum — `proposal`, `acceptance`, `rejection`, `promote`,
    `subscribe`, `object_update`, …) and a renderer-side `action`
    string composed by the api. A second host surface (Slack, iOS) is
    free to render its own prose off `operation` and ignore `action`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: str = Field(description="ISO-8601 instant of the entry.")
    actor: str = Field(description='Display name ("you" or counterparty name).')
    operation: str = Field(
        description="Substrate Operation enum value (proposal/acceptance/…)."
    )
    action: str = Field(
        description="Pre-composed human prose. Renderers may override.",
    )
    payload_hash_preview: str = Field(
        description="First 16 chars of the residue payload_hash."
    )


class MeetingDetail(MeetingCard):
    """Detail view: the inbox card plus the receipt.

    `agreement_hash` is None until a canonical MeetingObject exists —
    i.e. only set once the meeting is ACCEPTED. When present, it is the
    *full* 64-hex sha256 of the canonical MeetingObjectState (matches
    the `^[0-9a-f]{64}$` constraint enforced in
    `meeting_object.py::MeetingObjectState`). Renderers may show a
    short prefix; the api projection is always the full hash so the
    type contract is honest. The ledger and reasoning are present for
    any state so the user can see the audit trail even on declines.
    """

    agreement_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    ledger: list[LedgerEntry] = Field(default_factory=list)
    reasoning: str = ""


class NewMeetingRequest(BaseModel):
    """Wire body for POST /api/meetings.

    In the skeleton this is held in an in-memory inbox. Step 4 swaps
    this for `SchedulingAgent.propose_meeting_to`, at which point
    `when_window` becomes a list of candidate slot strings the agent
    negotiates over.
    """

    model_config = ConfigDict(extra="forbid")

    counterparty_principal_id: str
    counterparty_name: str
    duration_minutes: int = Field(gt=0)
    when_window: str = Field(
        description="Free-form window ('next week', 'this Wed afternoon'). "
        "The agent narrows this to concrete slots."
    )
    title: str
