"""Smoke test for the FastAPI app — proves the import path and route
table are wired before we add real endpoints on top."""

from __future__ import annotations

from fastapi.testclient import TestClient

from meshycal.api import create_app


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
