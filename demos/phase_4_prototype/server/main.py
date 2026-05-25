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
from .sandbox_models import (
    SandboxAck,
    SandboxPrincipal,
    SandboxPrincipalIn,
    SandboxRequestSpec,
    SandboxRunResult,
    SandboxSessionCreated,
    SandboxSessionState,
)
from .sandbox_orchestrator import SandboxOrchestratorError, run_sandbox_two_party
from .sandbox_session import session_store
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


# =====================================================================
#  Sandbox endpoints — dynamic principals, real Mesherra exchanges,
#  optional LLM-backed reasoners.
# =====================================================================


def _principal_or_404(token: str, principal_id: str) -> SandboxPrincipal:
    try:
        record = session_store.get_session(token)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found or expired",
        ) from e
    if principal_id not in record.principals:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"principal {principal_id!r} not in session",
        )
    return record.principals[principal_id]


@app.post(
    "/sandbox/session",
    response_model=SandboxSessionCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_sandbox_session() -> SandboxSessionCreated:
    """Create a fresh sandbox session seeded with the synthetic default
    principals (Iris, Marius, Atlas)."""
    record = session_store.create()
    return SandboxSessionCreated(
        session_token=record.token,
        expires_at=record.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        principals=list(record.principals.values()),
    )


@app.get(
    "/sandbox/session/{token}",
    response_model=SandboxSessionState,
)
async def get_sandbox_session(token: str) -> SandboxSessionState:
    try:
        record = session_store.get_session(token)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found or expired",
        ) from e
    return SandboxSessionState(
        session_token=record.token,
        expires_at=record.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        principals=list(record.principals.values()),
    )


@app.put(
    "/sandbox/session/{token}/principal/{principal_id:path}",
    response_model=SandboxPrincipal,
)
async def upsert_principal(
    token: str,
    principal_id: str,
    body: SandboxPrincipalIn,
) -> SandboxPrincipal:
    """Add or replace a principal. Accepts ``api_key`` on the body; the
    key is stored separately and is NEVER returned by any GET. The path
    {principal_id} must match the body's id."""
    if body.id != principal_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="principal id in path and body must match",
        )
    try:
        session_store.get_session(token)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found or expired",
        ) from e
    # Split the api_key off so the stored shape carries no key.
    principal = SandboxPrincipal(
        id=body.id,
        display_name=body.display_name,
        color_slot=body.color_slot,
        calendar=body.calendar,
        policy=body.policy,
        reasoner=body.reasoner,
    )
    session_store.upsert_principal(token, principal, body.api_key)
    return principal


@app.delete(
    "/sandbox/session/{token}/principal/{principal_id:path}",
    response_model=SandboxAck,
)
async def delete_principal(token: str, principal_id: str) -> SandboxAck:
    try:
        session_store.get_session(token)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found or expired",
        ) from e
    session_store.delete_principal(token, principal_id)
    return SandboxAck()


@app.delete(
    "/sandbox/session/{token}",
    response_model=SandboxAck,
)
async def destroy_sandbox_session(token: str) -> SandboxAck:
    session_store.destroy(token)
    return SandboxAck()


@app.post(
    "/sandbox/session/{token}/run",
    response_model=SandboxRunResult,
)
async def run_sandbox_endpoint(
    token: str,
    body: SandboxRequestSpec,
) -> SandboxRunResult:
    """Fire a scheduling request through the real Mesherra trust layer.

    Phase 1: 2-party only. 3-party cascading reschedule will return 501
    until Phase 2 lands.
    """
    try:
        record = session_store.get_session(token)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found or expired",
        ) from e
    sender = record.principals.get(body.sender_id)
    recipient = record.principals.get(body.recipient_id)
    if sender is None or recipient is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sender or recipient not in session",
        )
    # Read api_keys from the store, pass into orchestrator. Never expose.
    api_keys: dict[str, str] = {}
    for pid in (sender.id, recipient.id):
        k = session_store.read_api_key(token, pid)
        if k:
            api_keys[pid] = k
    try:
        return await run_sandbox_two_party(
            sender=sender,
            recipient=recipient,
            request=body,
            api_keys=api_keys,
        )
    except SandboxOrchestratorError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"sandbox run failed: {e!r}",
        ) from e
