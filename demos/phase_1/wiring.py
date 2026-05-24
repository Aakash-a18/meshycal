"""Wiring helper for the Phase 1 two-agent demo.

Each scheduling agent needs a fully-wired ``Mesherra`` instance:

* an Ed25519 signer (one keypair per principal)
* a per-principal SQLite ``ProvenanceLedger``
* a per-principal ``A2AAdapter``
* a ``public_key_directory`` that knows BOTH peers' published public keys

The directory is symmetric — each side needs the other side's public key to
verify the peer's SendClaim signatures, plus its own (the verifier path
resolves the sender's principal_id, which can be either peer depending on
whose response is being checked). Assembling that dict by hand at the top
of ``agent_a.py`` and ``agent_b.py`` was the sharpest forward edge flagged
by the Phase 1 step-5 theory-aligner; this module hides exactly that
assembly and nothing more.

Per MeshyCal CLAUDE.md rule #1: this helper lives in MeshyCal's demos,
NOT in mesherra. Mesherra src is untouched. If a future Delegation does a
similar two-process demo, it'll copy this file — that's the *right* time
to extract a shared helper (CLAUDE.md #7: two examples is the minimum).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mesherra import Mesherra
from mesherra.a2a_adapter import A2AAdapter
from mesherra.crypto.primitives import Signer
from mesherra.provenance.ledger import ProvenanceLedger


@dataclass(frozen=True)
class PairedAgents:
    """Everything the demo orchestrator needs after wiring is complete.

    The ``Mesherra`` instances are the consumer-facing handles; the signers,
    ledger paths, and public-key directory are exposed so the orchestrator
    can do post-hoc verification (e.g., re-load the ledger files cold and
    re-verify every SendClaim signature using the captured public keys).
    """

    agent_a: Mesherra
    agent_b: Mesherra
    signer_a: Signer
    signer_b: Signer
    ledger_path_a: Path
    ledger_path_b: Path
    public_key_directory: dict[str, str]


def build_agent_pair(
    *,
    principal_a_id: str,
    principal_b_id: str,
    ledger_dir: Path,
    signer_a: Signer | None = None,
    signer_b: Signer | None = None,
) -> PairedAgents:
    """Wire up two Mesherra instances ready to talk to each other.

    Args:
        principal_a_id: Identity of the first agent (e.g., ``user-a@phase1.local``).
        principal_b_id: Identity of the second agent.
        ledger_dir: Directory in which to create the two SQLite ledger files.
            Must exist; this helper does NOT create it (the orchestrator
            owns lifecycle of the demo's data root).
        signer_a: Optional pre-generated Ed25519 signer for A. If omitted,
            a fresh keypair is generated. Tests may pass a fixed signer for
            determinism; the demo just calls without it.
        signer_b: Same, for B.

    Returns:
        A :class:`PairedAgents` carrying both wired Mesherra handles plus the
        artifacts the orchestrator needs for the SPEC §5 end-state assertions.

    Raises:
        FileNotFoundError: ``ledger_dir`` does not exist.
        ValueError: the two principal ids are identical (a one-principal
            two-ledger setup is a programming error here — symmetric
            assembly assumes two distinct principals).
    """
    if principal_a_id == principal_b_id:
        raise ValueError(
            f"principal_a_id and principal_b_id must differ; got "
            f"{principal_a_id!r} twice. The two-agent demo requires two "
            "distinct principals."
        )
    if not ledger_dir.is_dir():
        raise FileNotFoundError(
            f"ledger_dir {ledger_dir!s} does not exist. The orchestrator "
            "is expected to create the demo's data root before wiring."
        )

    signer_a = signer_a or Signer.generate()
    signer_b = signer_b or Signer.generate()

    # Symmetric public-key directory: each side carries both peers'
    # published public keys. The verifier resolves whichever principal_id
    # is on the SendClaim being checked.
    directory = {
        principal_a_id: signer_a.public_key_b64(),
        principal_b_id: signer_b.public_key_b64(),
    }

    ledger_path_a = ledger_dir / f"{_safe(principal_a_id)}.sqlite"
    ledger_path_b = ledger_dir / f"{_safe(principal_b_id)}.sqlite"

    ledger_a = ProvenanceLedger(db_path=ledger_path_a, ledger_owner=principal_a_id)
    ledger_b = ProvenanceLedger(db_path=ledger_path_b, ledger_owner=principal_b_id)

    agent_a = Mesherra(
        principal_id=principal_a_id,
        signer=signer_a,
        ledger=ledger_a,
        adapter=A2AAdapter(),
        public_key_directory=directory,
    )
    agent_b = Mesherra(
        principal_id=principal_b_id,
        signer=signer_b,
        ledger=ledger_b,
        adapter=A2AAdapter(),
        public_key_directory=directory,
    )

    return PairedAgents(
        agent_a=agent_a,
        agent_b=agent_b,
        signer_a=signer_a,
        signer_b=signer_b,
        ledger_path_a=ledger_path_a,
        ledger_path_b=ledger_path_b,
        public_key_directory=directory,
    )


def _safe(principal_id: str) -> str:
    """Map a principal id to a filesystem-safe filename stem.

    ``user-a@phase1.local`` -> ``user-a_phase1_local``. The exact mapping
    doesn't matter — just needs to be deterministic and not contain
    path-separator or shell-special chars.
    """
    return principal_id.replace("@", "_").replace(".", "_").replace("/", "_")
