"""Bridge between the storage layer and the chain primitive.

The server holds records in SQLite and only reconstructs Chain objects when
it needs the primitive's logic (computing the next prev_hash, verifying an
exported chain). This module is the glue.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from headlights_chain import Chain
from headlights_chain.canonical import (
    canonical_bytes,
    record_hash_for_chain,
    sha256_hex,
)
from headlights_chain.enums import ActionType, LifecycleEvent, Outcome, TrustLevel
from headlights_chain.records import Record, utc_now_rfc3339

from headlights_server.storage import SessionRow, Store

_SLUG_PATTERN = re.compile(r"[^a-z0-9-]+")


def make_agent_id(prefix: str, agent_name: str) -> str:
    """Generate a stable agent_id URI from a human-readable name."""
    slug = _SLUG_PATTERN.sub("-", agent_name.lower()).strip("-")[:60] or "agent"
    suffix = uuid.uuid4().hex[:10]
    return f"{prefix}{slug}-{suffix}"


def utc_now() -> str:
    now = datetime.now(timezone.utc)
    millis = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def open_session(
    *,
    store: Store,
    agent_id: str,
    agent_version: str,
    trust_level: TrustLevel,
    genesis_detail: dict[str, Any],
) -> tuple[str, int, str, str]:
    """Open a session: write the SessionRow and the genesis Record.

    Returns (session_id, position=0, record_hash_hex, started_at).
    """
    detail = dict(genesis_detail or {})
    detail["event"] = LifecycleEvent.SESSION_START.value
    started_at = utc_now()

    record = Record.new(
        agent_id=agent_id,
        agent_version=agent_version,
        session_id=str(uuid.uuid4()),
        action_type=ActionType.LIFECYCLE,
        action_detail=detail,
        outcome=Outcome.SUCCESS,
        trust_level=trust_level,
        parent_record_id=None,
        prev_hash=None,
        timestamp=started_at,
    )
    canonical_dict = record.to_canonical_dict()

    store.create_session(
        SessionRow(
            session_id=record.session_id,
            agent_id=agent_id,
            started_at=started_at,
            closed_at=None,
            session_hash=None,
        )
    )
    store.append_record(
        session_id=record.session_id,
        position=0,
        record_id=record.record_id,
        timestamp=record.timestamp,
        canonical_json=_canonical_to_json(canonical_dict),
    )
    record_hash = record_hash_for_chain(canonical_dict)
    return (record.session_id, 0, record_hash, started_at)


def append_action(
    *,
    store: Store,
    agent_id: str,
    agent_version: str,
    session_id: str,
    action_type: ActionType,
    action_detail: dict[str, Any],
    outcome: Outcome,
    trust_level: TrustLevel,
    optional_fields: dict[str, Any] | None = None,
) -> tuple[int, str, str]:
    """Append an action record. Returns (position, record_id, record_hash_hex)."""
    last = store.get_last_record(session_id)
    if last is None:
        raise LookupError(f"session {session_id} has no genesis record")
    prev_position, prev_dict = last

    prev_complete_hash = record_hash_for_chain(prev_dict)
    record = Record.new(
        agent_id=agent_id,
        agent_version=agent_version,
        session_id=session_id,
        action_type=action_type,
        action_detail=action_detail,
        outcome=outcome,
        trust_level=trust_level,
        parent_record_id=prev_dict["record_id"],
        prev_hash=prev_complete_hash,
        **(optional_fields or {}),
    )
    canonical_dict = record.to_canonical_dict()
    new_position = prev_position + 1

    store.append_record(
        session_id=session_id,
        position=new_position,
        record_id=record.record_id,
        timestamp=record.timestamp,
        canonical_json=_canonical_to_json(canonical_dict),
    )
    return (new_position, record.record_id, record_hash_for_chain(canonical_dict))


def close_session(
    *,
    store: Store,
    agent_id: str,
    agent_version: str,
    session_id: str,
    trust_level: TrustLevel = TrustLevel.L1,
) -> tuple[int, str, str]:
    """Close a session per AAT §6.3. Returns (record_count, session_hash, closed_at)."""
    records = store.get_session_records(session_id)
    if not records:
        raise LookupError(f"session {session_id} has no records")

    last = records[-1]

    # Compute session_hash over the concatenated raw prev_hash digests of
    # every record after genesis, plus the close record's own prev_hash.
    prev_complete_hash = record_hash_for_chain(last)
    raw_digests = [
        bytes.fromhex(r["prev_hash"]) for r in records[1:] if r.get("prev_hash")
    ]
    raw_digests.append(bytes.fromhex(prev_complete_hash))
    session_hash = sha256_hex(b"".join(raw_digests))

    closed_at = utc_now()
    detail = {
        "event": LifecycleEvent.SESSION_END.value,
        "session_hash": session_hash,
        "record_count": len(records) + 1,
    }
    record = Record.new(
        agent_id=agent_id,
        agent_version=agent_version,
        session_id=session_id,
        action_type=ActionType.LIFECYCLE,
        action_detail=detail,
        outcome=Outcome.SUCCESS,
        trust_level=trust_level,
        parent_record_id=last["record_id"],
        prev_hash=prev_complete_hash,
        timestamp=closed_at,
    )
    canonical_dict = record.to_canonical_dict()
    new_position = len(records)
    store.append_record(
        session_id=session_id,
        position=new_position,
        record_id=record.record_id,
        timestamp=record.timestamp,
        canonical_json=_canonical_to_json(canonical_dict),
    )
    store.close_session(session_id, session_hash, closed_at)
    return (new_position + 1, session_hash, closed_at)


def verify_session(store: Store, session_id: str) -> Chain:
    """Reconstruct a Chain from storage and return it. Caller can run verify()."""
    records = store.get_session_records(session_id)
    if not records:
        raise LookupError(f"session {session_id} has no records")
    return Chain.from_records(records)


def _canonical_to_json(canonical_dict: dict[str, Any]) -> str:
    """Serialize a canonical dict back to a JSON string (JCS-equivalent)."""
    # rfc8785.dumps yields bytes; decode to str for SQLite storage.
    return canonical_bytes(canonical_dict).decode("utf-8")
