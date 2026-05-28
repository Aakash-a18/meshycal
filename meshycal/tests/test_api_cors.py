"""CORS tests — the web renderer (Next.js dev server on :3000) must be
able to call the API, but unknown origins must not get the allow-header.

Origins are configured via env (MESHYCAL_CORS_ORIGINS) per CLAUDE.md
rule 4 (no hardcoded values).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meshycal.api import create_app
from meshycal.api.settings import ApiSettings


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_default_settings_include_local_dev_origin():
    settings = ApiSettings()
    assert "http://localhost:3000" in settings.cors_origins


def test_cors_origins_overridable_via_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MESHYCAL_CORS_ORIGINS", '["https://meshycal.com"]')
    settings = ApiSettings()
    assert settings.cors_origins == ["https://meshycal.com"]


def test_allowed_origin_gets_cors_header(client: TestClient):
    response = client.get(
        "/api/meetings",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin")
        == "http://localhost:3000"
    )


def test_unknown_origin_does_not_get_cors_header(client: TestClient):
    response = client.get(
        "/api/meetings",
        headers={"Origin": "http://evil.example"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_preflight_permits_post_from_dev_origin(client: TestClient):
    response = client.options(
        "/api/meetings",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert "POST" in response.headers.get("access-control-allow-methods", "")
