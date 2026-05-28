"""Tests for the /api/meetings endpoints — the inbox card list and detail
view the web renderer renders. In the skeleton step the responses are
synthetic; later steps wire them to a real SchedulingAgent + ledger."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meshycal.api import create_app
from meshycal.api.models import MeetingCard, MeetingStatus


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_list_returns_multiple_cards_in_different_states(client: TestClient):
    response = client.get("/api/meetings")
    assert response.status_code == 200
    cards = response.json()
    assert isinstance(cards, list)
    assert len(cards) >= 3
    statuses = {c["status"] for c in cards}
    assert {"pending", "accepted", "declined"}.issubset(statuses)


def test_list_cards_validate_as_meeting_card(client: TestClient):
    """Every card on the wire must validate against the MeetingCard
    pydantic model — the renderer relies on the shape."""
    response = client.get("/api/meetings")
    for raw in response.json():
        card = MeetingCard.model_validate(raw)
        assert card.id
        assert card.counterparty_name
        assert card.counterparty_principal_id
        assert card.proposed_time
        assert card.duration_minutes > 0


def test_pending_card_is_first_in_inbox(client: TestClient):
    """Inbox order: pending (needs your attention) → accepted → declined.
    A user opening the inbox should see actionable items at the top."""
    response = client.get("/api/meetings")
    cards = response.json()
    pending_idx = next(i for i, c in enumerate(cards) if c["status"] == "pending")
    accepted_idx = next(i for i, c in enumerate(cards) if c["status"] == "accepted")
    declined_idx = next(i for i, c in enumerate(cards) if c["status"] == "declined")
    assert pending_idx < accepted_idx < declined_idx


def test_meeting_status_enum_round_trip():
    """A round-trip safety net so the wire string stays aligned with the
    enum the renderer keys off."""
    for s in ("pending", "accepted", "declined"):
        assert MeetingStatus(s).value == s
