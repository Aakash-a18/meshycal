"""Multi-principal session layer for the api.

In M1 the api hosts N synthetic principals in one process. Each gets:

  - its own SchedulingAgent (with its own Signer keypair)
  - its own SQLite-backed policy store, ledger, object store
  - its own HTTP listener on a free port (started by the app's lifespan
    handler)
  - its own SchedulingAgentInbox

Each principal's data lives under `<data_dir>/<alias>/`. Aliases are
short URL-friendly names (`alice`, `bob`); principal_ids are the
full sandbox addresses (`alice@sandbox.local`).

In M2 this becomes per-user keyed by Google identity. The registry
shape stays; the seed function (`build_sandbox_registry`) is what
gets replaced.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import TYPE_CHECKING

from mesherra.crypto.primitives import Signer
from mesherra.identity import StaticDirectoryClient
from mesherra.object.store import ObjectStore
from mesherra.policy import PolicyStore, sign_policy_doc
from mesherra.provenance.ledger import ProvenanceLedger

from meshycal import (
    CalendarObject,
    ScriptedReasoner,
    SchedulingAgent,
    build_policy_doc,
)
from meshycal.api.agent_inbox import SchedulingAgentInbox

if TYPE_CHECKING:
    from meshycal.reasoners.base import SchedulingReasoner


_DEFAULT_HOST = "127.0.0.1"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class PrincipalSession:
    """One synthetic user's substrate + agent + listener."""

    def __init__(
        self,
        *,
        alias: str,
        principal_id: str,
        display_name: str,
        signer: Signer,
        directory: StaticDirectoryClient,
        reasoner: SchedulingReasoner,
        data_dir: Path,
    ) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        calendar = CalendarObject(owner_principal_id=principal_id, events=[])
        policy = PolicyStore(
            db_path=data_dir / "policy.sqlite",
            principal_id=principal_id,
            public_key_b64=signer.public_key_b64(),
        )
        policy.save_signed(
            sign_policy_doc(
                doc=build_policy_doc(principal_id=principal_id),
                signer=signer,
            )
        )
        ledger = ProvenanceLedger(
            db_path=data_dir / "ledger.sqlite",
            ledger_owner=principal_id,
        )
        objects = ObjectStore(
            db_path=data_dir / "objects.sqlite",
            owner_principal_id=principal_id,
        )

        self.alias = alias
        self.principal_id = principal_id
        self.display_name = display_name
        self.agent = SchedulingAgent(
            calendar=calendar,
            signer=signer,
            policy_store=policy,
            ledger=ledger,
            object_store=objects,
            directory=directory,
            reasoner=reasoner,
            display_name=display_name,
        )
        self.inbox = SchedulingAgentInbox(self.agent)
        self._listener_handle = None

    @property
    def listener_url(self) -> str | None:
        return self.agent.my_url

    async def start_listener(self, host: str = _DEFAULT_HOST, port: int = 0) -> None:
        actual_port = port or _find_free_port()
        self._listener_handle = await self.agent.start_listener(
            host=host, port=actual_port,
        )

    async def stop_listener(self) -> None:
        if self._listener_handle is not None:
            await self._listener_handle.stop()
            self._listener_handle = None

    def close(self) -> None:
        self.agent.close()


class PrincipalRegistry:
    """Holds all synthetic principals + the shared directory."""

    def __init__(self, *, directory: StaticDirectoryClient) -> None:
        self._directory = directory
        self._by_alias: dict[str, PrincipalSession] = {}
        self._by_principal_id: dict[str, PrincipalSession] = {}

    @property
    def directory(self) -> StaticDirectoryClient:
        return self._directory

    def register(self, session: PrincipalSession) -> None:
        self._by_alias[session.alias] = session
        self._by_principal_id[session.principal_id] = session

    def get(self, alias_or_pid: str) -> PrincipalSession | None:
        return self._by_alias.get(alias_or_pid) or self._by_principal_id.get(
            alias_or_pid
        )

    def all(self) -> list[PrincipalSession]:
        return list(self._by_alias.values())

    async def start_all_listeners(self, host: str = _DEFAULT_HOST) -> None:
        for sess in self._by_alias.values():
            await sess.start_listener(host=host)

    async def stop_all_listeners(self) -> None:
        for sess in self._by_alias.values():
            await sess.stop_listener()

    def close_all(self) -> None:
        for sess in self._by_alias.values():
            sess.close()


# --- sandbox seed -----------------------------------------------------

_SANDBOX_PRINCIPALS = [
    ("alice", "alice@sandbox.local", "Alice"),
    ("bob", "bob@sandbox.local", "Bob"),
]


def build_sandbox_registry(*, data_dir: Path) -> PrincipalRegistry:
    """Seed two synthetic principals (Alice, Bob) with fresh keys.

    M2 replaces this with a per-Google-identity factory that loads
    persisted keys; the registry shape stays the same.
    """
    signers = {
        principal_id: Signer.generate()
        for _, principal_id, _ in _SANDBOX_PRINCIPALS
    }
    directory = StaticDirectoryClient(
        {pid: s.public_key_b64() for pid, s in signers.items()}
    )
    registry = PrincipalRegistry(directory=directory)
    for alias, principal_id, display_name in _SANDBOX_PRINCIPALS:
        registry.register(
            PrincipalSession(
                alias=alias,
                principal_id=principal_id,
                display_name=display_name,
                signer=signers[principal_id],
                directory=directory,
                reasoner=ScriptedReasoner(),
                data_dir=data_dir / alias,
            )
        )
    return registry
