"""Tests for POST /api/meetings — the 'new meeting' form submission.

In the skeleton step submissions are stored in an in-process inbox
on app.state. Step 4 swaps this for SchedulingAgent.propose_meeting_to.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meshycal.api import create_app
from meshycal.api.models import MeetingCard, MeetingStatus


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _valid_body() -> dict:
    return {
        "counterparty_principal_id": "newperson@sandbox.local",
        "counterparty_name": "New Person",
        "duration_minutes": 30,
        "when_window": "next week",
        "title": "Intro call",
    }


def test_post_creates_pending_card(client: TestClient):
    response = client.post("/api/meetings", json=_valid_body())
    assert response.status_code == 201
    card = MeetingCard.model_validate(response.json())
    assert card.status is MeetingStatus.PENDING
    assert card.counterparty_name == "New Person"
    assert card.duration_minutes == 30
    assert card.title == "Intro call"
    assert card.id


def test_post_then_get_shows_new_card_in_inbox(client: TestClient):
    """A submitted meeting must appear in the inbox list — proves we
    persist it (in-memory) and that the list endpoint reads from the
    same store the POST writes to."""
    response = client.post("/api/meetings", json=_valid_body())
    new_id = response.json()["id"]
    listed = client.get("/api/meetings").json()
    assert any(c["id"] == new_id for c in listed)


def test_post_detail_endpoint_returns_new_meeting(client: TestClient):
    new_id = client.post("/api/meetings", json=_valid_body()).json()["id"]
    detail = client.get(f"/api/meetings/{new_id}").json()
    assert detail["id"] == new_id
    assert detail["agreement_hash"] is None
    assert detail["status"] == "pending"


def test_post_rejects_invalid_duration(client: TestClient):
    body = _valid_body() | {"duration_minutes": 0}
    response = client.post("/api/meetings", json=body)
    assert response.status_code == 422


def test_post_rejects_missing_counterparty(client: TestClient):
    body = _valid_body()
    body.pop("counterparty_principal_id")
    response = client.post("/api/meetings", json=body)
    assert response.status_code == 422


def test_inbox_state_isolated_between_apps():
    """Each create_app() instance must have its own in-memory inbox —
    no leakage via a module-level global."""
    app_a = TestClient(create_app())
    app_b = TestClient(create_app())
    app_a.post("/api/meetings", json=_valid_body())
    ids_a = {c["id"] for c in app_a.get("/api/meetings").json()}
    ids_b = {c["id"] for c in app_b.get("/api/meetings").json()}
    new_in_a = ids_a - ids_b
    assert len(new_in_a) == 1
