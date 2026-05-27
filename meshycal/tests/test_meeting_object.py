"""Unit tests for MeetingObjectState — the structured state that lives
inside a MeetingObject's Mesherra Object.

Per ``docs/ARCHITECTURE.md`` §3.2, MeetingObject is the canonical
"agreement" produced by a successful negotiation. It is a real Mesherra
Object (single owner = the initiator; live-reference-promoted to the
counterpart). This file tests the Pydantic schema for what lives inside
the Object's ``state`` field. The Mesherra Object wrapper provides the
``content_hash`` / ``object_version`` / ``owner`` machinery; MeetingObject
just specifies the structured fields.

Frozen + extra="forbid" so a typo or stray field is caught at the model
boundary rather than at the wire.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from mesherra.crypto.primitives import canonical_json, content_hash
from meshycal.meeting_object import (
    MEETING_OBJECT_SCHEMA,
    MeetingObjectState,
)


@pytest.fixture
def base_state() -> dict[str, Any]:
    proposal = {"candidates": ["2026-06-01T10:00:00Z"], "duration_minutes": 30}
    return dict(
        time="2026-06-01T10:00:00Z",
        duration_minutes=30,
        timezone="UTC",
        title="planning sync",
        location=None,
        attendees=[],
        agreement_hash=content_hash(canonical_json(proposal)),
        provenance_pointer=None,
    )


class TestSchemaConstant:
    def test_schema_ref(self) -> None:
        assert MEETING_OBJECT_SCHEMA == "meshycal.scheduling/meeting-v1"


class TestConstruction:
    def test_constructs_minimal(self, base_state: dict[str, Any]) -> None:
        m = MeetingObjectState(**base_state)
        assert m.time == "2026-06-01T10:00:00Z"
        assert m.duration_minutes == 30
        assert m.timezone == "UTC"
        assert m.title == "planning sync"
        assert m.location is None
        assert m.attendees == []
        assert m.provenance_pointer is None

    def test_constructs_with_location_and_attendees(
        self, base_state: dict[str, Any]
    ) -> None:
        m = MeetingObjectState(
            **{
                **base_state,
                "location": "Mesherra HQ, Room 3",
                "attendees": ["alice@phase4.local", "bob@phase4.local"],
            }
        )
        assert m.location == "Mesherra HQ, Room 3"
        assert m.attendees == ["alice@phase4.local", "bob@phase4.local"]

    def test_provenance_pointer_threading(
        self, base_state: dict[str, Any]
    ) -> None:
        m = MeetingObjectState(**{**base_state, "provenance_pointer": "ctx-negotiation-1"})
        assert m.provenance_pointer == "ctx-negotiation-1"

    def test_frozen(self, base_state: dict[str, Any]) -> None:
        m = MeetingObjectState(**base_state)
        with pytest.raises(ValidationError):
            m.time = "2026-06-02T10:00:00Z"  # type: ignore[misc]


class TestValidation:
    @pytest.mark.parametrize(
        "field,bad_value",
        [
            ("time", ""),
            ("timezone", ""),
            ("title", ""),
            ("agreement_hash", ""),
            ("agreement_hash", "tooshort"),
            ("agreement_hash", "Z" * 64),  # non-hex
        ],
    )
    def test_rejects_malformed_field(
        self, base_state: dict[str, Any], field: str, bad_value: Any
    ) -> None:
        with pytest.raises(ValidationError):
            MeetingObjectState(**{**base_state, field: bad_value})

    def test_duration_minutes_must_be_positive(
        self, base_state: dict[str, Any]
    ) -> None:
        with pytest.raises(ValidationError):
            MeetingObjectState(**{**base_state, "duration_minutes": 0})
        with pytest.raises(ValidationError):
            MeetingObjectState(**{**base_state, "duration_minutes": -5})

    def test_extra_field_rejected(self, base_state: dict[str, Any]) -> None:
        # Defense against silent drift: any extra field in the wire payload
        # should error rather than be carried as opaque metadata.
        with pytest.raises(ValidationError):
            MeetingObjectState(**{**base_state, "extra_field": "leak"})

    def test_uppercase_hash_rejected(
        self, base_state: dict[str, Any]
    ) -> None:
        # Lowercase-hex only, matching the rest of Mesherra's content_hash
        # discipline.
        proposal = {"candidates": ["X"], "duration_minutes": 30}
        upper_hash = content_hash(canonical_json(proposal)).upper()
        with pytest.raises(ValidationError):
            MeetingObjectState(**{**base_state, "agreement_hash": upper_hash})


class TestRoundTrip:
    """The model is what lives inside a Mesherra Object's ``state`` field.
    Going through model_dump → model_validate must yield an equivalent
    instance — otherwise the cross-process reconstruction in the
    on_object_update callback would lose data."""

    def test_round_trip_preserves_state(self, base_state: dict[str, Any]) -> None:
        m1 = MeetingObjectState(
            **{
                **base_state,
                "location": "Bldg A",
                "attendees": ["alice@phase4.local"],
                "provenance_pointer": "ctx-1",
            }
        )
        as_dict = m1.model_dump()
        m2 = MeetingObjectState.model_validate(as_dict)
        assert m1 == m2

    def test_two_instances_same_state_same_canonical_bytes(
        self, base_state: dict[str, Any]
    ) -> None:
        # Same state → same model_dump_json → same canonical hash when
        # wrapped in a Mesherra Object. This is what gives the receiver
        # the ability to detect "the owner mutated the meeting state."
        m1 = MeetingObjectState(**base_state)
        m2 = MeetingObjectState(**base_state)
        assert m1.model_dump_json() == m2.model_dump_json()
