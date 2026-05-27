"""Chain: the session-scoped tamper-evident ledger.

Per ADR-002 the chain scope is one session. Genesis is a `lifecycle/session_start`
record with null parent_record_id and prev_hash. Each subsequent record links
to the previous via parent_record_id (UUID) and prev_hash (hex SHA-256 of the
previous record's canonical bytes, *including* the previous record's signature
if one was attached, per AAT §4.1).

The chain primitive is persistence-agnostic. Records live in an in-memory list.
A storage adapter is responsible for durability, anchoring, and tenancy.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Iterator

from headlights_chain.canonical import (
    record_hash_for_chain,
    record_hash_for_signing,
    sha256_hex,
)
from headlights_chain.enums import ActionType, LifecycleEvent, Outcome, TrustLevel
from headlights_chain.records import Record
from headlights_chain.signatures import SigningKey, VerifyingKey


def _parse_rfc3339(ts: str) -> datetime:
    """Parse an AAT-permitted RFC 3339 timestamp into a timezone-aware datetime.

    Both 'Z' and '±HH:MM' offsets are accepted by the Record validator, so
    timestamp comparisons must normalise to a single timezone before ordering.
    Lexicographic comparison of the raw strings is wrong for mixed-timezone
    chains.
    """
    # Python 3.10's fromisoformat does not accept 'Z'; normalise to '+00:00'.
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of Chain.verify().

    is_intact   True iff every link and (when keys are provided) every
                signature checks out.
    failed_position  0-indexed position of the first failing record, or None.
    reason      Short human-readable explanation, or None when intact.
    """

    is_intact: bool
    failed_position: int | None
    reason: str | None

    @classmethod
    def ok(cls) -> "VerificationResult":
        return cls(True, None, None)

    @classmethod
    def fail(cls, position: int, reason: str) -> "VerificationResult":
        return cls(False, position, reason)


@dataclass(frozen=True)
class ChainState:
    """Snapshot of chain progress, suitable for storage."""

    session_id: str
    agent_id: str
    length: int  # number of records, including genesis
    last_hash: str  # hex SHA-256 of the most recent record
    closed: bool


class Chain:
    """A session-scoped AAT conduct chain."""

    def __init__(
        self,
        records: list[Record],
        *,
        signing_key: SigningKey | None = None,
    ) -> None:
        if not records:
            raise ValueError("A Chain must have at least a genesis record.")
        self._records: list[Record] = list(records)
        self._signing_key = signing_key

    # ── Factories ───────────────────────────────────────────────────────

    @classmethod
    def genesis(
        cls,
        *,
        agent_id: str,
        agent_version: str,
        signing_key: SigningKey | None = None,
        session_id: str | None = None,
        trust_level: TrustLevel | str = TrustLevel.L1,
        genesis_detail: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> "Chain":
        """Create a new chain with a freshly minted genesis record.

        Per AAT §4.3 the genesis MUST have:
          - action_type = lifecycle
          - action_detail.event = session_start
          - parent_record_id = null
          - prev_hash = null
        """
        detail: dict[str, Any] = dict(genesis_detail or {})
        detail["event"] = LifecycleEvent.SESSION_START.value

        record = Record.new(
            agent_id=agent_id,
            agent_version=agent_version,
            session_id=session_id or str(uuid.uuid4()),
            action_type=ActionType.LIFECYCLE,
            action_detail=detail,
            outcome=Outcome.SUCCESS,
            trust_level=trust_level,
            parent_record_id=None,
            prev_hash=None,
            timestamp=timestamp,
        )
        record = _maybe_sign(record, signing_key)
        return cls([record], signing_key=signing_key)

    # ── Mutation ────────────────────────────────────────────────────────

    def append(
        self,
        *,
        action_type: ActionType | str,
        action_detail: dict[str, Any],
        outcome: Outcome | str,
        trust_level: TrustLevel | str,
        timestamp: str | None = None,
        **optional: Any,
    ) -> tuple[int, str]:
        """Append a record. Returns (position, hex_sha256_of_complete_record)."""
        if self.is_closed:
            raise RuntimeError(
                "Cannot append: session has been closed (session_end written)."
            )

        prev = self._records[-1]
        prev_complete_hash = record_hash_for_chain(prev.to_canonical_dict())

        record = Record.new(
            agent_id=prev.agent_id,
            agent_version=prev.agent_version,
            session_id=prev.session_id,
            action_type=action_type,
            action_detail=action_detail,
            outcome=outcome,
            trust_level=trust_level,
            parent_record_id=prev.record_id,
            prev_hash=prev_complete_hash,
            timestamp=timestamp,
            **optional,
        )
        record = _maybe_sign(record, self._signing_key)
        self._records.append(record)
        new_hash = record_hash_for_chain(record.to_canonical_dict())
        return (len(self._records) - 1, new_hash)

    def close(
        self,
        *,
        trust_level: TrustLevel | str | None = None,
        timestamp: str | None = None,
    ) -> tuple[int, str]:
        """Write the session_end record per AAT §6.3.

        action_detail carries:
          event         = "session_end"
          session_hash  = SHA-256( raw_prev_hash_1 || raw_prev_hash_2 || ... )
          record_count  = total records including this one
        """
        if self.is_closed:
            raise RuntimeError("Chain is already closed.")

        prev = self._records[-1]
        prev_complete_hash = record_hash_for_chain(prev.to_canonical_dict())

        # Concatenate raw 32-byte digests of every record's prev_hash except
        # genesis (whose prev_hash is null). The close record's own prev_hash
        # (= prev_complete_hash) is part of the concatenation per spec.
        raw_digests = [
            bytes.fromhex(r.prev_hash)
            for r in self._records[1:]
            if r.prev_hash is not None
        ]
        raw_digests.append(bytes.fromhex(prev_complete_hash))
        session_hash = sha256_hex(b"".join(raw_digests))

        detail = {
            "event": LifecycleEvent.SESSION_END.value,
            "session_hash": session_hash,
            "record_count": len(self._records) + 1,
        }

        record = Record.new(
            agent_id=prev.agent_id,
            agent_version=prev.agent_version,
            session_id=prev.session_id,
            action_type=ActionType.LIFECYCLE,
            action_detail=detail,
            outcome=Outcome.SUCCESS,
            trust_level=trust_level or prev.trust_level,
            parent_record_id=prev.record_id,
            prev_hash=prev_complete_hash,
            timestamp=timestamp,
        )
        record = _maybe_sign(record, self._signing_key)
        self._records.append(record)
        return (len(self._records) - 1, record_hash_for_chain(record.to_canonical_dict()))

    # ── Inspection ──────────────────────────────────────────────────────

    @property
    def state(self) -> ChainState:
        last = self._records[-1]
        return ChainState(
            session_id=last.session_id,
            agent_id=last.agent_id,
            length=len(self._records),
            last_hash=record_hash_for_chain(last.to_canonical_dict()),
            closed=self.is_closed,
        )

    @property
    def is_closed(self) -> bool:
        last = self._records[-1]
        return (
            last.action_type == ActionType.LIFECYCLE
            and last.action_detail.get("event") == LifecycleEvent.SESSION_END.value
        )

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[Record]:
        return iter(self._records)

    def records(self) -> list[Record]:
        """Defensive copy of the records list."""
        return list(self._records)

    # ── Verification ────────────────────────────────────────────────────

    def verify(
        self,
        *,
        verifying_key: VerifyingKey | None = None,
    ) -> VerificationResult:
        """Verify chain integrity.

        Checks at each position:
          1. Genesis invariants (parent_record_id and prev_hash null;
             action_type=lifecycle; action_detail.event=session_start)
          2. parent_record_id matches the previous record's record_id
          3. prev_hash matches the SHA-256 of the previous record's canonical bytes
          4. session_id consistent across the chain
          5. agent_id consistent across the chain
          6. timestamps non-decreasing (AAT §3.3)
          7. signature (if present and verifying_key supplied) verifies

        If the last record is a session_end, the session_hash is recomputed
        and compared.
        """
        return _verify_records(self._records, verifying_key=verifying_key)

    # ── Export / Import ─────────────────────────────────────────────────

    def export_records(self) -> list[dict[str, Any]]:
        """Return the chain as a list of canonical-form dicts.

        The exported list is round-trippable through Chain.from_records.
        """
        return [r.to_canonical_dict() for r in self._records]

    @classmethod
    def from_records(cls, records: Iterable[dict[str, Any]]) -> "Chain":
        """Reconstruct a chain from its canonical export.

        The returned chain has no signing key — it is for inspection and
        verification only.
        """
        parsed = [Record(**r) for r in records]
        return cls(parsed, signing_key=None)


# ── Internals ───────────────────────────────────────────────────────────


def _maybe_sign(record: Record, signing_key: SigningKey | None) -> Record:
    """If a signing key is provided, attach an AAT §4.2 signature."""
    if signing_key is None:
        return record
    body = record.to_canonical_dict(include_signature=False)
    digest = record_hash_for_signing(body)
    signature = signing_key.sign_digest(digest)
    return record.model_copy(update={"signature": signature})


def _verify_records(
    records: list[Record],
    *,
    verifying_key: VerifyingKey | None,
) -> VerificationResult:
    if not records:
        return VerificationResult.fail(0, "empty chain")

    first = records[0]
    if first.parent_record_id is not None or first.prev_hash is not None:
        return VerificationResult.fail(
            0, "genesis record must have null parent_record_id and prev_hash"
        )
    if first.action_type != ActionType.LIFECYCLE:
        return VerificationResult.fail(
            0, "genesis record must have action_type=lifecycle"
        )
    if first.action_detail.get("event") != LifecycleEvent.SESSION_START.value:
        return VerificationResult.fail(
            0, "genesis record must have action_detail.event=session_start"
        )

    expected_session_id = first.session_id
    expected_agent_id = first.agent_id

    prev_complete_hash: str | None = None
    prev_record_id: str | None = None
    prev_timestamp: str | None = None

    for position, record in enumerate(records):
        if record.session_id != expected_session_id:
            return VerificationResult.fail(
                position,
                f"session_id mismatch (expected {expected_session_id}, got {record.session_id})",
            )
        if record.agent_id != expected_agent_id:
            return VerificationResult.fail(
                position,
                f"agent_id mismatch (expected {expected_agent_id}, got {record.agent_id})",
            )

        if position == 0:
            if record.parent_record_id is not None or record.prev_hash is not None:
                return VerificationResult.fail(
                    0, "genesis record nullability violated"
                )
        else:
            if record.parent_record_id != prev_record_id:
                return VerificationResult.fail(
                    position,
                    f"parent_record_id chain broken: record claims "
                    f"parent={record.parent_record_id}, expected={prev_record_id}",
                )
            if record.prev_hash != prev_complete_hash:
                return VerificationResult.fail(
                    position,
                    f"prev_hash mismatch: record claims {record.prev_hash}, "
                    f"computed {prev_complete_hash}",
                )

        if prev_timestamp is not None and _parse_rfc3339(record.timestamp) < _parse_rfc3339(prev_timestamp):
            return VerificationResult.fail(
                position,
                f"timestamp regression: {record.timestamp} < {prev_timestamp}",
            )

        if record.signature is not None and verifying_key is not None:
            body = record.to_canonical_dict(include_signature=False)
            digest = record_hash_for_signing(body)
            if not verifying_key.verify_digest(record.signature, digest):
                return VerificationResult.fail(
                    position, "signature failed to verify"
                )

        prev_complete_hash = record_hash_for_chain(record.to_canonical_dict())
        prev_record_id = record.record_id
        prev_timestamp = record.timestamp

    # If closed, validate session_hash claim.
    last = records[-1]
    if (
        last.action_type == ActionType.LIFECYCLE
        and last.action_detail.get("event") == LifecycleEvent.SESSION_END.value
    ):
        claimed = last.action_detail.get("session_hash")
        raw_digests = [
            bytes.fromhex(r.prev_hash)
            for r in records[1:]
            if r.prev_hash is not None
        ]
        computed = sha256_hex(b"".join(raw_digests))
        if claimed != computed:
            return VerificationResult.fail(
                len(records) - 1,
                f"session_hash mismatch: claimed {claimed}, computed {computed}",
            )
        expected_count = last.action_detail.get("record_count")
        if expected_count is not None and expected_count != len(records):
            return VerificationResult.fail(
                len(records) - 1,
                f"record_count mismatch: claimed {expected_count}, actual {len(records)}",
            )

    return VerificationResult.ok()
