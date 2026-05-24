"""Unit tests for the demo wiring helper.

Covers the boilerplate-hiding contract: two distinct principals, symmetric
public-key directory, separate ledgers, separate signers, separate adapters.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mesherra import Mesherra
from mesherra.crypto.primitives import Signer

from wiring import PairedAgents, build_agent_pair


_A_ID = "user-a@phase1.local"
_B_ID = "user-b@phase1.local"


class TestBuildAgentPair:
    def test_returns_two_distinct_mesherra_instances(self, tmp_path: Path) -> None:
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )
        assert isinstance(pair, PairedAgents)
        assert isinstance(pair.agent_a, Mesherra)
        assert isinstance(pair.agent_b, Mesherra)
        assert pair.agent_a is not pair.agent_b
        assert pair.agent_a.principal_id == _A_ID
        assert pair.agent_b.principal_id == _B_ID

    def test_public_key_directory_is_symmetric(self, tmp_path: Path) -> None:
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )
        # Both principals appear, each with the matching signer's pubkey.
        assert set(pair.public_key_directory.keys()) == {_A_ID, _B_ID}
        assert pair.public_key_directory[_A_ID] == pair.signer_a.public_key_b64()
        assert pair.public_key_directory[_B_ID] == pair.signer_b.public_key_b64()

    def test_each_agent_sees_both_pubkeys(self, tmp_path: Path) -> None:
        """If either side's directory were missing the peer, SendClaim
        verification would fail on the very first inbound message."""
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )
        # Same dict identity is fine, but the contents must include both.
        # Use the private attr only for this invariant check — production
        # code never reaches in like this.
        for agent in (pair.agent_a, pair.agent_b):
            directory = agent._public_key_directory  # type: ignore[attr-defined]
            assert _A_ID in directory
            assert _B_ID in directory

    def test_ledger_files_are_per_principal(self, tmp_path: Path) -> None:
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )
        assert pair.ledger_path_a != pair.ledger_path_b
        assert pair.ledger_path_a.exists()
        assert pair.ledger_path_b.exists()
        assert pair.ledger_path_a.parent == tmp_path
        assert pair.ledger_path_b.parent == tmp_path

    def test_signers_are_independent(self, tmp_path: Path) -> None:
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )
        # Two freshly-generated keypairs must produce different public keys
        # (probability of collision is astronomically small for Ed25519).
        assert pair.signer_a.public_key_b64() != pair.signer_b.public_key_b64()

    def test_accepts_caller_supplied_signers(self, tmp_path: Path) -> None:
        sa = Signer.generate()
        sb = Signer.generate()
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
            signer_a=sa,
            signer_b=sb,
        )
        assert pair.signer_a is sa
        assert pair.signer_b is sb
        assert pair.public_key_directory[_A_ID] == sa.public_key_b64()
        assert pair.public_key_directory[_B_ID] == sb.public_key_b64()

    def test_rejects_identical_principal_ids(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="must differ"):
            build_agent_pair(
                principal_a_id=_A_ID,
                principal_b_id=_A_ID,
                ledger_dir=tmp_path,
            )

    def test_rejects_missing_ledger_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        with pytest.raises(FileNotFoundError, match="does not exist"):
            build_agent_pair(
                principal_a_id=_A_ID,
                principal_b_id=_B_ID,
                ledger_dir=missing,
            )

    def test_ledger_owner_matches_principal_after_wiring(self, tmp_path: Path) -> None:
        """If the symmetric assembly ever crossed wires (A's ledger pointed at
        B's principal), Mesherra's constructor would raise. This test
        guards that the wiring helper itself doesn't introduce that bug."""
        pair = build_agent_pair(
            principal_a_id=_A_ID,
            principal_b_id=_B_ID,
            ledger_dir=tmp_path,
        )
        # Reading private attrs again for the invariant check.
        assert pair.agent_a._ledger.ledger_owner == _A_ID  # type: ignore[attr-defined]
        assert pair.agent_b._ledger.ledger_owner == _B_ID  # type: ignore[attr-defined]
