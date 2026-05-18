"""External anchoring of session hashes.

Per ADR-005, once per UTC day the hosted platform computes a Merkle root over
every `session_hash` closed that day per tenant and commits the root to an
external append-only store (Azure Immutable Blob, S3 Object Lock, OpenTimestamps,
a blockchain — whatever the deployment chooses). The chain primitive itself
does not perform the commit; it just produces the Merkle root and exposes an
`Anchor` interface that storage adapters implement.

The Merkle construction is deterministic:

    leaves      = sha-256 digests of `session_hash` strings (decoded from hex)
    duplication = if a level has an odd number of nodes, the last is duplicated
    internal    = sha256(left || right)
    root        = the single remaining 32-byte digest, emitted as hex

This is the same construction used by Certificate Transparency (RFC 6962) and
many timestamping services, so verifiers in other ecosystems can replay our
roots with their own libraries.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence


def _utc_now_rfc3339() -> str:
    now = datetime.now(timezone.utc)
    millis = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def _hash_pair(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(left + right).digest()


def merkle_root(session_hashes_hex: Sequence[str]) -> str:
    """Compute a deterministic Merkle root over a list of hex SHA-256 strings.

    Returns a 64-character lowercase hex string. Raises ValueError if any leaf
    is not a valid 64-character hex digest, or if the input is empty.
    """
    if not session_hashes_hex:
        raise ValueError("merkle_root requires at least one leaf")

    level: list[bytes] = []
    for leaf in session_hashes_hex:
        if not isinstance(leaf, str) or len(leaf) != 64:
            raise ValueError(f"leaf must be a 64-character hex string; got {leaf!r}")
        try:
            level.append(bytes.fromhex(leaf))
        except ValueError as e:
            raise ValueError(f"leaf is not valid hex: {leaf!r}") from e

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])  # duplicate last (RFC 6962-style)
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]

    return level[0].hex()


def merkle_proof(
    session_hashes_hex: Sequence[str], index: int
) -> list[tuple[str, str]]:
    """Build an inclusion proof for the leaf at `index`.

    Returns a list of (sibling_hex, position) tuples where position is "L" if
    the sibling is on the left, "R" if on the right. To verify, the caller
    starts with the leaf, hashes it with each sibling in order, and checks the
    final value against the published Merkle root.
    """
    if not session_hashes_hex:
        raise ValueError("merkle_proof requires at least one leaf")
    if not 0 <= index < len(session_hashes_hex):
        raise ValueError(
            f"index {index} out of range for {len(session_hashes_hex)} leaves"
        )

    level: list[bytes] = [bytes.fromhex(leaf) for leaf in session_hashes_hex]
    proof: list[tuple[str, str]] = []
    i = index

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        if i % 2 == 0:
            # sibling is to the right
            proof.append((level[i + 1].hex(), "R"))
        else:
            proof.append((level[i - 1].hex(), "L"))
        level = [_hash_pair(level[j], level[j + 1]) for j in range(0, len(level), 2)]
        i //= 2

    return proof


def verify_merkle_proof(
    leaf_hex: str,
    proof: list[tuple[str, str]],
    expected_root_hex: str,
) -> bool:
    """Verify an inclusion proof produced by `merkle_proof`."""
    try:
        current = bytes.fromhex(leaf_hex)
        for sibling_hex, position in proof:
            sibling = bytes.fromhex(sibling_hex)
            if position == "L":
                current = _hash_pair(sibling, current)
            elif position == "R":
                current = _hash_pair(current, sibling)
            else:
                return False
        return current.hex() == expected_root_hex
    except ValueError:
        return False


@dataclass(frozen=True)
class AnchorReceipt:
    """The result of committing a Merkle root to an external store."""

    merkle_root: str  # 64-char lowercase hex
    leaves: tuple[str, ...]  # the session_hashes that composed the tree
    committed_at: str  # RFC 3339 timestamp
    backend: str  # human-readable label, e.g. "noop", "azure-immutable-blob"
    uri: str | None = None  # link to the external commitment, if applicable
    metadata: dict[str, str] = field(default_factory=dict)


class Anchor(ABC):
    """Abstract base for external-anchor backends."""

    backend_name: str = "abstract"

    @abstractmethod
    def commit(self, session_hashes: Sequence[str]) -> AnchorReceipt:
        """Compute the Merkle root over `session_hashes` and commit it
        externally. Implementations MUST be idempotent for identical inputs."""

    def root_only(self, session_hashes: Sequence[str]) -> str:
        """Compute the root without committing — useful for dry-runs."""
        return merkle_root(session_hashes)


class NoOpAnchor(Anchor):
    """An anchor that computes the root but does not commit anywhere.

    Useful as the default for self-hosters who have not configured an external
    backend, and as the default in tests. Receipts are well-formed; their
    `uri` is None.
    """

    backend_name = "noop"

    def commit(self, session_hashes: Sequence[str]) -> AnchorReceipt:
        root = merkle_root(session_hashes)
        return AnchorReceipt(
            merkle_root=root,
            leaves=tuple(session_hashes),
            committed_at=_utc_now_rfc3339(),
            backend=self.backend_name,
            uri=None,
        )


class InMemoryAnchor(Anchor):
    """An anchor that keeps every receipt in memory. Test fixture.

    Each `commit` call appends to `self.receipts` in insertion order.
    """

    backend_name = "in-memory"

    def __init__(self) -> None:
        self.receipts: list[AnchorReceipt] = []

    def commit(self, session_hashes: Sequence[str]) -> AnchorReceipt:
        root = merkle_root(session_hashes)
        receipt = AnchorReceipt(
            merkle_root=root,
            leaves=tuple(session_hashes),
            committed_at=_utc_now_rfc3339(),
            backend=self.backend_name,
            uri=f"mem://anchor/{len(self.receipts)}",
        )
        self.receipts.append(receipt)
        return receipt
