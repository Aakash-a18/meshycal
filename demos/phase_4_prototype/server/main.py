"""FastAPI bridge for the Phase 4 prototype.

Runs the existing Phase 3 mesherra backend over HTTP so the static
``index.html`` can render real cryptographic outputs instead of
hardcoded animation timings + fake hashes.

Endpoints:

* ``GET  /healthz`` — liveness probe.
* ``POST /scenarios/two-party/run`` — runs a real two-party Mesherra
  negotiation; returns structured payloads, hashes, and both ledgers'
  entries as a :class:`TwoPartyResult`.
* ``POST /scenarios/four-party/run`` — runs a real four-party group-find
  negotiation; returns a :class:`FourPartyResult`.
* ``POST /scenarios/cascading/run`` — runs the three-principal cascading
  reschedule (Iris→Marius, Marius↔Atlas reasoner-driven sub-exchange,
  Marius→Iris); returns a :class:`CascadingResult`.

Run locally:

    uv run --extra dev uvicorn server.main:app --reload --port 8080

The HTML prototype's JS will call this via ``fetch`` from the local
file or a sibling origin. CORS is wide-open here because the prototype
is loaded from ``file://`` URLs in normal use — narrow this when
deploying.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from .cascading import CascadingResult, run_cascading
from .group_negotiation import FourPartyResult, run_four_party
from .scenarios import NotYetImplemented, TwoPartyResult, run_two_party


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(
    title="MeshyCal Phase 4 prototype bridge",
    version="0.4.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # prototype-only; tighten before any deploy
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "meshycal-phase4-bridge"}


@app.post(
    "/scenarios/two-party/run",
    response_model=TwoPartyResult,
)
async def run_two_party_endpoint() -> TwoPartyResult:
    """Run a real Phase 3 two-party negotiation; return structured data."""
    try:
        return await run_two_party()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"two-party scenario failed: {e!r}",
        ) from e


@app.post(
    "/scenarios/four-party/run",
    response_model=FourPartyResult,
)
async def run_four_party_endpoint() -> FourPartyResult:
    """Run a real Phase 3 four-party group-find negotiation."""
    try:
        return await run_four_party()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"four-party scenario failed: {e!r}",
        ) from e


@app.post(
    "/scenarios/cascading/run",
    response_model=CascadingResult,
)
async def run_cascading_endpoint() -> CascadingResult:
    """Run the three-principal cascading-reschedule scenario."""
    try:
        return await run_cascading()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"cascading scenario failed: {e!r}",
        ) from e
