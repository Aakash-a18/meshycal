"""FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from meshycal.api._fixtures import seed_details
from meshycal.api.inbox import InMemoryInbox
from meshycal.api.models import (
    MeetingCard,
    MeetingDetail,
    NewMeetingRequest,
)
from meshycal.api.settings import ApiSettings


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings()
    app = FastAPI(title="MeshyCal API", version="0.0.1")
    app.state.inbox = InMemoryInbox(seed=seed_details())

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/meetings", response_model=list[MeetingCard])
    def list_meetings(request: Request) -> list[MeetingCard]:
        return request.app.state.inbox.list_cards()

    @app.get("/api/meetings/{meeting_id}", response_model=MeetingDetail)
    def get_meeting(meeting_id: str, request: Request) -> MeetingDetail:
        detail = request.app.state.inbox.find_detail(meeting_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        return detail

    @app.post(
        "/api/meetings",
        response_model=MeetingCard,
        status_code=201,
    )
    def submit_meeting(req: NewMeetingRequest, request: Request) -> MeetingCard:
        detail = request.app.state.inbox.submit_new(req)
        return MeetingCard.model_validate(
            detail.model_dump(include=set(MeetingCard.model_fields.keys()))
        )

    return app
