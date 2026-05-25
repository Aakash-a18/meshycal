"""Smoke tests for the Phase 4 sandbox.

These cover the load-bearing properties:
  - The scripted-mode 2-party run produces matching scoped payload_hash
    bytes on both principals' Residue ledgers.
  - Sensitive api_keys are never returned by the read endpoints.
  - The orchestrator's policy mapping actually strips blocked fields.
  - The AnthropicReasoner parses a mocked Anthropic response into a
    ProposalVerdict without making a network call.

The Anthropic SDK is loaded but not called; the AsyncAnthropic client
is monkey-patched on the reasoner instance to return a synthetic
response shape.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from demos.phase_4_prototype.server.main import app
from demos.phase_4_prototype.server.reasoner import CalendarEvent
from demos.phase_4_prototype.server.sandbox_models import (
    SandboxEvent,
    SandboxPolicy,
    SandboxPrincipal,
    SandboxReasonerConfig,
    SandboxRequestSpec,
)
from demos.phase_4_prototype.server.sandbox_orchestrator import (
    _build_candidates,
    run_sandbox_two_party,
)
from demos.phase_4_prototype.server.sandbox_reasoners import (
    AnthropicReasoner,
    ProposalVerdict,
    ScriptedSandboxReasoner,
    build_sandbox_reasoner,
)


# --- Fixtures -------------------------------------------------------------


def _principal(
    pid: str,
    name: str,
    slot: int,
    events: list[tuple[str, int, str, bool]] | None = None,
    provider: str = "scripted",
) -> SandboxPrincipal:
    return SandboxPrincipal(
        id=pid,
        display_name=name,
        color_slot=slot,
        calendar=[
            SandboxEvent(time=t, duration=d, title=title, attendees="", is_blocking=b)
            for (t, d, title, b) in (events or [])
        ],
        policy=SandboxPolicy(
            outbound_allow=["candidates", "duration_minutes", "constraint_hints"],
            outbound_block=["calendar_titles", "attendee_emails"],
            inbound_allow=["candidates", "duration_minutes", "constraint_hints"],
            max_cascade_depth=1,
        ),
        reasoner=SandboxReasonerConfig(provider=provider),
    )


def _request(sender_id: str, recipient_id: str, duration: int = 30) -> SandboxRequestSpec:
    return SandboxRequestSpec(
        sender_id=sender_id,
        recipient_id=recipient_id,
        earliest="2026-05-26T09:00:00Z",
        latest="2026-05-26T18:00:00Z",
        duration=duration,
    )


# --- Orchestrator end-to-end ---------------------------------------------


@pytest.mark.asyncio
async def test_scripted_two_party_produces_matching_scoped_hash():
    """The signed scoped payload_hash must appear identically on both
    principals' ledgers. This is the Mesherra Phase 3 invariant."""
    sender = _principal("sender@sandbox.local", "Sender", 0)
    recipient = _principal(
        "recipient@sandbox.local",
        "Recipient",
        1,
        events=[("11:00", 30, "weekly", False)],
    )
    result = await run_sandbox_two_party(
        sender=sender, recipient=recipient, request=_request(sender.id, recipient.id), api_keys={}
    )
    assert result.success is True
    assert result.topology == "two_party"
    assert result.scoped_payload_hash, "scoped_payload_hash must be set"
    assert result.rich_payload_hash != result.scoped_payload_hash, (
        "scoped projection must differ from the rich payload"
    )

    sender_emit = next((e for e in result.ledgers[sender.id]
                        if e.action_type == "emit" and e.operation == "proposal"), None)
    recipient_recv = next((e for e in result.ledgers[recipient.id]
                           if e.action_type == "receive" and e.operation == "proposal"), None)
    assert sender_emit and recipient_recv, "both sides must have proposal ledger entries"
    assert sender_emit.payload_hash == recipient_recv.payload_hash == result.scoped_payload_hash


@pytest.mark.asyncio
async def test_scoped_payload_strips_blocked_fields():
    """The recipient's scoped payload must not include the sender's
    blocked fields (calendar_titles, attendee_emails)."""
    sender = _principal(
        "sender@sandbox.local",
        "Sender",
        0,
        events=[("10:00", 60, "secret-1on1", False)],
    )
    recipient = _principal("recipient@sandbox.local", "Recipient", 1)
    result = await run_sandbox_two_party(
        sender=sender, recipient=recipient, request=_request(sender.id, recipient.id), api_keys={}
    )
    recipient_scoped = result.scoped_payloads[recipient.id]
    assert "calendar_titles" not in recipient_scoped
    assert "attendee_emails" not in recipient_scoped
    assert "candidates" in recipient_scoped
    assert "duration_minutes" in recipient_scoped


@pytest.mark.asyncio
async def test_calendar_deltas_added_on_accept():
    sender = _principal("a@sandbox.local", "Alpha", 0)
    recipient = _principal("b@sandbox.local", "Beta", 1)
    result = await run_sandbox_two_party(
        sender=sender, recipient=recipient, request=_request(sender.id, recipient.id), api_keys={}
    )
    assert len(result.calendar_deltas) == 2
    by_pid = {d.principal_id: d for d in result.calendar_deltas}
    assert by_pid[sender.id].delta_type == "add"
    assert by_pid[recipient.id].delta_type == "add"
    assert by_pid[sender.id].time == by_pid[recipient.id].time


def test_candidate_builder_filters_sender_conflicts():
    sender = _principal(
        "x@sandbox.local",
        "Ex",
        0,
        events=[("09:00", 60, "morning", False), ("10:00", 30, "stand", False)],
    )
    candidates, _ = _build_candidates(sender, _request(sender.id, "y@sandbox.local"))
    # 09:00 and 10:00 should be filtered; 11:00 should appear.
    assert all("T09:00" not in c for c in candidates)
    assert any("T11:00" in c for c in candidates)


# --- Session HTTP endpoints ----------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_session_create_seeds_defaults(client: TestClient):
    res = client.post("/sandbox/session")
    assert res.status_code == 201
    body = res.json()
    assert "session_token" in body
    pids = {p["id"] for p in body["principals"]}
    assert pids == {"iris@sandbox.local", "marius@sandbox.local", "atlas@sandbox.local"}


def test_session_get_never_returns_api_keys(client: TestClient):
    tok = client.post("/sandbox/session").json()["session_token"]
    # PUT a principal with an api_key
    res = client.put(
        f"/sandbox/session/{tok}/principal/iris@sandbox.local",
        json={
            "id": "iris@sandbox.local",
            "display_name": "Iris",
            "color_slot": 0,
            "calendar": [],
            "policy": {
                "outbound_allow": ["candidates", "duration_minutes"],
                "outbound_block": ["calendar_titles"],
                "inbound_allow": ["candidates"],
                "max_cascade_depth": 1,
            },
            "reasoner": {"provider": "anthropic", "model": "claude-sonnet-4-6", "base_url": ""},
            "api_key": "sk-ant-secret-do-not-leak",
        },
    )
    assert res.status_code == 200, res.text
    # The PUT response itself must not echo the key
    assert "api_key" not in res.json()
    # GET state must not include the key
    state = client.get(f"/sandbox/session/{tok}").json()
    for p in state["principals"]:
        assert "api_key" not in p
    # The serialized session_state must not contain the secret string
    # anywhere.
    body_text = json.dumps(state)
    assert "sk-ant-secret-do-not-leak" not in body_text
    client.delete(f"/sandbox/session/{tok}")


def test_session_endpoints_full_lifecycle(client: TestClient):
    tok = client.post("/sandbox/session").json()["session_token"]
    # Run a scripted 2-party against the default seed
    body = {
        "sender_id": "iris@sandbox.local",
        "recipient_id": "marius@sandbox.local",
        "earliest": "2026-05-26T09:00:00Z",
        "latest": "2026-05-26T18:00:00Z",
        "duration": 30,
    }
    res = client.post(f"/sandbox/session/{tok}/run", json=body)
    assert res.status_code == 200, res.text
    run = res.json()
    assert run["success"] is True
    assert run["topology"] == "two_party"
    # Both sides have ledger entries
    assert len(run["ledgers"]["iris@sandbox.local"]) >= 2
    assert len(run["ledgers"]["marius@sandbox.local"]) >= 2
    # Matching scoped hash
    iris_emit = [e for e in run["ledgers"]["iris@sandbox.local"]
                 if e["action_type"] == "emit" and e["operation"] == "proposal"][0]
    marius_recv = [e for e in run["ledgers"]["marius@sandbox.local"]
                   if e["action_type"] == "receive" and e["operation"] == "proposal"][0]
    assert iris_emit["payload_hash"] == marius_recv["payload_hash"] == run["scoped_payload_hash"]
    # Cleanup
    assert client.delete(f"/sandbox/session/{tok}").status_code == 200


# --- AnthropicReasoner parsing -------------------------------------------


class _FakeToolBlock:
    """Mimics anthropic SDK's tool_use content block."""

    def __init__(self, *, name: str, input_dict: dict[str, Any]) -> None:
        self.type = "tool_use"
        self.name = name
        self.input = input_dict


class _FakeResponse:
    def __init__(self, blocks: list[Any]) -> None:
        self.content = blocks


class _FakeMessages:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def create(self, **_kwargs: Any) -> _FakeResponse:
        return self._response


class _FakeAsyncAnthropic:
    def __init__(self, response: _FakeResponse) -> None:
        self.messages = _FakeMessages(response)


@pytest.mark.asyncio
async def test_anthropic_reasoner_parses_tool_use_response():
    fake_blocks = [
        _FakeToolBlock(
            name=AnthropicReasoner.TOOL_NAME,
            input_dict={
                "accept": True,
                "chosen_slot": "2026-05-26T13:00:00Z",
                "reason": "13:00 is the first candidate that does not conflict",
            },
        ),
    ]
    reasoner = AnthropicReasoner(api_key="dummy", model="claude-sonnet-4-6")
    reasoner._client = _FakeAsyncAnthropic(_FakeResponse(fake_blocks))  # type: ignore[assignment]

    verdict = await reasoner.evaluate_proposal(
        candidate_slots=["2026-05-26T13:00:00Z", "2026-05-26T15:00:00Z"],
        duration_minutes=30,
        my_calendar=[],
        my_display_name="TestUser",
    )
    assert isinstance(verdict, ProposalVerdict)
    assert verdict.accept is True
    assert verdict.chosen_slot == "2026-05-26T13:00:00Z"
    assert "13:00" in verdict.reason


@pytest.mark.asyncio
async def test_anthropic_reasoner_rejects_invented_slot():
    """If Claude returns a slot not in the candidate list, reject."""
    fake_blocks = [
        _FakeToolBlock(
            name=AnthropicReasoner.TOOL_NAME,
            input_dict={
                "accept": True,
                "chosen_slot": "2026-05-26T22:00:00Z",  # NOT in candidates
                "reason": "hallucinated slot",
            },
        ),
    ]
    reasoner = AnthropicReasoner(api_key="dummy", model="claude-sonnet-4-6")
    reasoner._client = _FakeAsyncAnthropic(_FakeResponse(fake_blocks))  # type: ignore[assignment]

    verdict = await reasoner.evaluate_proposal(
        candidate_slots=["2026-05-26T13:00:00Z"],
        duration_minutes=30,
        my_calendar=[],
        my_display_name="TestUser",
    )
    assert verdict.accept is False
    assert verdict.chosen_slot is None


def test_build_reasoner_falls_back_without_key():
    """provider=anthropic without an api_key must degrade gracefully."""
    r = build_sandbox_reasoner(provider="anthropic", model="claude-sonnet-4-6", api_key=None)
    assert isinstance(r, ScriptedSandboxReasoner)
    r2 = build_sandbox_reasoner(provider="anthropic", model="claude-sonnet-4-6", api_key="")
    assert isinstance(r2, ScriptedSandboxReasoner)


@pytest.mark.asyncio
async def test_scripted_reasoner_picks_non_conflicting_slot():
    reasoner = ScriptedSandboxReasoner()
    cal = [
        CalendarEvent(slot_start="2026-05-26T13:00:00Z", duration_minutes=30,
                      title="conflict", attendee_principal_ids=[]),
    ]
    verdict = await reasoner.evaluate_proposal(
        candidate_slots=["2026-05-26T13:00:00Z", "2026-05-26T14:00:00Z"],
        duration_minutes=30,
        my_calendar=cal,
        my_display_name="Test",
    )
    assert verdict.accept is True
    assert verdict.chosen_slot == "2026-05-26T14:00:00Z"
