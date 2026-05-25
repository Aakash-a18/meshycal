"""Phase 4 prototype scenario 2 — four-party group meeting find.

Iris convenes a 30-minute meeting with three peers (Marius, Wren,
Atlas). Her agent runs six bilateral Phase 3 Mesherra exchanges in
sequence: three query exchanges (Phase A) followed by three confirm
exchanges (Phase B). Between the two phases Iris's orchestrator
computes the intersection of the per-peer free-slot sets purely
locally.

The Mesherra trust layer is not modified or extended here. Every
bilateral is a standard Phase 3 ``send_to`` / ``on_message`` round
trip; group semantics live entirely in this module on top of the
existing primitive.

No disk artifacts persist after the call: SQLite stores live in a
tempdir scoped to one call.
"""

from __future__ import annotations

import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mesherra.a2a_adapter import A2AAdapter
from mesherra.crypto.primitives import Signer, canonical_json, content_hash
from mesherra.gateways.inbound import (
    ConsumerHandler,
    IncomingMessage,
    OutgoingResponse,
)
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

from .scenarios import (
    IRIS,
    MARIUS,
    PAYLOAD_SCHEMA,
    ResidueDTO,
    _free_port,
    _residue_to_dto,
    _strip_blocked_fields,
)

WREN = "wren@meshycal.demo"
ATLAS = "atlas@meshycal.demo"

# Iris's initial candidate slots she proposes outbound (free 30-min windows).
_IRIS_CANDIDATES: list[str] = [
    "2026-05-26T13:00:00Z",
    "2026-05-26T15:30:00Z",
    "2026-05-27T11:30:00Z",
]

# Synthetic busy schedules — internal only, never crosses the wire.
_BUSY_BLOCKS: dict[str, list[tuple[str, str]]] = {
    IRIS: [
        ("2026-05-26T09:00:00Z", "2026-05-26T10:00:00Z"),
        ("2026-05-26T11:00:00Z", "2026-05-26T12:00:00Z"),
        ("2026-05-26T14:00:00Z", "2026-05-26T15:00:00Z"),
    ],
    MARIUS: [
        ("2026-05-26T10:00:00Z", "2026-05-26T11:30:00Z"),
        ("2026-05-26T15:30:00Z", "2026-05-26T16:30:00Z"),
        ("2026-05-27T09:00:00Z", "2026-05-27T10:30:00Z"),
    ],
    WREN: [
        ("2026-05-26T08:30:00Z", "2026-05-26T09:30:00Z"),
        ("2026-05-27T11:30:00Z", "2026-05-27T12:30:00Z"),
    ],
    ATLAS: [
        ("2026-05-26T15:30:00Z", "2026-05-26T17:00:00Z"),
        ("2026-05-27T10:00:00Z", "2026-05-27T12:00:00Z"),
    ],
}


# -- Wire / response shapes ------------------------------------------------


class BilateralExchangeRecord(BaseModel):
    """One bilateral exchange — what Iris sent, what the peer replied, both ledgers."""

    model_config = ConfigDict(extra="forbid")

    exchange_id: str
    phase: str
    coordinator: str
    peer: str
    iris_scoped_payload: dict[str, Any]
    peer_response_payload: dict[str, Any]
    iris_payload_hash: str
    peer_payload_hash: str
    iris_ledger_entries: list[ResidueDTO]
    peer_ledger_entries: list[ResidueDTO]
    task_id: str


class IntersectionState(BaseModel):
    """The progressive funnel from Iris's candidates to the chosen slot."""

    model_config = ConfigDict(extra="forbid")

    iris_candidates: list[str]
    marius_available: list[str]
    wren_available: list[str]
    atlas_available: list[str]
    after_marius: list[str]
    after_wren: list[str]
    after_atlas: list[str]
    chosen_slot: str | None


class PeerLedgerSummary(BaseModel):
    """One non-Iris principal's full ledger across both exchanges with that peer."""

    model_config = ConfigDict(extra="forbid")

    principal_id: str
    query_exchange_id: str
    confirm_exchange_id: str
    all_ledger_entries: list[ResidueDTO]
    policy_doc: dict[str, Any]


class FourPartyResult(BaseModel):
    """Top-level response: outcome, six exchanges, intersection trace, ledgers."""

    model_config = ConfigDict(extra="forbid")

    iris_principal_id: str
    marius_principal_id: str
    wren_principal_id: str
    atlas_principal_id: str

    success: bool
    failure_reason: str | None

    chosen_slot: str | None

    exchanges: list[BilateralExchangeRecord]

    intersection: IntersectionState | None

    marius_summary: PeerLedgerSummary
    wren_summary: PeerLedgerSummary
    atlas_summary: PeerLedgerSummary

    iris_ledger: list[ResidueDTO]

    policy_doc_iris: dict[str, Any]

    duration_ms: int


# -- Policy doc (duplicated from scenarios.py per design §6) --------------


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


def _busy_blocks(principal_id: str) -> list[tuple[str, str]]:
    """Return the synthetic busy schedule for a given principal."""
    return list(_BUSY_BLOCKS.get(principal_id, []))


def _parse_iso(ts: str) -> datetime:
    # Mesherra uses trailing "Z" UTC; datetime.fromisoformat handles +00:00.
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _slots_available(
    candidates: list[str],
    busy_blocks: list[tuple[str, str]],
    duration_minutes: int,
) -> list[str]:
    """Return the subset of candidates whose [start, start+duration) interval
    does not overlap any busy block. Pure function."""
    available: list[str] = []
    duration = timedelta(minutes=duration_minutes)
    for slot in candidates:
        slot_start = _parse_iso(slot)
        slot_end = slot_start + duration
        overlaps = False
        for busy_start_s, busy_end_s in busy_blocks:
            busy_start = _parse_iso(busy_start_s)
            busy_end = _parse_iso(busy_end_s)
            # Half-open intervals: overlap iff slot_start < busy_end and busy_start < slot_end.
            if slot_start < busy_end and busy_start < slot_end:
                overlaps = True
                break
        if not overlaps:
            available.append(slot)
    return available


def _make_peer_handler(
    principal_id: str,
    phase: str,
) -> tuple[ConsumerHandler, dict[str, Any]]:
    """Factory returning a (handler, captured) pair.

    The handler closes over ``principal_id`` and ``phase`` and writes the
    response payload it returned into ``captured`` so the orchestrator can
    read it after the bilateral completes.

    * Phase ``"query"``: the handler filters Iris's candidates against the
      peer's busy blocks and returns the available subset.
    * Phase ``"confirm"``: the handler echoes the single proposed slot
      Iris sent (acknowledgement).
    """
    captured: dict[str, Any] = {}
    busy = _busy_blocks(principal_id)

    async def handler(msg: IncomingMessage) -> OutgoingResponse:
        candidates = list(msg.payload["candidates"])
        duration = int(msg.payload["duration_minutes"])
        if phase == "query":
            available = _slots_available(candidates, busy, duration)
            response = {
                "candidates": available,
                "duration_minutes": duration,
                "constraint_hints": {"role": "responder"},
            }
        else:
            # Confirm: echo back the single proposed slot.
            response = {
                "candidates": candidates,
                "duration_minutes": duration,
                "constraint_hints": {"role": "responder"},
            }
        captured.clear()
        captured.update(response)
        return OutgoingResponse(
            payload=response,
            operation=Operation.ACCEPTANCE,
            payload_schema=PAYLOAD_SCHEMA,
        )

    return handler, captured


def _scoped_payload_for(candidates: list[str]) -> dict[str, Any]:
    """The post-airlock scoped payload Iris would emit for a given candidate set.

    Mirrors what `_strip_blocked_fields` produces from a rich proposal:
    only the allow-listed keys cross the wire.
    """
    rich = {
        "candidates": candidates,
        "duration_minutes": 30,
        "calendar_titles": ["synthetic-convening"],
        "attendee_emails": ["synthetic-attendee@example.invalid"],
        "constraint_hints": {
            "tz": "Europe/Lisbon",
            "preferred_window": {"start_hour": 9, "end_hour": 17},
        },
    }
    return _strip_blocked_fields(rich)


async def _run_bilateral(
    *,
    exchange_id: str,
    phase: str,
    iris_sdk: Mesherra,
    iris_ledger: ProvenanceLedger,
    peer_sdk: Mesherra,
    peer_ledger: ProvenanceLedger,
    peer_principal_id: str,
    candidates: list[str],
) -> BilateralExchangeRecord:
    """Boot peer listener, run send_to, stop listener, return the record."""
    handler, captured = _make_peer_handler(peer_principal_id, phase)
    peer_sdk.on_message(handler)
    # Iris registers a placeholder receiver (required by A2AAdapter though
    # she never receives in this flow).
    iris_sdk.on_message(lambda msg: None)  # type: ignore[arg-type]

    peer_port = _free_port()
    peer_handle = await peer_sdk.start_listener(
        host="127.0.0.1",
        port=peer_port,
        agent_name=f"meshycal-{peer_principal_id.split('@')[0]}",
    )

    rich_payload = {
        "candidates": candidates,
        "duration_minutes": 30,
        "calendar_titles": ["synthetic-convening"],
        "attendee_emails": ["synthetic-attendee@example.invalid"],
        "constraint_hints": {
            "tz": "Europe/Lisbon",
            "preferred_window": {"start_hour": 9, "end_hour": 17},
        },
    }
    scoped_payload_expected = _strip_blocked_fields(rich_payload)
    iris_payload_hash = content_hash(canonical_json(scoped_payload_expected))

    try:
        result = await iris_sdk.send_to(
            peer_url=f"http://127.0.0.1:{peer_port}/",
            peer_principal_id=peer_principal_id,
            payload=rich_payload,
            payload_schema=PAYLOAD_SCHEMA,
            operation=Operation.PROPOSAL,
        )
    finally:
        await peer_handle.stop()

    peer_response_payload = dict(captured)

    iris_entries = sorted(
        iris_ledger.get_by_task(result.task_id), key=lambda r: r.sequence
    )
    peer_entries = sorted(
        peer_ledger.get_by_task(result.task_id), key=lambda r: r.sequence
    )

    # Tessera-fit invariant: the peer's emit Residue carries the
    # authoritative hash of whatever bytes actually crossed the wire
    # (post-outbound-policy). Read it from the ledger rather than
    # recomputing from ``captured``, which is the pre-gateway dict and
    # would drift if the peer's outbound policy ever strips or reorders
    # a field. Same discipline as iris_payload_hash, which is computed
    # from scoped_payload_expected (= what Iris' airlock produces).
    peer_emit_entry = next(
        (e for e in peer_entries if e.action_type == ActionType.EMIT),
        None,
    )
    peer_payload_hash = (
        peer_emit_entry.payload_hash
        if peer_emit_entry is not None
        else content_hash(canonical_json(peer_response_payload))
    )

    # Use the residue's real ``sequence`` field, not the enumerate
    # position. They coincide today (contiguous per-task ledger) but
    # passing enumerate would silently coerce mismatches if the ledger
    # ever held non-contiguous sequences for a task.
    iris_dtos = [_residue_to_dto(r, r.sequence) for r in iris_entries]
    peer_dtos = [_residue_to_dto(r, r.sequence) for r in peer_entries]

    return BilateralExchangeRecord(
        exchange_id=exchange_id,
        phase=phase,
        coordinator=IRIS,
        peer=peer_principal_id,
        iris_scoped_payload=scoped_payload_expected,
        peer_response_payload=peer_response_payload,
        iris_payload_hash=iris_payload_hash,
        peer_payload_hash=peer_payload_hash,
        iris_ledger_entries=iris_dtos,
        peer_ledger_entries=peer_dtos,
        task_id=result.task_id,
    )


# -- Scenario 2 orchestrator ------------------------------------------------


# NOTE (deferred fix from bug-review wave): the body below cleans up
# stores + ledgers explicitly on the two success returns. An exception
# inside Phase B would skip those closes; Python's GC + tempfile's
# context manager still tear everything down, but cross-platform CI may
# emit ResourceWarning. A clean try/finally wrapper is the right
# eventual fix (extract body into a helper or use contextlib.ExitStack).
# Not blocking demos.

async def run_four_party() -> FourPartyResult:
    """Run a real Phase 3 four-party group-find negotiation.

    Six bilateral exchanges total: three query (A1, A2, A3) then three
    confirm (B1, B2, B3). The intersection of per-peer available slots
    is computed locally between the two phases. On empty intersection
    the orchestrator returns early with ``success=False`` and never
    initiates Phase B.
    """
    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="meshycal-phase4-fourparty-") as td:
        td_path = Path(td)

        # Per-principal signers.
        iris_signer = Signer.generate()
        marius_signer = Signer.generate()
        wren_signer = Signer.generate()
        atlas_signer = Signer.generate()

        directory = StaticDirectoryClient(
            {
                IRIS: iris_signer.public_key_b64(),
                MARIUS: marius_signer.public_key_b64(),
                WREN: wren_signer.public_key_b64(),
                ATLAS: atlas_signer.public_key_b64(),
            }
        )

        # Per-principal PolicyStores.
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
        wren_store = PolicyStore(
            db_path=td_path / "wren_policy.sqlite",
            principal_id=WREN,
            public_key_b64=wren_signer.public_key_b64(),
        )
        atlas_store = PolicyStore(
            db_path=td_path / "atlas_policy.sqlite",
            principal_id=ATLAS,
            public_key_b64=atlas_signer.public_key_b64(),
        )

        iris_policy_signed = sign_policy_doc(
            doc=_default_meshycal_policy(IRIS), signer=iris_signer
        )
        marius_policy_signed = sign_policy_doc(
            doc=_default_meshycal_policy(MARIUS), signer=marius_signer
        )
        wren_policy_signed = sign_policy_doc(
            doc=_default_meshycal_policy(WREN), signer=wren_signer
        )
        atlas_policy_signed = sign_policy_doc(
            doc=_default_meshycal_policy(ATLAS), signer=atlas_signer
        )
        iris_store.save_signed(iris_policy_signed)
        marius_store.save_signed(marius_policy_signed)
        wren_store.save_signed(wren_policy_signed)
        atlas_store.save_signed(atlas_policy_signed)

        # Per-principal ledgers.
        iris_ledger = ProvenanceLedger(
            db_path=td_path / "iris_ledger.sqlite", ledger_owner=IRIS
        )
        marius_ledger = ProvenanceLedger(
            db_path=td_path / "marius_ledger.sqlite", ledger_owner=MARIUS
        )
        wren_ledger = ProvenanceLedger(
            db_path=td_path / "wren_ledger.sqlite", ledger_owner=WREN
        )
        atlas_ledger = ProvenanceLedger(
            db_path=td_path / "atlas_ledger.sqlite", ledger_owner=ATLAS
        )

        # Per-principal SDK instances.
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
        wren_sdk = Mesherra(
            principal_id=WREN,
            signer=wren_signer,
            ledger=wren_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=wren_store,
        )
        atlas_sdk = Mesherra(
            principal_id=ATLAS,
            signer=atlas_signer,
            ledger=atlas_ledger,
            adapter=A2AAdapter(),
            directory=directory,
            policy_store=atlas_store,
        )

        exchanges: list[BilateralExchangeRecord] = []

        # -- Phase A: query each peer in turn --------------------------
        a1 = await _run_bilateral(
            exchange_id="A1",
            phase="query",
            iris_sdk=iris_sdk,
            iris_ledger=iris_ledger,
            peer_sdk=marius_sdk,
            peer_ledger=marius_ledger,
            peer_principal_id=MARIUS,
            candidates=list(_IRIS_CANDIDATES),
        )
        exchanges.append(a1)

        a2 = await _run_bilateral(
            exchange_id="A2",
            phase="query",
            iris_sdk=iris_sdk,
            iris_ledger=iris_ledger,
            peer_sdk=wren_sdk,
            peer_ledger=wren_ledger,
            peer_principal_id=WREN,
            candidates=list(_IRIS_CANDIDATES),
        )
        exchanges.append(a2)

        a3 = await _run_bilateral(
            exchange_id="A3",
            phase="query",
            iris_sdk=iris_sdk,
            iris_ledger=iris_ledger,
            peer_sdk=atlas_sdk,
            peer_ledger=atlas_ledger,
            peer_principal_id=ATLAS,
            candidates=list(_IRIS_CANDIDATES),
        )
        exchanges.append(a3)

        # -- Intersection (local) --------------------------------------
        marius_available = list(a1.peer_response_payload.get("candidates", []))
        wren_available = list(a2.peer_response_payload.get("candidates", []))
        atlas_available = list(a3.peer_response_payload.get("candidates", []))

        after_marius = [s for s in _IRIS_CANDIDATES if s in set(marius_available)]
        after_wren = [s for s in after_marius if s in set(wren_available)]
        after_atlas = [s for s in after_wren if s in set(atlas_available)]

        chosen_slot: str | None = sorted(after_atlas)[0] if after_atlas else None

        intersection = IntersectionState(
            iris_candidates=list(_IRIS_CANDIDATES),
            marius_available=marius_available,
            wren_available=wren_available,
            atlas_available=atlas_available,
            after_marius=after_marius,
            after_wren=after_wren,
            after_atlas=after_atlas,
            chosen_slot=chosen_slot,
        )

        # Helper to build per-peer ledger summaries.
        def _build_summary(
            principal_id: str,
            ledger: ProvenanceLedger,
            policy_signed: Any,
            query_record: BilateralExchangeRecord,
            confirm_record: BilateralExchangeRecord | None,
        ) -> PeerLedgerSummary:
            task_ids = [query_record.task_id]
            if confirm_record is not None:
                task_ids.append(confirm_record.task_id)
            all_residues: list[Any] = []
            for tid in task_ids:
                all_residues.extend(ledger.get_by_task(tid))
            all_residues.sort(key=lambda r: r.sequence)
            dtos = [_residue_to_dto(r, i) for i, r in enumerate(all_residues)]
            return PeerLedgerSummary(
                principal_id=principal_id,
                query_exchange_id=query_record.exchange_id,
                confirm_exchange_id=(
                    confirm_record.exchange_id if confirm_record is not None else ""
                ),
                all_ledger_entries=dtos,
                policy_doc=policy_signed.doc.to_signing_payload(),
            )

        if chosen_slot is None:
            # No common slot — return early with the three query records only.
            marius_summary = _build_summary(
                MARIUS, marius_ledger, marius_policy_signed, a1, None
            )
            wren_summary = _build_summary(
                WREN, wren_ledger, wren_policy_signed, a2, None
            )
            atlas_summary = _build_summary(
                ATLAS, atlas_ledger, atlas_policy_signed, a3, None
            )

            iris_all = []
            for ex in exchanges:
                iris_all.extend(iris_ledger.get_by_task(ex.task_id))
            iris_all.sort(key=lambda r: r.sequence)
            iris_dtos = [_residue_to_dto(r, i) for i, r in enumerate(iris_all)]

            iris_policy_doc = iris_policy_signed.doc.to_signing_payload()

            iris_store.close()
            marius_store.close()
            wren_store.close()
            atlas_store.close()
            iris_ledger.close()
            marius_ledger.close()
            wren_ledger.close()
            atlas_ledger.close()

            duration_ms = int((time.monotonic() - started) * 1000)

            return FourPartyResult(
                iris_principal_id=IRIS,
                marius_principal_id=MARIUS,
                wren_principal_id=WREN,
                atlas_principal_id=ATLAS,
                success=False,
                failure_reason="no_common_slot",
                chosen_slot=None,
                exchanges=exchanges,
                intersection=intersection,
                marius_summary=marius_summary,
                wren_summary=wren_summary,
                atlas_summary=atlas_summary,
                iris_ledger=iris_dtos,
                policy_doc_iris=iris_policy_doc,
                duration_ms=duration_ms,
            )

        # -- Phase B: confirm with each peer ---------------------------
        b1 = await _run_bilateral(
            exchange_id="B1",
            phase="confirm",
            iris_sdk=iris_sdk,
            iris_ledger=iris_ledger,
            peer_sdk=marius_sdk,
            peer_ledger=marius_ledger,
            peer_principal_id=MARIUS,
            candidates=[chosen_slot],
        )
        exchanges.append(b1)

        b2 = await _run_bilateral(
            exchange_id="B2",
            phase="confirm",
            iris_sdk=iris_sdk,
            iris_ledger=iris_ledger,
            peer_sdk=wren_sdk,
            peer_ledger=wren_ledger,
            peer_principal_id=WREN,
            candidates=[chosen_slot],
        )
        exchanges.append(b2)

        b3 = await _run_bilateral(
            exchange_id="B3",
            phase="confirm",
            iris_sdk=iris_sdk,
            iris_ledger=iris_ledger,
            peer_sdk=atlas_sdk,
            peer_ledger=atlas_ledger,
            peer_principal_id=ATLAS,
            candidates=[chosen_slot],
        )
        exchanges.append(b3)

        # -- Per-peer summaries + Iris's union ledger ------------------
        marius_summary = _build_summary(
            MARIUS, marius_ledger, marius_policy_signed, a1, b1
        )
        wren_summary = _build_summary(
            WREN, wren_ledger, wren_policy_signed, a2, b2
        )
        atlas_summary = _build_summary(
            ATLAS, atlas_ledger, atlas_policy_signed, a3, b3
        )

        iris_all = []
        for ex in exchanges:
            iris_all.extend(iris_ledger.get_by_task(ex.task_id))
        iris_all.sort(key=lambda r: r.sequence)
        iris_dtos = [_residue_to_dto(r, i) for i, r in enumerate(iris_all)]

        iris_policy_doc = iris_policy_signed.doc.to_signing_payload()

        iris_store.close()
        marius_store.close()
        wren_store.close()
        atlas_store.close()
        iris_ledger.close()
        marius_ledger.close()
        wren_ledger.close()
        atlas_ledger.close()

        duration_ms = int((time.monotonic() - started) * 1000)

        return FourPartyResult(
            iris_principal_id=IRIS,
            marius_principal_id=MARIUS,
            wren_principal_id=WREN,
            atlas_principal_id=ATLAS,
            success=True,
            failure_reason=None,
            chosen_slot=chosen_slot,
            exchanges=exchanges,
            intersection=intersection,
            marius_summary=marius_summary,
            wren_summary=wren_summary,
            atlas_summary=atlas_summary,
            iris_ledger=iris_dtos,
            policy_doc_iris=iris_policy_doc,
            duration_ms=duration_ms,
        )
