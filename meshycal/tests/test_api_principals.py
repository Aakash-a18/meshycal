"""Tests for PrincipalRegistry — the M1.2 multi-principal session layer.

The api hosts N synthetic principals in one process. Each gets its own
SchedulingAgent + substrate (policy, ledger, object_store) + HTTP
listener. The web renderer picks which principal it's acting as via a
URL query param (`?as=alice`).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from meshycal.api.principals import (
    PrincipalRegistry,
    PrincipalSession,
    build_sandbox_registry,
)


def test_sandbox_registry_seeds_alice_and_bob():
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        registry = build_sandbox_registry(data_dir=td)
        try:
            aliases = {s.alias for s in registry.all()}
            assert {"alice", "bob"}.issubset(aliases)
            assert registry.get("alice") is not None
            assert registry.get("bob") is not None
            assert registry.get("alice").principal_id == "alice@sandbox.local"
        finally:
            registry.close_all()


def test_registry_get_by_principal_id_also_works():
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        registry = build_sandbox_registry(data_dir=td)
        try:
            sess = registry.get("alice@sandbox.local")
            assert sess is not None
            assert sess.alias == "alice"
        finally:
            registry.close_all()


def test_registry_get_unknown_returns_none():
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        registry = build_sandbox_registry(data_dir=td)
        try:
            assert registry.get("nobody") is None
        finally:
            registry.close_all()


def test_each_session_has_independent_substrate():
    """Alice's ledger writes must not appear in Bob's, and vice versa.
    A single shared substrate would silently merge their data — fatal
    for the demo and a violation of per-principal isolation."""
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        registry = build_sandbox_registry(data_dir=td)
        try:
            alice = registry.get("alice")
            bob = registry.get("bob")
            assert alice.agent.ledger.db_path != bob.agent.ledger.db_path
            assert alice.agent.objects.db_path != bob.agent.objects.db_path
            assert alice.agent.principal_id != bob.agent.principal_id
        finally:
            registry.close_all()


def test_shared_directory_knows_both_principals():
    """Alice and Bob's principal_ids must both be in the shared
    directory. Otherwise their agents cannot verify each other's
    signatures, and propose_meeting_to fails immediately."""
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        registry = build_sandbox_registry(data_dir=td)
        try:
            known = registry.directory.known_principals()
            assert "alice@sandbox.local" in known
            assert "bob@sandbox.local" in known
        finally:
            registry.close_all()


@pytest.mark.asyncio
async def test_listeners_start_and_stop_cleanly():
    """Both principals must come up on a free port and shut down
    without leaking sockets."""
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        registry = build_sandbox_registry(data_dir=td)
        try:
            await registry.start_all_listeners(host="127.0.0.1")
            for sess in registry.all():
                assert sess.listener_url is not None
                assert sess.listener_url.startswith("http://127.0.0.1:")
        finally:
            await registry.stop_all_listeners()
            registry.close_all()


def test_session_inbox_is_a_scheduling_agent_inbox():
    """Each session exposes an inbox adapter that reads from its own
    agent — the api routes will call session.inbox.list_cards() etc."""
    from meshycal.api.agent_inbox import SchedulingAgentInbox

    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        registry = build_sandbox_registry(data_dir=td)
        try:
            for sess in registry.all():
                assert isinstance(sess.inbox, SchedulingAgentInbox)
                # Empty by default — no negotiations have happened.
                assert sess.inbox.list_cards() == []
        finally:
            registry.close_all()
