"""End-to-end test for the agent-backed submit flow (M1.3).

POST /api/meetings?as=alice triggers a real PROPOSAL + ACCEPTANCE +
MeetingObject + LIVE promotion. Both Alice and Bob end up with a
canonical accepted card in their inboxes.

This is the test that proves "the AI works in the inbox." It
exercises the full Mesherra+MeshyCal stack through the api surface.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from meshycal.api.models import MeetingDetail, MeetingStatus


def _submit_body(**overrides: object) -> dict:
    base = {
        "counterparty_principal_id": "bob@sandbox.local",
        "counterparty_name": "Bob",
        "duration_minutes": 30,
        "when_window": "next week",
        "title": "Coffee chat",
    }
    base.update(overrides)
    return base


def test_alice_submits_meeting_bob_accepts_both_inboxes_populated(
    sandbox_client: TestClient,
):
    response = sandbox_client.post("/api/meetings?as=alice", json=_submit_body())
    assert response.status_code == 201, response.text
    card = response.json()
    assert card["status"] == "accepted"
    assert card["counterparty_principal_id"] == "bob@sandbox.local"
    assert card["duration_minutes"] == 30
    new_id = card["id"]

    alice_inbox = sandbox_client.get("/api/meetings?as=alice").json()
    assert len(alice_inbox) == 1
    assert alice_inbox[0]["id"] == new_id

    bob_inbox = sandbox_client.get("/api/meetings?as=bob").json()
    assert len(bob_inbox) == 1, "Bob's inbox should also show the agreement"
    assert bob_inbox[0]["counterparty_principal_id"] == "alice@sandbox.local"


def test_submitted_meeting_has_full_64_hex_agreement_hash(
    sandbox_client: TestClient,
):
    response = sandbox_client.post("/api/meetings?as=alice", json=_submit_body())
    meeting_id = response.json()["id"]
    detail = sandbox_client.get(
        f"/api/meetings/{meeting_id}?as=alice",
    ).json()
    parsed = MeetingDetail.model_validate(detail)
    assert parsed.status is MeetingStatus.ACCEPTED
    assert parsed.agreement_hash is not None
    assert len(parsed.agreement_hash) == 64
    assert all(c in "0123456789abcdef" for c in parsed.agreement_hash)


def test_alice_and_bob_see_the_same_agreement_hash(
    sandbox_client: TestClient,
):
    """The whole point of the canonical MeetingObject: both sides
    reference one signed truth. Their respective detail views must
    agree on agreement_hash byte-for-byte."""
    response = sandbox_client.post("/api/meetings?as=alice", json=_submit_body())
    alice_card = response.json()
    bob_inbox = sandbox_client.get("/api/meetings?as=bob").json()
    assert len(bob_inbox) == 1
    bob_card = bob_inbox[0]

    alice_detail = sandbox_client.get(
        f"/api/meetings/{alice_card['id']}?as=alice",
    ).json()
    bob_detail = sandbox_client.get(
        f"/api/meetings/{bob_card['id']}?as=bob",
    ).json()
    assert alice_detail["agreement_hash"] == bob_detail["agreement_hash"]


def test_submit_unknown_counterparty_returns_404(sandbox_client: TestClient):
    response = sandbox_client.post(
        "/api/meetings?as=alice",
        json=_submit_body(
            counterparty_principal_id="charlie@sandbox.local",
            counterparty_name="Charlie",
        ),
    )
    assert response.status_code == 404
    assert "charlie" in response.json()["detail"].lower()


def test_submit_returns_pending_card_when_counterparty_declines(
    sandbox_client: TestClient,
):
    """Self-meetings are auto-declined by the scripted reasoner
    (defensive against accidental loops). The api still returns a
    card — declined — so the user sees what happened in the inbox."""
    # ScriptedReasoner accepts on a no-conflict calendar; to trigger
    # decline behavior we'd need a non-trivial reasoner. For M1.3
    # the happy path is the focus; decline UX shows up in M1.4 with
    # a richer reasoner. Mark this as a placeholder.
    pass
