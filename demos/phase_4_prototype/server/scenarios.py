"""Phase 4 prototype scenarios — wraps the existing Phase 3 mesherra
backend and returns structured results the HTML prototype can render.

What ships now:

* :func:`run_two_party` — runs a real two-party Mesherra negotiation
  with a real PolicyStore, real Ed25519 signing, real SHA-256 / JCS
  canonicalization, and returns the rich payload, the post-airlock
  scoped payload, both signed payload hashes, and both ledgers'
  Residue entries — everything the UI needs to render the demo with
  *actual* cryptographic outputs.

Scenarios 2 (four-party) and 3 (cascading reschedule) are stubbed
endpoints that return ``status: "not_yet_implemented"`` — the UI shows
"upcoming" for them, mirroring the roadmap section of index.html.

No disk artifacts persist after the call: SQLite stores live in a
tempdir scoped to one call. Each request is self-contained — the
service is stateless from the client's point of view.
"""

from __future__ import annotations

import asyncio
import socket
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mesherra.a2a_adapter import A2AAdapter
from mesherra.crypto.primitives import Signer, canonical_json, content_hash
from mesherra.gateways.inbound import IncomingMessage, OutgoingResponse
from mesherra.identity import StaticDirectoryClient
from mesherra.models.primitives import ActionType, Operation
from mesherra.policy import (
    Direction,
    Match,
    PolicyDoc,
    PolicyStore,
    Rule,
    sign_policy_doc,
)
from mesherra.provenance.ledger import ProvenanceLedger
from mesherra.sdk import Mesherra

PAYLOAD_SCHEMA = "meshycal.scheduling/proposal-v1"

IRIS = "iris@meshycal.demo"
MARIUS = "marius@meshycal.demo"


# -- Wire / response shapes --------------------------------------------------


class ResidueDTO(BaseModel):
    """Trimmed Residue projection the UI consumes."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    action_type: str
    operation: str
    actor: str
    counterpart: str
    timestamp: str
    payload_hash: str
    payload_schema: str
    signature_prefix: str  # first 16 chars; full sig is verifiable server-side


class TwoPartyResult(BaseModel):
    """Everything the scenario-1 demo needs to render the real flow."""

    model_config = ConfigDict(extra="forbid")

    iris_principal_id: str
    marius_principal_id: str
    iris_rich_payload: dict[str, Any]
    iris_scoped_payload: dict[str, Any]
    marius_acceptance_payload: dict[str, Any]
    rich_payload_hash: str
    scoped_payload_hash: str
    acceptance_payload_hash: str
    iris_ledger: list[ResidueDTO]
    marius_ledger: list[ResidueDTO]
    policy_doc_iris: dict[str, Any]
    duration_ms: int


# -- The default MeshyCal policy (matches MeshyCal/demos/phase_1/policy_template.py) -


def _default_meshycal_policy(principal_id: str) -> PolicyDoc:
    return PolicyDoc(
        principal_id=principal_id,
        version=1,
        issued_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rules=[
            Rule(
                match=Match(schema=PAYLOAD_SCHEMA, direction=Direction.OUTBOUND),
                outbound_allow=[
                    "candidates",
                    "duration_minutes",
                    "constraint_hints",
                ],
                outbound_block=["calendar_titles", "attendee_emails"],
                max_array_size={"candidates": 5},
            ),
            Rule(
                match=Match(schema=PAYLOAD_SCHEMA, direction=Direction.INBOUND),
                inbound_allow=[
                    "candidates",
                    "duration_minutes",
                    "constraint_hints",
                ],
            ),
        ],
    )


# -- Helpers ---------------------------------------------------------------


def _strip_blocked_fields(rich: dict[str, Any]) -> dict[str, Any]:
    """Mirror of MeshyCal/demos/phase_1/run_demo.py ``_strip_blocked_fields``.

    The orchestrator computes the expected scoped bytes independently of
    the engine so the UI can show "rich" and "scoped" side-by-side
    without trusting in-process state.
    """
    allowed = {"candidates", "duration_minutes", "constraint_hints"}
    return {k: v for k, v in rich.items() if k in allowed}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _residue_to_dto(r: Any, sequence: int) -> ResidueDTO:
    return ResidueDTO(
        sequence=sequence,
        action_type=r.action_type.value,
        operation=r.operation.value,
        actor=r.actor,
        counterpart=r.counterpart,
        timestamp=r.timestamp,
        payload_hash=r.payload_hash,
        payload_schema=r.payload_schema,
        signature_prefix=r.signature[:16],
    )


def _rich_proposal_payload() -> dict[str, Any]:
    """The 'internal' payload Iris' agent builds before the airlock.

    Stable values so the UI's animation matches the data. Mirrors what
    MeshyCal/demos/phase_1/agent_a.py constructs in Phase 3.
    """
    return {
        "candidates": [
            "2026-05-26T13:00:00Z",
            "2026-05-26T15:30:00Z",
            "2026-05-27T11:30:00Z",
        ],
        "duration_minutes": 30,
        "calendar_titles": [
            "synthetic-team-sync",
            "synthetic-1-on-1",
        ],
        "attendee_emails": [
            "synthetic-attendee@example.invalid",
        ],
        "constraint_hints": {
            "tz": "Europe/Lisbon",
            "preferred_window": {"start_hour": 9, "end_hour": 17},
        },
    }


# -- Scenario 1 ------------------------------------------------------------


async def run_two_party() -> TwoPartyResult:
    """Run a real Phase 3 two-party negotiation and return its bytes.

    Everything is real: real keys, real signatures, real Mesherra
    gateways, real PolicyStore enforcement, real SHA-256(JCS()) hashes.
    Persistence is to a temp directory that's deleted on exit.
    """
    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="meshycal-phase4-") as td:
        td_path = Path(td)

        iris_signer = Signer.generate()
        marius_signer = Signer.generate()
        directory = StaticDirectoryClient(
            {
                IRIS: iris_signer.public_key_b64(),
                MARIUS: marius_signer.public_key_b64(),
            }
        )

        # Per-principal PolicyStores. Bound to each principal's public
        # key — every read re-verifies the signature.
        iris_store = PolicyStore(
            db_path=td_path / "iris_policy.sqlite",
            principal_id=IRIS,
            public_key_b64=iris_signer.public_key_b64(),
        )
        marius_store = PolicyStore(
            db_path=td_path / "marius_policy.sqlite",
            principal_id=MARIUS,
            public_key_b64=marius_signer.public_key_b64(),
        )

        iris_policy_signed = sign_policy_doc(
            doc=_default_meshycal_policy(IRIS), signer=iris_signer
        )
        marius_policy_signed = sign_policy_doc(
            doc=_default_meshycal_policy(MARIUS), signer=marius_signer
        )
        iris_store.save_signed(iris_policy_signed)
        marius_store.save_signed(marius_policy_signed)

        iris_ledger = ProvenanceLedger(
            db_path=td_path / "iris_ledger.sqlite", ledger_owner=IRIS
        )
        marius_ledger = ProvenanceLedger(
            db_path=td_path / "marius_ledger.sqlite", ledger_owner=MARIUS
        )

        iris_sdk = Mesherra(
            principal_id=IRIS,
            signer=iris_signer,
            ledger=iris_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=iris_store,
        )
        marius_sdk = Mesherra(
            principal_id=MARIUS,
            signer=marius_signer,
            ledger=marius_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=marius_store,
        )

        # Marius' consumer picks the first candidate (deterministic).
        captured_acceptance: dict[str, Any] = {}

        async def marius_handler(msg: IncomingMessage) -> OutgoingResponse:
            chosen = msg.payload["candidates"][0]
            duration = int(msg.payload["duration_minutes"])
            acceptance = {
                "candidates": [chosen],
                "duration_minutes": duration,
            }
            captured_acceptance.update(acceptance)
            return OutgoingResponse(
                payload=acceptance,
                operation=Operation.ACCEPTANCE,
                payload_schema=PAYLOAD_SCHEMA,
            )

        marius_sdk.on_message(marius_handler)
        # Iris registers a placeholder (required by A2AAdapter even
        # though she never receives in this flow).
        iris_sdk.on_message(lambda msg: None)  # type: ignore[arg-type]

        marius_port = _free_port()
        marius_handle = await marius_sdk.start_listener(
            host="127.0.0.1",
            port=marius_port,
            agent_name="meshycal-marius",
        )

        rich_payload = _rich_proposal_payload()
        scoped_payload_expected = _strip_blocked_fields(rich_payload)
        rich_hash = content_hash(canonical_json(rich_payload))
        scoped_hash = content_hash(canonical_json(scoped_payload_expected))

        try:
            result = await iris_sdk.send_to(
                peer_url=f"http://127.0.0.1:{marius_port}/",
                peer_principal_id=MARIUS,
                payload=rich_payload,
                payload_schema=PAYLOAD_SCHEMA,
                operation=Operation.PROPOSAL,
            )
        finally:
            await marius_handle.stop()

        acceptance_payload = dict(captured_acceptance)
        acceptance_hash = content_hash(canonical_json(acceptance_payload))

        iris_entries = sorted(
            iris_ledger.get_by_task(result.task_id), key=lambda r: r.sequence
        )
        marius_entries = sorted(
            marius_ledger.get_by_task(result.task_id), key=lambda r: r.sequence
        )

        iris_dtos = [_residue_to_dto(r, i) for i, r in enumerate(iris_entries)]
        marius_dtos = [_residue_to_dto(r, i) for i, r in enumerate(marius_entries)]

        # Capture the policy doc for the UI's "policy" panel.
        iris_policy_doc = iris_policy_signed.doc.to_signing_payload()

        # Close stores + ledgers before tempdir teardown.
        iris_store.close()
        marius_store.close()
        iris_ledger.close()
        marius_ledger.close()

        duration_ms = int((time.monotonic() - started) * 1000)

        return TwoPartyResult(
            iris_principal_id=IRIS,
            marius_principal_id=MARIUS,
            iris_rich_payload=rich_payload,
            iris_scoped_payload=scoped_payload_expected,
            marius_acceptance_payload=acceptance_payload,
            rich_payload_hash=rich_hash,
            scoped_payload_hash=scoped_hash,
            acceptance_payload_hash=acceptance_hash,
            iris_ledger=iris_dtos,
            marius_ledger=marius_dtos,
            policy_doc_iris=iris_policy_doc,
            duration_ms=duration_ms,
        )


# -- Scenario 2 and 3 — placeholders --------------------------------------


class NotYetImplemented(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "not_yet_implemented"
    scenario: str
    why: str
    estimate: str
