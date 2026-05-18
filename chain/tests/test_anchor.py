"""Tests for the Anchor interface and Merkle root computation."""

from __future__ import annotations

import hashlib

import pytest

from headlights_chain.anchor import (
    Anchor,
    AnchorReceipt,
    InMemoryAnchor,
    NoOpAnchor,
    merkle_proof,
    merkle_root,
    verify_merkle_proof,
)


def _h(s: str) -> str:
    """Convenience: hex SHA-256 of a string."""
    return hashlib.sha256(s.encode()).hexdigest()


# ── Merkle root ─────────────────────────────────────────────────────────


def test_merkle_root_single_leaf_is_the_leaf() -> None:
    leaf = _h("only")
    assert merkle_root([leaf]) == leaf


def test_merkle_root_two_leaves() -> None:
    a, b = _h("a"), _h("b")
    expected = hashlib.sha256(bytes.fromhex(a) + bytes.fromhex(b)).hexdigest()
    assert merkle_root([a, b]) == expected


def test_merkle_root_odd_count_duplicates_last() -> None:
    """RFC 6962-style duplication: with three leaves, the third pairs with itself
    at the lowest level."""
    a, b, c = _h("a"), _h("b"), _h("c")
    ab = hashlib.sha256(bytes.fromhex(a) + bytes.fromhex(b)).digest()
    cc = hashlib.sha256(bytes.fromhex(c) + bytes.fromhex(c)).digest()
    expected = hashlib.sha256(ab + cc).hexdigest()
    assert merkle_root([a, b, c]) == expected


def test_merkle_root_is_deterministic() -> None:
    leaves = [_h(f"x{i}") for i in range(7)]
    assert merkle_root(leaves) == merkle_root(leaves)


def test_merkle_root_distinguishes_order() -> None:
    a, b = _h("a"), _h("b")
    assert merkle_root([a, b]) != merkle_root([b, a])


def test_merkle_root_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one leaf"):
        merkle_root([])


def test_merkle_root_rejects_bad_leaves() -> None:
    with pytest.raises(ValueError):
        merkle_root(["short"])
    with pytest.raises(ValueError):
        merkle_root(["z" * 64])


# ── Merkle proofs ───────────────────────────────────────────────────────


@pytest.mark.parametrize("n", [1, 2, 3, 4, 7, 8, 16, 31])
def test_merkle_proof_roundtrip_for_every_leaf(n: int) -> None:
    leaves = [_h(f"leaf{i}") for i in range(n)]
    root = merkle_root(leaves)
    for i, leaf in enumerate(leaves):
        proof = merkle_proof(leaves, i)
        assert verify_merkle_proof(leaf, proof, root), f"proof failed for leaf {i} of {n}"


def test_merkle_proof_rejects_wrong_leaf() -> None:
    leaves = [_h(f"leaf{i}") for i in range(8)]
    root = merkle_root(leaves)
    proof = merkle_proof(leaves, 3)
    assert not verify_merkle_proof(_h("not-a-leaf"), proof, root)


def test_merkle_proof_rejects_wrong_root() -> None:
    leaves = [_h(f"leaf{i}") for i in range(8)]
    proof = merkle_proof(leaves, 3)
    assert not verify_merkle_proof(leaves[3], proof, "0" * 64)


def test_merkle_proof_out_of_range_raises() -> None:
    leaves = [_h("x")]
    with pytest.raises(ValueError):
        merkle_proof(leaves, 5)


# ── NoOpAnchor ──────────────────────────────────────────────────────────


def test_noop_anchor_returns_well_formed_receipt() -> None:
    leaves = [_h("a"), _h("b"), _h("c")]
    anchor = NoOpAnchor()
    receipt = anchor.commit(leaves)
    assert isinstance(receipt, AnchorReceipt)
    assert receipt.merkle_root == merkle_root(leaves)
    assert receipt.leaves == tuple(leaves)
    assert receipt.backend == "noop"
    assert receipt.uri is None
    assert receipt.committed_at.endswith("Z")


def test_noop_anchor_root_only_does_not_emit_receipt() -> None:
    leaves = [_h("a"), _h("b")]
    anchor = NoOpAnchor()
    root = anchor.root_only(leaves)
    assert root == merkle_root(leaves)


# ── InMemoryAnchor ──────────────────────────────────────────────────────


def test_in_memory_anchor_persists_receipts_in_order() -> None:
    anchor = InMemoryAnchor()
    r1 = anchor.commit([_h("a")])
    r2 = anchor.commit([_h("a"), _h("b")])
    assert anchor.receipts == [r1, r2]
    assert r1.uri == "mem://anchor/0"
    assert r2.uri == "mem://anchor/1"


def test_in_memory_anchor_root_matches_pure_function() -> None:
    leaves = [_h(f"x{i}") for i in range(5)]
    anchor = InMemoryAnchor()
    receipt = anchor.commit(leaves)
    assert receipt.merkle_root == merkle_root(leaves)


# ── Anchor abstract ─────────────────────────────────────────────────────


def test_cannot_instantiate_abstract_anchor() -> None:
    with pytest.raises(TypeError):
        Anchor()  # type: ignore[abstract]
