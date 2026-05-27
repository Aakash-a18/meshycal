"""MeetingObject — the canonical agreement produced by a MeshyCal
negotiation.

Per ``docs/ARCHITECTURE.md`` §3.2: a MeetingObject is a real Mesherra
``Object`` (singular owner = the initiator, live-reference-promoted to
the counterpart). This module defines the structured **state** that
lives inside the Mesherra Object's ``state`` field — the Mesherra Object
wrapper handles content-hash anchoring, owner-binding, monotonic
versioning, layer membership; MeshyCal just specifies which fields are
in the state and validates them.

The schema URI is published as a constant so the SchedulingAgent and
the on_object_update callback can both refer to the same identifier.
(A Schema Registry publication step is deferred per §11.)

Frozen + ``extra="forbid"`` — defense against silent drift on the wire
between MeshyCal and any downstream consumer reading the Object's state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MEETING_OBJECT_SCHEMA: Literal["meshycal.scheduling/meeting-v1"] = (
    "meshycal.scheduling/meeting-v1"
)


class MeetingObjectState(BaseModel):
    """The structured state inside a MeetingObject's Mesherra Object.

    Maps the conceptual MeetingObject fields documented in ARCH §3.2 to
    Pydantic-validated wire-safe values:

    * ``time`` — ISO 8601 UTC start time of the meeting
    * ``duration_minutes`` — strictly positive
    * ``timezone`` — display timezone (IANA or short label)
    * ``title`` — meeting title; scoped per-viewer per policy template
    * ``location`` — optional; scoped per-viewer per policy template
    * ``attendees`` — optional; principal IDs; scoped per-viewer
    * ``agreement_hash`` — SHA-256/JCS of the agreed Proposal that
      produced this Meeting. The cryptographic link from the
      negotiation chain to the resulting canonical agreement.
    * ``provenance_pointer`` — optional anchor (context_id or task_id)
      pointing at the Residue chain of the negotiation that produced
      this MeetingObject. Carries no signing weight on its own — the
      Mesherra Object's content_hash + the Promotion's owner_signature
      are the load-bearing trust artefacts. This is a navigational
      pointer for auditors.

    What is NOT in this state:
    * ``meeting_id`` — handled by the Mesherra ``Object.object_id`` and
      the ``Promotion.promotion_id``; not duplicated here.
    * ``owner``/``counterpart`` — handled by the Mesherra Object's
      ``owner`` field and the Promotion's ``receiver`` field
      respectively.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    time: str = Field(min_length=1)
    duration_minutes: int = Field(ge=1)
    timezone: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str | None = None
    attendees: list[str] = Field(default_factory=list)
    agreement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_pointer: str | None = None
