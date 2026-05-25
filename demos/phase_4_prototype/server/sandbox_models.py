"""Pydantic shapes for the sandbox API.

Mirrors the frontend's ``SB_STATE`` shape but renamed snake_case for the
Python side. Field naming chosen so the FastAPI request bodies can be
produced directly by ``JSON.stringify`` on the frontend with a small
keys-to-snake_case helper.

XSS / PII discipline: this module defines shapes only. None of the
defaults contain real names or emails — they are populated by the
session store from the synthetic-archetype defaults (Iris / Marius /
Atlas on ``@sandbox.local``).

API key handling: ``SandboxPrincipalIn`` accepts an ``api_key`` field on
ingress (PUT). ``SandboxPrincipalOut`` deliberately omits it so GET
responses can never leak it. The orchestrator reads keys from a
separate per-session dict, never returns them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# --- Building blocks ------------------------------------------------------


class SandboxEvent(BaseModel):
    """One calendar entry. Synthetic data only."""

    model_config = ConfigDict(extra="forbid")

    time: str  # "HH:MM" 24h local
    duration: int = Field(ge=5, le=480)
    title: str = ""
    attendees: str = ""
    is_blocking: bool = False


class SandboxPolicy(BaseModel):
    """Plain-English privacy toggles. Maps 1:1 to the frontend's privacy panel."""

    model_config = ConfigDict(extra="forbid")

    outbound_allow: list[str]
    outbound_block: list[str]
    inbound_allow: list[str]
    max_cascade_depth: int = Field(default=1, ge=0, le=3)


class SandboxReasonerConfig(BaseModel):
    """LLM provider config. ``api_key`` is NOT here on purpose — it lives in
    a separate per-session dict that's never serialized back to the wire.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["scripted", "anthropic", "openai", "openai-compatible"] = "scripted"
    model: str = ""
    base_url: str = ""


# --- Principal in / out ---------------------------------------------------


class _SandboxPrincipalBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    color_slot: int = Field(default=0, ge=0, le=5)
    calendar: list[SandboxEvent] = Field(default_factory=list)
    policy: SandboxPolicy
    reasoner: SandboxReasonerConfig


class SandboxPrincipalIn(_SandboxPrincipalBase):
    """Inbound shape — accepts an ``api_key`` field that's split out
    server-side before storage. The stored principal has no key on it.
    """

    api_key: str | None = None


class SandboxPrincipal(_SandboxPrincipalBase):
    """Stored / returned shape — never carries an api_key."""


# --- Request + result -----------------------------------------------------


class SandboxRequestSpec(BaseModel):
    """The body of POST /sandbox/session/{tok}/run."""

    model_config = ConfigDict(extra="forbid")

    sender_id: str
    recipient_id: str
    earliest: str  # ISO 8601 datetime, e.g. "2026-05-26T09:00:00Z"
    latest: str
    duration: int = Field(ge=5, le=480)
    note: str = ""


class SandboxExchange(BaseModel):
    """One bilateral exchange between two principals — the unit the UI
    renders as a tessera badge."""

    model_config = ConfigDict(extra="forbid")

    label: str  # "A", "B", "C" — narrative label
    initiator_id: str
    responder_id: str
    proposal_payload_hash: str
    acceptance_payload_hash: str
    task_id: str


class SandboxResidue(BaseModel):
    """Trimmed Residue projection the UI consumes. Mirrors ResidueDTO in
    scenarios.py."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    action_type: str
    operation: str
    actor: str
    counterpart: str
    timestamp: str
    payload_hash: str
    payload_schema: str
    signature_prefix: str  # first 16 chars only


class SandboxCalendarDelta(BaseModel):
    """A change to a principal's calendar produced by a run."""

    model_config = ConfigDict(extra="forbid")

    principal_id: str
    delta_type: Literal["remove", "add"]
    slot_id: str  # frontend slot key, e.g. "iris-sandbox-local-1300"
    time: str  # "HH:MM"
    title: str = ""
    attendees: str = ""


class SandboxReasonerTrace(BaseModel):
    """Captured reasoning for the UI's trace panel — populated for the
    pivot agent in a cascade. ``provider`` distinguishes scripted vs
    real-LLM outputs so the UI can decorate accordingly."""

    model_config = ConfigDict(extra="forbid")

    principal_id: str
    provider: str  # "scripted" | "anthropic" | ...
    model: str = ""
    requested_slot: str
    blocking_event_title: str = ""
    blocking_event_attendee: str = ""
    proposed_new_slot: str = ""
    reason: str = ""


class SandboxRunResult(BaseModel):
    """Everything the UI needs to render a run, scripted or LLM-driven."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    topology: Literal["two_party", "three_party"]
    sender_id: str
    recipient_id: str
    pivot_id: str | None = None  # set when topology == "three_party"

    principals: list[SandboxPrincipal]
    exchanges: list[SandboxExchange]
    ledgers: dict[str, list[SandboxResidue]] = Field(default_factory=dict)
    scoped_payloads: dict[str, dict[str, Any]] = Field(default_factory=dict)
    rich_payload_hash: str = ""
    scoped_payload_hash: str = ""

    calendar_deltas: list[SandboxCalendarDelta] = Field(default_factory=list)
    narrative_beats: list[str] = Field(default_factory=list)
    reasoner_trace: SandboxReasonerTrace | None = None

    duration_ms: int = 0
    reasoner_summary: dict[str, str] = Field(default_factory=dict)
    """principal_id → human-readable reasoner label ("scripted" /
    "anthropic · claude-sonnet-4-6")"""


# --- Session shapes -------------------------------------------------------


class SandboxSessionCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_token: str
    expires_at: str
    principals: list[SandboxPrincipal]


class SandboxSessionState(BaseModel):
    """Returned by GET /sandbox/session/{tok}. api_keys never included."""

    model_config = ConfigDict(extra="forbid")

    session_token: str
    expires_at: str
    principals: list[SandboxPrincipal]


class SandboxAck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
