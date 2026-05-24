"""FastAPI bridge for the Phase 4 prototype.

Runs the existing Phase 3 mesherra backend over HTTP so the static
``index.html`` can render real cryptographic outputs instead of
hardcoded animation timings + fake hashes.

Endpoints:

* ``GET  /healthz`` — liveness probe.
* ``POST /scenarios/two-party/run`` — runs a real two-party Mesherra
  negotiation; returns structured payloads, hashes, and both ledgers'
  entries as a :class:`TwoPartyResult`.
* ``GET  /scenarios/four-party/run`` — placeholder; returns 501 with a
  ``not_yet_implemented`` body.
* ``GET  /scenarios/cascading/run`` — placeholder; same shape.

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


@app.get(
    "/scenarios/four-party/run",
    response_model=NotYetImplemented,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
async def run_four_party_endpoint() -> NotYetImplemented:
    return NotYetImplemented(
        scenario="four-party group find",
        why=(
            "Requires a coordinator pattern layered on top of Mesherra's "
            "two-party primitive. Mesherra's policy + receipt machinery "
            "applies per-bilateral with no change."
        ),
        estimate="3-5 days backend + 1-2 days UI",
    )


@app.get(
    "/scenarios/cascading/run",
    response_model=NotYetImplemented,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
async def run_cascading_endpoint() -> NotYetImplemented:
    return NotYetImplemented(
        scenario="cascading reschedule",
        why=(
            "Requires an LLM-driven scheduling agent that reasons about "
            "tradeoffs (\"can I move my meeting with C to free this slot?\"). "
            "Requires a strategic call on real LLM API vs scripted "
            "deterministic reasoner."
        ),
        estimate="1-2 weeks backend + 3-5 days UI",
    )
