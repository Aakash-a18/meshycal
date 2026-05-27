"""Sandbox-layer tests.

Covers the surface specific to the sandbox: the HTTP endpoints, the
session store's api_key isolation, the sandbox_runner end-to-end, and
the AnthropicReasoner's mocked response parsing.

Domain-level tests (CalendarObject canonical hash, SchedulingAgent
behaviour, scoped-payload hash invariant) live alongside the package
in ``meshycal/tests/``.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from demos.phase_4_prototype.server.main import app
from demos.phase_4_prototype.server.sandbox_models import (
    SandboxEvent,
    SandboxPolicy,
    SandboxPrincipal,
    SandboxReasonerConfig,
    SandboxRequestSpec,
)
from demos.phase_4_prototype.server.sandbox_runner import run_sandbox_two_party
from meshycal import (
    AnthropicReasoner,
    CalendarEvent,
    CalendarObject,
    OpenAICompatibleReasoner,
    ProposalVerdict,
    ScriptedReasoner,
    build_reasoner,
    reasoner_label,
)


# --- Principal fixtures ---------------------------------------------------


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


# --- sandbox_runner end-to-end -------------------------------------------


@pytest.mark.asyncio
async def test_runner_scripted_two_party_produces_matching_scoped_hash():
    """Sandbox-runner-level smoke: the wire-true scoped payload_hash
    matches on both ledgers. (The agent-level version of this test lives
    in meshycal/tests/test_scheduling_agent.py.)"""
    sender = _principal("sender@sandbox.local", "Sender", 0)
    recipient = _principal(
        "recipient@sandbox.local", "Recipient", 1,
        events=[("11:00", 30, "weekly", False)],
    )
    result = await run_sandbox_two_party(
        sender=sender, recipient=recipient,
        request=_request(sender.id, recipient.id), api_keys={},
    )
    assert result.success is True
    assert result.topology == "two_party"

    sender_emit = next(
        e for e in result.ledgers[sender.id]
        if e.action_type == "emit" and e.operation == "proposal"
    )
    recipient_recv = next(
        e for e in result.ledgers[recipient.id]
        if e.action_type == "receive" and e.operation == "proposal"
    )
    assert sender_emit.payload_hash == recipient_recv.payload_hash == result.scoped_payload_hash


@pytest.mark.asyncio
async def test_runner_scoped_payload_strips_blocked_fields():
    sender = _principal(
        "sender@sandbox.local", "Sender", 0,
        events=[("10:00", 60, "secret-1on1", False)],
    )
    recipient = _principal("recipient@sandbox.local", "Recipient", 1)
    result = await run_sandbox_two_party(
        sender=sender, recipient=recipient,
        request=_request(sender.id, recipient.id), api_keys={},
    )
    recipient_scoped = result.scoped_payloads[recipient.id]
    assert "calendar_titles" not in recipient_scoped
    assert "attendee_emails" not in recipient_scoped


@pytest.mark.asyncio
async def test_runner_calendar_deltas_added_on_accept():
    sender = _principal("a@sandbox.local", "Alpha", 0)
    recipient = _principal("b@sandbox.local", "Beta", 1)
    result = await run_sandbox_two_party(
        sender=sender, recipient=recipient,
        request=_request(sender.id, recipient.id), api_keys={},
    )
    assert len(result.calendar_deltas) == 2


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
    assert "api_key" not in res.json()
    state = client.get(f"/sandbox/session/{tok}").json()
    for p in state["principals"]:
        assert "api_key" not in p
    assert "sk-ant-secret-do-not-leak" not in json.dumps(state)
    client.delete(f"/sandbox/session/{tok}")


def test_session_endpoints_full_lifecycle(client: TestClient):
    tok = client.post("/sandbox/session").json()["session_token"]
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
    assert len(run["ledgers"]["iris@sandbox.local"]) >= 2
    assert len(run["ledgers"]["marius@sandbox.local"]) >= 2
    iris_emit = [e for e in run["ledgers"]["iris@sandbox.local"]
                 if e["action_type"] == "emit" and e["operation"] == "proposal"][0]
    marius_recv = [e for e in run["ledgers"]["marius@sandbox.local"]
                   if e["action_type"] == "receive" and e["operation"] == "proposal"][0]
    assert iris_emit["payload_hash"] == marius_recv["payload_hash"] == run["scoped_payload_hash"]
    assert client.delete(f"/sandbox/session/{tok}").status_code == 200


# --- AnthropicReasoner parsing (mocked) ----------------------------------


class _FakeToolBlock:
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

    cal = CalendarObject(owner_principal_id="t@x")
    verdict = await reasoner.evaluate_proposal(
        candidate_slots=["2026-05-26T13:00:00Z", "2026-05-26T15:00:00Z"],
        duration_minutes=30,
        my_calendar=cal,
        my_display_name="TestUser",
    )
    assert isinstance(verdict, ProposalVerdict)
    assert verdict.accept is True
    assert verdict.chosen_slot == "2026-05-26T13:00:00Z"


@pytest.mark.asyncio
async def test_anthropic_reasoner_rejects_invented_slot():
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
    cal = CalendarObject(owner_principal_id="t@x")
    verdict = await reasoner.evaluate_proposal(
        candidate_slots=["2026-05-26T13:00:00Z"],
        duration_minutes=30,
        my_calendar=cal,
        my_display_name="TestUser",
    )
    assert verdict.accept is False
    assert verdict.chosen_slot is None


def test_build_reasoner_falls_back_without_key():
    r = build_reasoner(provider="anthropic", model="claude-sonnet-4-6", api_key=None)
    assert isinstance(r, ScriptedReasoner)
    r2 = build_reasoner(provider="anthropic", model="claude-sonnet-4-6", api_key="")
    assert isinstance(r2, ScriptedReasoner)


# --- OpenAI-compatible reasoner (mocked HTTP) ----------------------------


class _FakeAsyncHttpResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    """Drop-in for httpx.AsyncClient that records the last POST and
    returns a canned response. Supports the ``async with`` shape the
    OpenAICompatibleReasoner uses."""

    def __init__(self, response: _FakeAsyncHttpResponse) -> None:
        self._response = response
        self.last_url: str | None = None
        self.last_json: dict[str, Any] | None = None
        self.last_headers: dict[str, str] | None = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
    ) -> _FakeAsyncHttpResponse:
        self.last_url = url
        self.last_json = json
        self.last_headers = headers
        return self._response


def _openai_tool_call_payload(*, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the OpenAI-shaped chat.completions response for a tool call."""
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_fake",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


@pytest.mark.asyncio
async def test_openai_compat_reasoner_parses_tool_call_response(monkeypatch):
    """Happy path: the reasoner translates an OpenAI-shaped tool_calls
    response into a ProposalVerdict matching the model's pick."""
    payload = _openai_tool_call_payload(
        name=OpenAICompatibleReasoner.TOOL_NAME,
        arguments={
            "accept": True,
            "chosen_slot": "2026-05-26T13:00:00Z",
            "reason": "13:00 is the first non-conflicting candidate",
        },
    )
    fake_client = _FakeAsyncClient(_FakeAsyncHttpResponse(payload))

    import meshycal.reasoners.openai_compatible as oc_mod

    monkeypatch.setattr(
        oc_mod.httpx, "AsyncClient", lambda *_a, **_kw: fake_client
    )

    reasoner = OpenAICompatibleReasoner(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-4o",
    )
    verdict = await reasoner.evaluate_proposal(
        candidate_slots=["2026-05-26T13:00:00Z", "2026-05-26T15:00:00Z"],
        duration_minutes=30,
        my_calendar=CalendarObject(owner_principal_id="t@x"),
        my_display_name="TestUser",
    )
    assert isinstance(verdict, ProposalVerdict)
    assert verdict.accept is True
    assert verdict.chosen_slot == "2026-05-26T13:00:00Z"

    # The reasoner must hit the configured base_url and never anywhere else.
    assert fake_client.last_url == "https://api.example.com/v1/chat/completions"
    assert fake_client.last_headers is not None
    assert fake_client.last_headers["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_openai_compat_reasoner_rejects_invented_slot(monkeypatch):
    """Defense against hallucinated slots: a model that picks a slot
    not in the CANDIDATES list flips to reject."""
    payload = _openai_tool_call_payload(
        name=OpenAICompatibleReasoner.TOOL_NAME,
        arguments={
            "accept": True,
            "chosen_slot": "2026-05-26T22:00:00Z",  # NOT in candidates
            "reason": "hallucinated slot",
        },
    )
    fake_client = _FakeAsyncClient(_FakeAsyncHttpResponse(payload))

    import meshycal.reasoners.openai_compatible as oc_mod

    monkeypatch.setattr(
        oc_mod.httpx, "AsyncClient", lambda *_a, **_kw: fake_client
    )

    reasoner = OpenAICompatibleReasoner(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-4o",
    )
    verdict = await reasoner.evaluate_proposal(
        candidate_slots=["2026-05-26T13:00:00Z"],
        duration_minutes=30,
        my_calendar=CalendarObject(owner_principal_id="t@x"),
        my_display_name="TestUser",
    )
    assert verdict.accept is False
    assert verdict.chosen_slot is None


@pytest.mark.asyncio
async def test_openai_compat_reasoner_falls_back_on_http_error(monkeypatch):
    """An HTTP failure must degrade to the scripted reasoner, not raise."""
    fake_client = _FakeAsyncClient(_FakeAsyncHttpResponse({}, status_code=500))

    import meshycal.reasoners.openai_compatible as oc_mod

    monkeypatch.setattr(
        oc_mod.httpx, "AsyncClient", lambda *_a, **_kw: fake_client
    )

    reasoner = OpenAICompatibleReasoner(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-4o",
    )
    verdict = await reasoner.evaluate_proposal(
        candidate_slots=["2026-05-26T13:00:00Z"],
        duration_minutes=30,
        my_calendar=CalendarObject(owner_principal_id="t@x"),
        my_display_name="TestUser",
    )
    # ScriptedReasoner picks the first non-conflicting slot.
    assert verdict.accept is True
    assert verdict.chosen_slot == "2026-05-26T13:00:00Z"


def test_build_reasoner_openai_with_defaults_returns_compat():
    r = build_reasoner(
        provider="openai",
        model="",  # factory fills in gpt-4o
        api_key="sk-test",
        base_url=None,  # factory fills in api.openai.com/v1
    )
    assert isinstance(r, OpenAICompatibleReasoner)


def test_build_reasoner_openai_compatible_requires_explicit_base_url():
    """``openai-compatible`` is the bring-your-own-endpoint variant —
    missing base_url must NOT silently default to api.openai.com."""
    r = build_reasoner(
        provider="openai-compatible",
        model="some-model",
        api_key="sk-test",
        base_url=None,
    )
    assert isinstance(r, ScriptedReasoner)


def test_build_reasoner_openai_compatible_with_full_config():
    r = build_reasoner(
        provider="openai-compatible",
        model="llama-3.1-70b",
        api_key="gsk-test",
        base_url="https://api.groq.com/openai/v1",
    )
    assert isinstance(r, OpenAICompatibleReasoner)


def test_reasoner_label_openai_compatible():
    assert reasoner_label(
        provider="openai",
        model="",
        api_key="sk-test",
        base_url=None,
    ) == "openai · gpt-4o"
    assert reasoner_label(
        provider="openai-compatible",
        model="llama-3.1-70b",
        api_key="gsk-test",
        base_url="https://api.groq.com/openai/v1",
    ) == "openai-compatible · llama-3.1-70b"
    assert reasoner_label(
        provider="openai",
        model="",
        api_key=None,
        base_url=None,
    ) == "openai · scripted fallback (no api key)"
