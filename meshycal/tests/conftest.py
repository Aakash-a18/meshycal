"""Shared pytest fixtures for meshycal tests.

The api tests use TestClient as a context manager so the FastAPI
lifespan handler fires — that's the only way the PrincipalRegistry
ends up on the same thread as the request handlers (Mesherra's
SQLite-backed substrate refuses cross-thread access). Per-test
isolation comes from setting MESHYCAL_DATA_DIR to pytest's
`tmp_path`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from meshycal.api import create_app


@pytest.fixture()
def sandbox_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """TestClient wired to a fresh sandbox registry (alice + bob).

    The lifespan builds the registry on the event-loop thread so
    SQLite connections are usable from request handlers.
    """
    monkeypatch.setenv("MESHYCAL_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as client:
        yield client
