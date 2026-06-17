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


# ── additional coverage added after SHOULD-FIX audit ────────────────────────


def test_verification_gate_failure_record_no_raw_claim():
    """When source() raises, the FAILURE record must hash the claim, not store it."""
    client = _client()
    secret_claim = "supersecret-value-12345"

    def bad_source(claim):
        raise ConnectionError("db timeout")

    gate = VerificationGate(client, source=bad_source)
    with pytest.raises(ConnectionError):
        gate.check(claim=secret_claim)

    rec = client.chain.records()[-1]
    assert rec.outcome == Outcome.FAILURE
    # Raw claim must not appear anywhere in the record detail.
    assert secret_claim not in str(rec.action_detail)
    # claim_hash must be present and be a sha256 digest.
    assert rec.action_detail["claim_hash"].startswith("sha256:")
    assert rec.action_detail["error_code"] == "ConnectionError"


def test_constraint_gate_failure_record_no_raw_params():
    """When policy() raises, the FAILURE record must not store raw parameters."""
    client = _client()
    sensitive_params = {"api_key": "sk-DEADBEEF"}

    def bad_policy(action, params):
        raise RuntimeError("policy engine unavailable")

    gate = ConstraintGate(client, policy=bad_policy)
    with pytest.raises(RuntimeError):
        gate.check(action="send_email", parameters=sensitive_params)

    rec = client.chain.records()[-1]
    assert rec.outcome == Outcome.FAILURE
    assert "sk-DEADBEEF" not in str(rec.action_detail)
    assert rec.action_detail["error_code"] == "RuntimeError"
    # action name is stored (it's not sensitive), error_code is stored.
    assert rec.action_detail["action"] == "send_email"


def test_citation_verifier_callable_verifier_does_not_raise():
    """Supplying only a verifier callable must be sufficient — no ValueError."""
    verifier = CitationVerifier(_client(), verifier=lambda c: c.startswith("DOI:"))
    result = verifier.check(content="See [DOI:10.1000/xyz123] for details.")
    assert result.allowed is True


def test_metric_record_requires_active_session_auto_session():
    """auto_session=True (the default) still raises: an unbound metric is useless."""
    # auto_session is True by default; chain is None until the first record_action call.
    # MetricRecord snapshots chain BEFORE record_action, so it must still raise.
    client = _client(auto_session=True)
    with pytest.raises(RuntimeError, match="active session"):
        MetricRecord(client).write("precision", 0.92)


def test_verification_gate_failure_record_chain_verifies():
    """The FAILURE record written on source() exception must not break chain integrity."""
    from headlights_chain.signatures import generate_keypair

    signing, verifying = generate_keypair()
    client = _client(signing_key=signing)

    def bad_source(claim):
        raise ValueError("oops")

    gate = VerificationGate(client, source=bad_source)
    with pytest.raises(ValueError):
        gate.check(claim="some-claim")

    client.close()
    result = client.chain.verify(verifying_key=verifying)
    assert result.is_intact is True
    assert result.signatures_checked is True
