"""Tests for /api/meetings/{id} — the receipt detail view.

The detail view is the moment the user actually sees the trust layer:
who said what, when, and the cryptographic proof. In the skeleton step
the contents are synthetic; later steps wire them to the real
ProvenanceLedger and MeetingObject.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meshycal.api import create_app
from meshycal.api.models import LedgerEntry, MeetingDetail, MeetingStatus


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_detail_returns_full_receipt_for_accepted_meeting(client: TestClient):
    response = client.get("/api/meetings/m-accepted-001")
    assert response.status_code == 200
    detail = MeetingDetail.model_validate(response.json())
    assert detail.status is MeetingStatus.ACCEPTED
    assert detail.agreement_hash is not None
    # Must be the full 64-hex sha256 — matches the constraint
    # `MeetingObjectState.agreement_hash` enforces in
    # meeting_object.py. The api never truncates; renderers may.
    assert len(detail.agreement_hash) == 64
    assert all(c in "0123456789abcdef" for c in detail.agreement_hash)
    assert len(detail.ledger) >= 1
    assert detail.reasoning


def test_detail_has_no_agreement_hash_for_pending(client: TestClient):
    """An accepted meeting has a canonical MeetingObject (hash present).
    A pending one does not — there's no agreement yet."""
    response = client.get("/api/meetings/m-pending-001")
    assert response.status_code == 200
    detail = MeetingDetail.model_validate(response.json())
    assert detail.status is MeetingStatus.PENDING
    assert detail.agreement_hash is None


def test_detail_404_on_unknown_id(client: TestClient):
    response = client.get("/api/meetings/does-not-exist")
    assert response.status_code == 404


def test_ledger_entries_validate(client: TestClient):
    response = client.get("/api/meetings/m-accepted-001")
    detail = MeetingDetail.model_validate(response.json())
    for entry in detail.ledger:
        assert isinstance(entry, LedgerEntry)
        assert entry.timestamp
        assert entry.actor
        assert entry.action
        # operation is the substrate Mesherra Operation enum string —
        # second-renderer authors can humanize from this instead of
        # leaning on the api's `action` prose.
        assert entry.operation


def test_ledger_operations_match_substrate_enum(client: TestClient):
    """Every operation value must appear in Mesherra's Operation enum.
    Drift here means the api is inventing operations the substrate
    doesn't know about."""
    from mesherra.models.primitives import Operation

    valid = {o.value for o in Operation}
    response = client.get("/api/meetings/m-accepted-001")
    detail = MeetingDetail.model_validate(response.json())
    for entry in detail.ledger:
        assert entry.operation in valid, f"unknown operation: {entry.operation}"


def test_invalid_agreement_hash_format_rejected():
    """A 32-hex value (the OLD fixture shape) must not validate against
    the model — proves the api projection cannot silently lie about
    the canonical hash length."""
    import pytest as _pytest

    from meshycal.api.models import MeetingDetail as _MD

    with _pytest.raises(Exception):
        _MD(
            id="x",
            status=MeetingStatus.ACCEPTED,
            counterparty_name="X",
            counterparty_principal_id="x@sandbox.local",
            proposed_time=None,
            duration_minutes=30,
            title="t",
            last_updated="2026-05-27T00:00:00Z",
            agreement_hash="b7c1e4a9d22f60185df1c0a3e8b5f7d4",  # 32 hex
        )
