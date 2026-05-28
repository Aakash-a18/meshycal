"""FastAPI app factory.

In M1.2 the app hosts N synthetic principals in one process. Each
request specifies which principal's view to render via `?as=<alias>`
(default "alice"). The principal registry is built in the lifespan
handler so its SQLite-backed substrate ends up on the event-loop
thread (Mesherra's substrate refuses cross-thread access).
"""

from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from meshycal.api.models import (
    MeetingCard,
    MeetingDetail,
    NewMeetingRequest,
)
from meshycal.api.principals import (
    PrincipalRegistry,
    PrincipalSession,
    build_sandbox_registry,
)
from meshycal.api.settings import ApiSettings


def _resolve_data_dir(settings: ApiSettings) -> Path:
    if settings.data_dir:
        return Path(settings.data_dir)
    # Ephemeral dir for M1; M2 will require a configured persistent dir.
    return Path(tempfile.mkdtemp(prefix="meshycal-"))


def _make_lifespan(settings: ApiSettings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        registry = build_sandbox_registry(data_dir=_resolve_data_dir(settings))
        await registry.start_all_listeners()
        app.state.registry = registry
        app.state.settings = settings
        try:
            yield
        finally:
            await registry.stop_all_listeners()
            registry.close_all()

    return lifespan


def _get_session(request: Request, alias: str | None) -> PrincipalSession:
    settings: ApiSettings = request.app.state.settings
    registry: PrincipalRegistry = request.app.state.registry
    chosen = alias or settings.default_principal_alias
    sess = registry.get(chosen)
    if sess is None:
        raise HTTPException(
            status_code=404, detail=f"unknown principal: {chosen}",
        )
    return sess


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings()
    app = FastAPI(
        title="MeshyCal API",
        version="0.0.1",
        lifespan=_make_lifespan(settings),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Handlers are `async` so they run on the event loop, not in a
    # thread pool. The PrincipalRegistry's SQLite-backed ObjectStore
    # and ProvenanceLedger are tied to the thread they were opened on
    # (Mesherra's design); sync handlers would hit
    # "SQLite objects created in a thread…" at request time.

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/principals")
    async def list_principals(request: Request) -> list[dict[str, str]]:
        """Lets the web renderer populate the principal switcher."""
        registry: PrincipalRegistry = request.app.state.registry
        return [
            {
                "alias": s.alias,
                "principal_id": s.principal_id,
                "display_name": s.display_name,
            }
            for s in registry.all()
        ]

    @app.get("/api/meetings", response_model=list[MeetingCard])
    async def list_meetings(
        request: Request,
        as_: str | None = Query(None, alias="as"),
    ) -> list[MeetingCard]:
        return _get_session(request, as_).inbox.list_cards()

    @app.get("/api/meetings/{meeting_id}", response_model=MeetingDetail)
    async def get_meeting(
        meeting_id: str,
        request: Request,
        as_: str | None = Query(None, alias="as"),
    ) -> MeetingDetail:
        detail = _get_session(request, as_).inbox.find_detail(meeting_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        return detail

    @app.post(
        "/api/meetings",
        response_model=MeetingCard,
        status_code=201,
    )
    async def submit_meeting(
        req: NewMeetingRequest,
        request: Request,
        as_: str | None = Query(None, alias="as"),
    ) -> MeetingCard:
        sess = _get_session(request, as_)
        try:
            detail = sess.inbox.submit_new(req)
        except NotImplementedError as e:
            # M1.3 wires this. Until then, surface clearly.
            raise HTTPException(status_code=501, detail=str(e))
        return MeetingCard.model_validate(
            detail.model_dump(include=set(MeetingCard.model_fields.keys()))
        )

    return app
