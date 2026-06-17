"""Tests for the post-review SDK/guard fixes."""
import datetime as _dt

import pytest

from headlights_chain.enums import ActionType, Outcome
from headlights_sdk import Client
from headlights_sdk.hashing import hash_value
from headlights_sdk.guards import (
    CitationVerifier,
    ConductRecord,
    ConstraintGate,
    EgressGate,
    MetricRecord,
    VerificationGate,
)


def _client(**k):
    return Client(agent_id="urn:test", agent_version="1.0.0", **k)


def test_error_record_hashes_message_no_raw():
    client = _client()

    @client.record
    def boom():
        raise ValueError("secret key AKIA-DEADBEEF embedded in url")

    with pytest.raises(ValueError):
        boom()
    rec = client.chain.records()[-1]
    assert rec.action_type == ActionType.ERROR
    assert "AKIA-DEADBEEF" not in str(rec.action_detail)
    assert rec.action_detail["error_message_hash"].startswith("sha256:")
    assert rec.action_detail["error_code"] == "ValueError"


def test_verification_gate_records_failure_on_source_error():
    client = _client()

    def bad_source(claim):
        raise RuntimeError("db down")

    gate = VerificationGate(client, source=bad_source)
    with pytest.raises(RuntimeError):
        gate.check(claim="x")
    rec = client.chain.records()[-1]
    assert rec.outcome == Outcome.FAILURE
    assert rec.action_detail["error_code"] == "RuntimeError"


def test_constraint_gate_records_failure_on_policy_error():
    client = _client()

    def bad_policy(action, params):
        raise RuntimeError("policy engine down")

    gate = ConstraintGate(client, policy=bad_policy)
    with pytest.raises(RuntimeError):
        gate.check(action="do_thing")
    rec = client.chain.records()[-1]
    assert rec.outcome == Outcome.FAILURE
    assert rec.action_detail["error_code"] == "RuntimeError"


# ── deferred should-fixes (this batch) ──────────────────────────────────────


def test_citation_verifier_requires_config():
    # Unconfigured (no known_valid, no verifier) would deny everything: fail fast.
    with pytest.raises(ValueError):
        CitationVerifier(_client())
    with pytest.raises(ValueError):
        CitationVerifier(_client(), known_valid=set())


def test_conduct_record_rejects_lifecycle():
    # A conduct record must not be able to close the chain.
    with pytest.raises(ValueError):
        ConductRecord(_client()).write(action_type=ActionType.LIFECYCLE, output="x")


def test_egress_flags_sensitive_to_trusted():
    client = _client()
    gate = EgressGate(
        client,
        trusted_destinations={"internal-store"},
        sensitive_patterns={"email": r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}"},
    )
    res = gate.check(content="contact me at a@b.com", destination="internal-store")
    assert res.allowed is True
    assert res.detail["sensitive_to_trusted"] is True
    # No false flag when the trusted destination carries nothing sensitive.
    res2 = gate.check(content="hello world", destination="internal-store")
    assert "sensitive_to_trusted" not in res2.detail


def test_metric_record_requires_active_session():
    # First call, no prior events: chain is None, so binding to a root is impossible.
    with pytest.raises(RuntimeError):
        MetricRecord(_client()).write("approval_rate", 0.5)


def test_hashing_type_prefix_avoids_cross_type_collision():
    # A datetime and the string equal to its repr must not collide.
    dt = _dt.datetime(2024, 1, 1)
    assert hash_value(dt) != hash_value(repr(dt))
