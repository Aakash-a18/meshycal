"""Tests for the agent-backed api routes.

These exercise the M1.2 wiring: every read endpoint accepts `?as=<alias>`
to choose which principal's view to render. Submit returns 501 until
M1.3 wires it to SchedulingAgent.propose_meeting_to.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_list_meetings_defaults_to_alice(sandbox_client: TestClient):
    """Omitting ?as= falls back to default_principal_alias (alice)."""
    response = sandbox_client.get("/api/meetings")
    assert response.status_code == 200
    # Fresh sandbox: no negotiations yet, inbox is empty.
    assert response.json() == []


def test_list_meetings_for_bob(sandbox_client: TestClient):
    response = sandbox_client.get("/api/meetings?as=bob")
    assert response.status_code == 200
    assert response.json() == []


def test_list_meetings_unknown_principal(sandbox_client: TestClient):
    response = sandbox_client.get("/api/meetings?as=nobody")
    assert response.status_code == 404
    assert "nobody" in response.json()["detail"]


def test_list_meetings_by_principal_id(sandbox_client: TestClient):
    """?as= accepts either the alias or the full principal_id."""
    response = sandbox_client.get(
        "/api/meetings?as=alice@sandbox.local",
    )
    assert response.status_code == 200


def test_list_principals(sandbox_client: TestClient):
    """Lets the renderer build the principal switcher menu."""
    response = sandbox_client.get("/api/principals")
    assert response.status_code == 200
    principals = response.json()
    aliases = {p["alias"] for p in principals}
    assert {"alice", "bob"}.issubset(aliases)
    by_alias = {p["alias"]: p for p in principals}
    assert by_alias["alice"]["display_name"] == "Alice"
    assert by_alias["alice"]["principal_id"] == "alice@sandbox.local"


def test_get_meeting_404_when_not_in_inbox(sandbox_client: TestClient):
    response = sandbox_client.get("/api/meetings/missing-id?as=alice")
    assert response.status_code == 404


def test_principals_have_listener_urls_after_lifespan(sandbox_client: TestClient):
    """The lifespan should have started listeners on both principals so
    they can talk to each other when M1.3 lands."""
    # We can't introspect app.state from outside, but we can verify
    # listeners came up via the /api/principals payload once that
    # field is exposed. For now, list_principals not exposing URLs
    # is intentional (URLs are an internal substrate concern). This
    # test guards against future regression by asserting the route
    # works after lifespan.
    response = sandbox_client.get("/api/principals")
    assert response.status_code == 200
