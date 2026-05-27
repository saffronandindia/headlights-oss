"""End-to-end Chain tests — genesis, append, close, verify, tamper-detection."""

from __future__ import annotations

import time

import pytest

from headlights_chain.canonical import record_hash_for_chain
from headlights_chain.chain import Chain
from headlights_chain.enums import (
    ActionType,
    LifecycleEvent,
    Outcome,
    TrustLevel,
)
from headlights_chain.records import Record, utc_now_rfc3339
from headlights_chain.signatures import generate_keypair


# ── Genesis ─────────────────────────────────────────────────────────────


def test_genesis_creates_lifecycle_session_start() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    assert len(chain) == 1
    g = chain.records()[0]
    assert g.action_type == ActionType.LIFECYCLE
    assert g.action_detail["event"] == LifecycleEvent.SESSION_START.value
    assert g.parent_record_id is None
    assert g.prev_hash is None


def test_genesis_includes_caller_detail() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        genesis_detail={"config_hash": "sha256:abc", "enabled_tools": ["x"]},
    )
    g = chain.records()[0]
    assert g.action_detail["config_hash"] == "sha256:abc"
    assert g.action_detail["enabled_tools"] == ["x"]
    assert g.action_detail["event"] == LifecycleEvent.SESSION_START.value


def test_genesis_with_signing_key_attaches_signature() -> None:
    signing, _ = generate_keypair()
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        signing_key=signing,
    )
    assert chain.records()[0].signature is not None


# ── Append ──────────────────────────────────────────────────────────────


def test_append_three_records_links_correctly() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    for i in range(3):
        pos, h = chain.append(
            action_type=ActionType.TOOL_CALL,
            action_detail={"tool_name": f"tool_{i}", "parameters_hash": "sha256:x"},
            outcome=Outcome.SUCCESS,
            trust_level=TrustLevel.L2,
        )
        assert pos == i + 1
        assert len(h) == 64

    records = chain.records()
    assert len(records) == 4

    # Each record's prev_hash == hash of previous complete canonical record
    for i in range(1, len(records)):
        prev_canonical = records[i - 1].to_canonical_dict()
        assert records[i].prev_hash == record_hash_for_chain(prev_canonical)
        assert records[i].parent_record_id == records[i - 1].record_id


def test_append_propagates_agent_and_session_identity() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    chain.append(
        action_type="decision",
        action_detail={"decision_type": "approve"},
        outcome="success",
        trust_level="L1",
    )
    g, r1 = chain.records()
    assert r1.agent_id == g.agent_id
    assert r1.session_id == g.session_id
    assert r1.agent_version == g.agent_version


# ── Close ───────────────────────────────────────────────────────────────


def test_close_writes_session_end_with_session_hash() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    for _ in range(2):
        chain.append(
            action_type="tool_call",
            action_detail={"tool_name": "t", "parameters_hash": "h"},
            outcome="success",
            trust_level="L1",
        )

    pos, _ = chain.close()
    assert chain.is_closed
    last = chain.records()[-1]
    assert last.action_type == ActionType.LIFECYCLE
    assert last.action_detail["event"] == LifecycleEvent.SESSION_END.value
    assert "session_hash" in last.action_detail
    assert last.action_detail["record_count"] == len(chain)


def test_cannot_append_after_close() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    chain.close()
    with pytest.raises(RuntimeError, match="closed"):
        chain.append(
            action_type="error",
            action_detail={
                "error_code": "x",
                "error_message": "y",
                "error_category": "internal",
                "recoverable": False,
            },
            outcome="failure",
            trust_level="L1",
        )


def test_cannot_close_twice() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    chain.close()
    with pytest.raises(RuntimeError, match="already closed"):
        chain.close()


# ── Verify (happy path) ─────────────────────────────────────────────────


def test_verify_intact_chain() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    for i in range(5):
        chain.append(
            action_type="tool_call",
            action_detail={"tool_name": f"t{i}", "parameters_hash": "h"},
            outcome="success",
            trust_level="L1",
        )
    chain.close()

    result = chain.verify()
    assert result.is_intact
    assert result.failed_position is None
    assert result.reason is None


def test_verify_with_signatures() -> None:
    signing, verifying = generate_keypair()
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        signing_key=signing,
    )
    for _ in range(3):
        chain.append(
            action_type="decision",
            action_detail={"decision_type": "x"},
            outcome="success",
            trust_level="L2",
        )
    chain.close()

    assert chain.verify(verifying_key=verifying).is_intact


# ── Tamper detection ────────────────────────────────────────────────────


def test_tamper_detected_when_action_detail_modified() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    for i in range(3):
        chain.append(
            action_type="tool_call",
            action_detail={"tool_name": f"t{i}", "parameters_hash": "h"},
            outcome="success",
            trust_level="L1",
        )

    # Export, mutate position 2, re-import.
    exported = chain.export_records()
    exported[2]["action_detail"]["tool_name"] = "tampered"
    tampered_chain = Chain.from_records(exported)

    result = tampered_chain.verify()
    assert not result.is_intact
    # Position 3 (the record AFTER the tampered one) is the one whose
    # prev_hash will no longer match.
    assert result.failed_position == 3
    assert "prev_hash" in (result.reason or "")


def test_tamper_detected_when_signature_modified() -> None:
    signing, verifying = generate_keypair()
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        signing_key=signing,
    )
    chain.append(
        action_type="decision",
        action_detail={"decision_type": "x"},
        outcome="success",
        trust_level="L2",
    )

    exported = chain.export_records()
    # Replace position 1's signature with a syntactically valid but wrong one.
    other_signing, _ = generate_keypair()
    import hashlib

    other_sig = other_signing.sign_digest(hashlib.sha256(b"different").digest())
    exported[1]["signature"] = other_sig
    tampered_chain = Chain.from_records(exported)

    result = tampered_chain.verify(verifying_key=verifying)
    assert not result.is_intact
    # Either the chain hash for position 1 changes (so position 2 would fail)
    # or the signature for position 1 fails. We only have positions 0 and 1
    # so signature failure at position 1 is what we expect.
    assert result.failed_position == 1
    assert "signature" in (result.reason or "")


def test_tamper_detected_when_record_id_modified() -> None:
    import uuid

    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    for _ in range(2):
        chain.append(
            action_type="tool_call",
            action_detail={"tool_name": "t", "parameters_hash": "h"},
            outcome="success",
            trust_level="L1",
        )

    exported = chain.export_records()
    # Change record_id on position 1.
    exported[1]["record_id"] = str(uuid.uuid4())
    tampered = Chain.from_records(exported)

    result = tampered.verify()
    assert not result.is_intact
    # Position 2's parent_record_id no longer matches position 1's new id.
    assert result.failed_position == 2


def test_tamper_detected_when_session_hash_modified() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    chain.append(
        action_type="tool_call",
        action_detail={"tool_name": "t", "parameters_hash": "h"},
        outcome="success",
        trust_level="L1",
    )
    chain.close()

    exported = chain.export_records()
    last = exported[-1]
    last["action_detail"]["session_hash"] = "0" * 64
    # The close record's prev_hash and parent_record_id are unchanged, so
    # only the session_hash claim will mismatch. But changing action_detail
    # also changes the close record's canonical bytes — there is no record
    # after it, so the only failure is the session_hash mismatch.
    tampered = Chain.from_records(exported)
    result = tampered.verify()
    assert not result.is_intact
    assert result.failed_position == len(exported) - 1
    assert "session_hash" in (result.reason or "")


# ── Export / import ─────────────────────────────────────────────────────


def test_export_import_roundtrip_preserves_chain() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    for i in range(4):
        chain.append(
            action_type="decision",
            action_detail={"decision_type": f"d{i}"},
            outcome="success",
            trust_level="L2",
        )
    chain.close()

    exported = chain.export_records()
    rebuilt = Chain.from_records(exported)

    assert len(rebuilt) == len(chain)
    assert rebuilt.is_closed
    assert rebuilt.verify().is_intact


def test_export_is_canonical_dict_form() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    exported = chain.export_records()
    assert exported[0]["parent_record_id"] is None
    assert exported[0]["prev_hash"] is None
    # No unset optionals leaked into the canonical export
    assert "signature" not in exported[0]
    assert "risk_score" not in exported[0]


# ── Timestamp monotonicity ──────────────────────────────────────────────


def test_timestamp_regression_detected() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        timestamp="2026-05-18T08:00:00Z",
    )
    chain.append(
        action_type="tool_call",
        action_detail={"tool_name": "t", "parameters_hash": "h"},
        outcome="success",
        trust_level="L1",
        timestamp="2026-05-18T08:00:01Z",
    )

    exported = chain.export_records()
    exported[1]["timestamp"] = "2026-05-18T07:00:00Z"
    tampered = Chain.from_records(exported)

    result = tampered.verify()
    assert not result.is_intact
    assert result.failed_position == 1



def test_mixed_timezone_timestamps_compared_as_instants_not_strings() -> None:
    """Regression test: lexicographic string comparison was wrong for chains
    mixing 'Z' and offset timestamps.

    Two timestamps:
      genesis : 2026-05-18T12:00:00Z       (12:00 UTC)
      append  : 2026-05-18T11:00:00-02:00  (13:00 UTC, one hour later)

    Lexically 'T11:' is less than 'T12:', so the pre-fix verifier flagged
    this as a regression. The post-fix verifier parses both to UTC and
    accepts them as monotonic.
    """
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        timestamp="2026-05-18T12:00:00Z",
    )
    chain.append(
        action_type="tool_call",
        action_detail={"tool_name": "t", "parameters_hash": "h"},
        outcome="success",
        trust_level="L1",
        timestamp="2026-05-18T11:00:00-02:00",
    )
    result = chain.verify()
    assert result.is_intact, result.reason


def test_mixed_timezone_real_regression_still_detected() -> None:
    """The mirror test: an offset timestamp that is lexically later but
    absolutely earlier than the previous UTC-Z timestamp must still be
    detected as a regression.

    Two timestamps:
      genesis : 2026-05-18T12:00:00Z       (12:00 UTC)
      append  : 2026-05-18T13:00:00+02:00  (11:00 UTC, one hour earlier)
    """
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        timestamp="2026-05-18T12:00:00Z",
    )
    chain.append(
        action_type="tool_call",
        action_detail={"tool_name": "t", "parameters_hash": "h"},
        outcome="success",
        trust_level="L1",
        timestamp="2026-05-18T12:00:01Z",
    )
    exported = chain.export_records()
    exported[1]["timestamp"] = "2026-05-18T13:00:00+02:00"
    tampered = Chain.from_records(exported)
    result = tampered.verify()
    assert not result.is_intact
    assert result.failed_position == 1


# ── State / __len__ / iteration ─────────────────────────────────────────

def test_state_reports_position_and_closed() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    s = chain.state
    assert s.length == 1
    assert not s.closed
    assert len(s.last_hash) == 64

    chain.append(
        action_type="error",
        action_detail={
            "error_code": "E",
            "error_message": "boom",
            "error_category": "internal",
            "recoverable": True,
        },
        outcome="failure",
        trust_level="L1",
    )
    chain.close()
    s2 = chain.state
    assert s2.closed
    assert s2.length == 3


def test_iteration_yields_records_in_order() -> None:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    chain.append(
        action_type="decision",
        action_detail={"decision_type": "a"},
        outcome="success",
        trust_level="L1",
    )
    items = list(chain)
    assert len(items) == 2
    assert all(isinstance(r, Record) for r in items)

