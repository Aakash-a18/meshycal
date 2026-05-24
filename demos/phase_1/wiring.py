"""Wiring helper for the Phase 1 two-agent demo.

Each scheduling agent needs a fully-wired ``Mesherra`` instance:

* an Ed25519 signer (one keypair per principal)
* a per-principal SQLite ``ProvenanceLedger``
* a per-principal ``A2AAdapter``
* a ``DirectoryClient`` that resolves BOTH peers' published public keys
  (Phase 2 sub-step 1: a single shared ``StaticDirectoryClient``;
  Phase 2 sub-step 4: per-agent ``HTTPDirectoryClient`` pointing at a
  live Directory service)

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
from mesherra.identity import DirectoryClient, StaticDirectoryClient
from mesherra.policy import PolicyStore
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
    # Phase 3: per-principal PolicyStores (None when bypass mode is
    # active — e.g., Phase 1/2 tests that do not exercise scoping).
    policy_store_a: PolicyStore | None
    policy_store_b: PolicyStore | None


def build_agent_pair(
    *,
    principal_a_id: str,
    principal_b_id: str,
    ledger_dir: Path,
    signer_a: Signer | None = None,
    signer_b: Signer | None = None,
    directory_a: DirectoryClient | None = None,
    directory_b: DirectoryClient | None = None,
    policy_store_a: PolicyStore | None = None,
    policy_store_b: PolicyStore | None = None,
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
        directory_a: Optional :class:`DirectoryClient` for agent A. If both
            ``directory_a`` and ``directory_b`` are omitted, the helper
            falls back to the Phase 1 path: a single shared
            :class:`StaticDirectoryClient` constructed from the two
            signers' public keys. The orchestrator (run_demo.py) supplies
            per-agent ``HTTPDirectoryClient`` instances pointing at a live
            Directory service after Phase 2 sub-step 4.
        directory_b: Same, for B. If one of ``directory_a`` / ``directory_b``
            is supplied the other must be too — mixed wiring (one live,
            one static) is a programming error.

    Returns:
        A :class:`PairedAgents` carrying both wired Mesherra handles plus the
        artifacts the orchestrator needs for the SPEC §5 end-state assertions.

    Raises:
        FileNotFoundError: ``ledger_dir`` does not exist.
        ValueError: the two principal ids are identical, or only one of
            ``directory_a`` / ``directory_b`` was supplied.
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
    if (directory_a is None) != (directory_b is None):
        raise ValueError(
            "directory_a and directory_b must both be provided or both omitted. "
            "Mixed live/static wiring is a programming error."
        )
    if (policy_store_a is None) != (policy_store_b is None):
        raise ValueError(
            "policy_store_a and policy_store_b must both be provided or both "
            "omitted. Mixed enforcement (one enforcing, one bypassing) is a "
            "programming error and would break the demo's symmetric proof."
        )

    signer_a = signer_a or Signer.generate()
    signer_b = signer_b or Signer.generate()

    # Symmetric public-key directory: each side carries both peers'
    # published public keys. Kept on PairedAgents as a snapshot for the
    # orchestrator's cold-reload verification path, which re-verifies
    # signed Residue entries directly without going through the SDK.
    directory_map = {
        principal_a_id: signer_a.public_key_b64(),
        principal_b_id: signer_b.public_key_b64(),
    }

    # Phase 2 sub-step 1+4: the gateways consume a DirectoryClient interface
    # rather than a raw dict. Two paths:
    #
    # * directory_a / directory_b NOT provided → fall back to the Phase 1
    #   path: a single shared StaticDirectoryClient. Fine because the
    #   static client is stateless after construction.
    # * directory_a / directory_b provided → orchestrator built per-agent
    #   HTTPDirectoryClient instances pointing at a live Directory.
    #   Per-agent because the HTTP client carries per-instance state
    #   (connection pool, future auth tokens).
    if directory_a is None:
        shared_static = StaticDirectoryClient(directory_map)
        directory_a = shared_static
        directory_b = shared_static

    ledger_path_a = ledger_dir / f"{_safe(principal_a_id)}.sqlite"
    ledger_path_b = ledger_dir / f"{_safe(principal_b_id)}.sqlite"

    ledger_a = ProvenanceLedger(db_path=ledger_path_a, ledger_owner=principal_a_id)
    ledger_b = ProvenanceLedger(db_path=ledger_path_b, ledger_owner=principal_b_id)

    agent_a = Mesherra(
        principal_id=principal_a_id,
        signer=signer_a,
        ledger=ledger_a,
        adapter=A2AAdapter(),
        directory=directory_a,
        policy_store=policy_store_a,
    )
    agent_b = Mesherra(
        principal_id=principal_b_id,
        signer=signer_b,
        ledger=ledger_b,
        adapter=A2AAdapter(),
        directory=directory_b,
        policy_store=policy_store_b,
    )

    return PairedAgents(
        agent_a=agent_a,
        agent_b=agent_b,
        signer_a=signer_a,
        signer_b=signer_b,
        ledger_path_a=ledger_path_a,
        ledger_path_b=ledger_path_b,
        public_key_directory=directory_map,
        policy_store_a=policy_store_a,
        policy_store_b=policy_store_b,
    )


def _safe(principal_id: str) -> str:
    """Map a principal id to a filesystem-safe filename stem.

    ``user-a@phase1.local`` -> ``user-a_phase1_local``. The exact mapping
    doesn't matter — just needs to be deterministic and not contain
    path-separator or shell-special chars.
    """
    return principal_id.replace("@", "_").replace(".", "_").replace("/", "_")
