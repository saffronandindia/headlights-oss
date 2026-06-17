"""Tests for the post-review crypto-core fixes."""
from headlights_chain.chain import Chain
from headlights_chain.enums import ActionType, LifecycleEvent, Outcome, TrustLevel
from headlights_chain.signatures import generate_keypair


def _chain(signing=None):
    return Chain.genesis(agent_id="urn:test", agent_version="1.0.0", signing_key=signing)


def test_verify_exposes_is_closed_and_signatures_checked():
    signing, verifying = generate_keypair()
    c = _chain(signing)
    c.append(action_type=ActionType.DECISION, action_detail={"x": 1}, outcome=Outcome.SUCCESS, trust_level=TrustLevel.L1)
    r_open = c.verify(verifying_key=verifying)
    assert r_open.is_intact and r_open.signatures_checked and not r_open.is_closed
    c.close()
    r_closed = c.verify(verifying_key=verifying)
    assert r_closed.is_intact and r_closed.is_closed and r_closed.signatures_checked


def test_signatures_not_checked_without_key():
    signing, _ = generate_keypair()
    c = _chain(signing)
    r = c.verify()  # no verifying key passed
    assert r.is_intact and r.signatures_checked is False


def test_tombstone_appends_marker_and_chain_verifies():
    signing, verifying = generate_keypair()
    c = _chain(signing)
    pos, _h = c.append(action_type=ActionType.DECISION, action_detail={"x": 1}, outcome=Outcome.SUCCESS, trust_level=TrustLevel.L1)
    target = c.records()[pos].record_id
    c.tombstone(target_record_id=target, reason="user erasure request")
    last = c.records()[-1]
    assert last.action_type == ActionType.LIFECYCLE
    assert last.action_detail["event"] == LifecycleEvent.RECORD_DELETED.value
    assert last.action_detail["target_record_id"] == target
    assert c.verify(verifying_key=verifying).is_intact


def test_verify_digest_none_returns_false():
    _, verifying = generate_keypair()
    assert verifying.verify_digest(None, b"\x00" * 32) is False


# ── deferred should-fixes (this batch) ──────────────────────────────────────


def test_invalid_calendar_timestamp_rejected():
    import uuid

    import pytest
    from pydantic import ValidationError

    from headlights_chain.records import Record

    # Matches the RFC 3339 *shape* but month 13 / second 99 are not real.
    with pytest.raises(ValidationError):
        Record.new(
            agent_id="urn:test:agent",
            agent_version="1.0.0",
            session_id=str(uuid.uuid4()),
            action_type=ActionType.DECISION,
            action_detail={"x": 1},
            outcome=Outcome.SUCCESS,
            trust_level=TrustLevel.L1,
            parent_record_id=None,
            prev_hash=None,
            timestamp="2026-13-45T25:99:99.000Z",
        )


def test_genesis_unsigned_with_signed_followers_fails():
    signing, verifying = generate_keypair()
    c = _chain(signing)
    c.append(action_type=ActionType.DECISION, action_detail={"x": 1}, outcome=Outcome.SUCCESS, trust_level=TrustLevel.L1)
    exported = c.export_records()
    exported[0].pop("signature", None)  # strip the genesis signature
    c2 = Chain.from_records(exported)
    r = c2.verify(verifying_key=verifying)
    assert r.is_intact is False
    assert "genesis" in (r.reason or "").lower()


def test_canonical_is_deterministic_and_normalised():
    from headlights_chain.canonical import canonical_bytes

    # JCS sorts keys and emits no whitespace.
    assert canonical_bytes({"b": 1, "a": 2}) == canonical_bytes({"a": 2, "b": 1})
    assert canonical_bytes({"a": 2, "b": 1}) == b'{"a":2,"b":1}'
    # JCS normalises 1.0 to 1 (ECMAScript number formatting).
    assert canonical_bytes({"x": 1.0}) == canonical_bytes({"x": 1})
    assert canonical_bytes({"x": 1.0}) == b'{"x":1}'


def test_leap_second_and_nanosecond_timestamps_accepted():
    import uuid

    from headlights_chain.records import Record

    for ts in ("2026-06-30T23:59:60Z", "2026-06-13T12:00:00.123456789Z"):
        r = Record.new(
            agent_id="urn:test:agent",
            agent_version="1.0.0",
            session_id=str(uuid.uuid4()),
            action_type=ActionType.DECISION,
            action_detail={"x": 1},
            outcome=Outcome.SUCCESS,
            trust_level=TrustLevel.L1,
            parent_record_id=None,
            prev_hash=None,
            timestamp=ts,
        )
        assert r.timestamp == ts
