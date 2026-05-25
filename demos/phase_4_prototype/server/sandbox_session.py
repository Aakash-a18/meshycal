"""In-memory session store for the sandbox.

A session holds:
  - principals: dict[principal_id, SandboxPrincipal]   (no api keys here)
  - api_keys:   dict[principal_id, str]                (separate, sensitive)
  - expires_at: datetime, refreshed on every touch

Sessions live in process memory. They are gone on server restart. That's
intentional — the sandbox is an R&D environment, not a system of record.
The frontend re-seeds defaults if its stored session_token doesn't
resolve on startup.

Sensitive-field discipline:
  - api_keys are never returned by any read method.
  - api_keys are never logged.
  - The serialized session principals (returned to the frontend) carry
    no api_key field.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .sandbox_models import (
    SandboxEvent,
    SandboxPolicy,
    SandboxPrincipal,
    SandboxReasonerConfig,
)

SESSION_TTL_MINUTES = 60


# --- Default seed principals (synthetic — Rule 3 in CLAUDE.md) ------------
# These match the frontend's seedDefaultPrincipals() in sandbox.html.

_DEFAULT_ALLOW = ["candidates", "duration_minutes", "constraint_hints"]
_DEFAULT_BLOCK = ["calendar_titles", "attendee_emails"]


def _default_policy() -> SandboxPolicy:
    return SandboxPolicy(
        outbound_allow=list(_DEFAULT_ALLOW),
        outbound_block=list(_DEFAULT_BLOCK),
        inbound_allow=list(_DEFAULT_ALLOW),
        max_cascade_depth=1,
    )


def _default_reasoner() -> SandboxReasonerConfig:
    return SandboxReasonerConfig(provider="scripted")


def _default_principals() -> list[SandboxPrincipal]:
    return [
        SandboxPrincipal(
            id="iris@sandbox.local",
            display_name="Iris",
            color_slot=0,
            calendar=[
                SandboxEvent(time="09:00", duration=60, title="morning-standup",
                             attendees="team", is_blocking=False),
                SandboxEvent(time="11:00", duration=30, title="focus-block",
                             attendees="solo", is_blocking=False),
            ],
            policy=_default_policy(),
            reasoner=_default_reasoner(),
        ),
        SandboxPrincipal(
            id="marius@sandbox.local",
            display_name="Marius",
            color_slot=1,
            calendar=[
                SandboxEvent(time="10:00", duration=60, title="weekly-review",
                             attendees="team", is_blocking=False),
                SandboxEvent(time="14:00", duration=45, title="project-sync",
                             attendees="atlas", is_blocking=True),
                SandboxEvent(time="15:30", duration=30, title="1-on-1",
                             attendees="report", is_blocking=False),
            ],
            policy=_default_policy(),
            reasoner=_default_reasoner(),
        ),
        SandboxPrincipal(
            id="atlas@sandbox.local",
            display_name="Atlas",
            color_slot=2,
            calendar=[
                SandboxEvent(time="14:00", duration=45, title="project-sync",
                             attendees="marius", is_blocking=True),
            ],
            policy=_default_policy(),
            reasoner=_default_reasoner(),
        ),
    ]


# --- Session record -------------------------------------------------------


@dataclass
class _SessionRecord:
    token: str
    expires_at: datetime
    principals: dict[str, SandboxPrincipal] = field(default_factory=dict)
    api_keys: dict[str, str] = field(default_factory=dict)


# --- Store ----------------------------------------------------------------


class SandboxSessionStore:
    """Thread-safe in-memory session store with idle TTL."""

    def __init__(self, ttl_minutes: int = SESSION_TTL_MINUTES) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionRecord] = {}
        self._ttl = timedelta(minutes=ttl_minutes)

    # ------ lifecycle

    def create(self) -> _SessionRecord:
        """Create a new session with synthetic default principals."""
        token = secrets.token_urlsafe(24)
        rec = _SessionRecord(token=token, expires_at=self._fresh_expiry())
        for p in _default_principals():
            rec.principals[p.id] = p
        with self._lock:
            self._sessions[token] = rec
        return rec

    def destroy(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    # ------ principal CRUD

    def get_session(self, token: str) -> _SessionRecord:
        """Return the live session record, refreshing its TTL. Raises
        KeyError if missing or expired."""
        self._sweep_expired()
        with self._lock:
            rec = self._sessions.get(token)
            if rec is None:
                raise KeyError(token)
            rec.expires_at = self._fresh_expiry()
            return rec

    def upsert_principal(
        self,
        token: str,
        principal: SandboxPrincipal,
        api_key: str | None,
    ) -> SandboxPrincipal:
        """Add or replace a principal. ``api_key`` is stored separately and
        never returned by any read method."""
        rec = self.get_session(token)
        with self._lock:
            rec.principals[principal.id] = principal
            if api_key is not None and api_key != "":
                rec.api_keys[principal.id] = api_key
            else:
                # Empty / None means "no LLM key for this principal" — clear
                # any prior key so reverting from anthropic to scripted
                # doesn't leave a stale credential in memory.
                rec.api_keys.pop(principal.id, None)
        return principal

    def delete_principal(self, token: str, principal_id: str) -> None:
        rec = self.get_session(token)
        with self._lock:
            rec.principals.pop(principal_id, None)
            rec.api_keys.pop(principal_id, None)

    def list_principals(self, token: str) -> list[SandboxPrincipal]:
        rec = self.get_session(token)
        with self._lock:
            return list(rec.principals.values())

    def read_api_key(self, token: str, principal_id: str) -> str | None:
        """Internal: orchestrator-only access to the api_key for a
        principal. NEVER expose this via any HTTP endpoint."""
        rec = self.get_session(token)
        with self._lock:
            return rec.api_keys.get(principal_id)

    # ------ helpers

    def expires_at_iso(self, token: str) -> str:
        rec = self.get_session(token)
        return rec.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------ private

    def _fresh_expiry(self) -> datetime:
        return datetime.now(UTC) + self._ttl

    def _sweep_expired(self) -> None:
        now = datetime.now(UTC)
        with self._lock:
            stale = [t for t, r in self._sessions.items() if r.expires_at < now]
            for t in stale:
                self._sessions.pop(t, None)


# Single process-wide store. Cleared on server restart.
session_store = SandboxSessionStore()
