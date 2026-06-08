"""Tests for the remaining six governance modules.

ConstraintGate, PersonaGuard, CitationVerifier, VerificationGate (gates) and
ConductRecord, MetricRecord (record helpers). Every failure path must still write
a valid AAT record on a chain that verifies intact.
"""

from __future__ import annotations

import pytest

from headlights_chain.enums import ActionType, Outcome
from headlights_sdk import Client
from headlights_sdk.guards import (
    AuthorityGate,
    CitationVerifier,
    ConductRecord,
    ConstraintGate,
    EgressGate,
    GuardDenied,
    MetricRecord,
    PersonaGuard,
    VerificationGate,
)


def _client(**kwargs) -> Client:
    return Client(agent_id="urn:headlights:agent:test", agent_version="1.0.0", **kwargs)


def test_all_eight_modules_importable() -> None:
    # Two record helpers + six gates.
    assert ConductRecord.name == "ConductRecord"
    assert MetricRecord.name == "MetricRecord"
    for gate in (
        AuthorityGate,
        ConstraintGate,
        PersonaGuard,
        CitationVerifier,
        VerificationGate,
        EgressGate,
    ):
        assert gate.action_type == ActionType.DECISION


# ── ConstraintGate ───────────────────────────────────────────────────────


def test_constraint_gate_denies_disallowed_action() -> None:
    client = _client()
    gate = ConstraintGate(client, disallowed_actions={"delete_database"})

    result = gate.check(action="delete_database", parameters={"table": "users"})

    assert result.allowed is False
    rec = client.chain.records()[-1]
    assert rec.action_type == ActionType.DECISION
    assert rec.outcome == Outcome.DENIED
    assert rec.action_detail["compliant"] is False
    assert rec.action_detail["parameters_hash"].startswith("sha256:")
    assert client.chain.verify().is_intact


def test_constraint_gate_policy_callable() -> None:
    client = _client()
    gate = ConstraintGate(client, policy=lambda action, params: params.get("amount", 0) <= 100)

    assert gate.check(action="transfer", parameters={"amount": 500}).allowed is False
    assert gate.check(action="transfer", parameters={"amount": 50}).allowed is True


def test_constraint_gate_enforce_raises() -> None:
    client = _client()
    gate = ConstraintGate(client, disallowed_actions={"wire_funds"})
    with pytest.raises(GuardDenied, match="ConstraintGate"):
        gate.enforce(action="wire_funds")


# ── PersonaGuard ─────────────────────────────────────────────────────────


def test_persona_guard_detects_drift_without_storing_reply() -> None:
    client = _client()
    guard = PersonaGuard(client, drift_patterns={"claims_human": r"I am a human"})

    secret_reply = "Trust me, I am a human and my password is hunterTwo"
    result = guard.check(reply=secret_reply, identity="support-bot")

    assert result.allowed is False
    assert "claims_human" in result.detail["drift_signals"]
    rec = client.chain.records()[-1]
    assert rec.outcome == Outcome.DENIED
    assert rec.action_detail["reply_hash"].startswith("sha256:")
    assert "hunterTwo" not in str(rec.action_detail)  # raw reply never stored
    assert client.chain.verify().is_intact


def test_persona_guard_allows_on_persona_reply() -> None:
    client = _client()
    guard = PersonaGuard(client, drift_patterns={"claims_human": r"I am a human"})
    result = guard.check(reply="I'm the support assistant, happy to help.")
    assert result.allowed is True
    assert client.chain.records()[-1].outcome == Outcome.SUCCESS


# ── CitationVerifier ─────────────────────────────────────────────────────


def test_citation_verifier_denies_fake_citation() -> None:
    client = _client()
    verifier = CitationVerifier(client, known_valid={"1", "2"})

    result = verifier.check(content="As held in [1] and [2], but also [99].")

    assert result.allowed is False
    assert result.detail["unverified_citations"] == ["99"]
    rec = client.chain.records()[-1]
    assert rec.outcome == Outcome.DENIED
    assert rec.action_detail["citations_checked"] == 3
    assert client.chain.verify().is_intact


def test_citation_verifier_allows_all_real() -> None:
    client = _client()
    verifier = CitationVerifier(client, verifier=lambda c: c.startswith("AC-"))
    assert verifier.check(content="See [AC-100] and [AC-200].").allowed is True


def test_citation_verifier_enforce_raises() -> None:
    client = _client()
    verifier = CitationVerifier(client, known_valid=set())
    with pytest.raises(GuardDenied, match="CitationVerifier"):
        verifier.enforce(content="A claim with citation [42].")


# ── VerificationGate ─────────────────────────────────────────────────────


def test_verification_gate_denies_unverified_claim() -> None:
    client = _client()
    truth = {"the earth is round"}
    gate = VerificationGate(client, source=lambda claim: claim in truth)

    result = gate.check(claim="the earth is flat")

    assert result.allowed is False
    rec = client.chain.records()[-1]
    assert rec.outcome == Outcome.DENIED
    assert rec.action_detail["verified"] is False
    assert rec.action_detail["claim_hash"].startswith("sha256:")
    assert "flat" not in str(rec.action_detail)  # raw claim never stored
    assert client.chain.verify().is_intact


def test_verification_gate_allows_verified_claim() -> None:
    client = _client()
    gate = VerificationGate(client, source=lambda claim: True)
    assert gate.check(claim="anything").allowed is True


def test_verification_gate_requires_callable_source() -> None:
    client = _client()
    with pytest.raises(TypeError):
        VerificationGate(client, source="not callable")


# ── ConductRecord ────────────────────────────────────────────────────────


def test_conduct_record_writes_hashed_record() -> None:
    client = _client()
    conduct = ConductRecord(client)

    pos, _ = conduct.write(
        model_id="gpt-x-2026",
        system_prompt="secret system prompt",
        retrieved=["doc-a", "doc-b"],
        tool_calls=["lookup_credit_score"],
        output="secret output",
    )

    rec = client.chain.records()[-1]
    assert rec.action_detail["record"] == "conduct"
    assert rec.action_detail["model_id"] == "gpt-x-2026"
    assert rec.action_detail["retrieved_count"] == 2
    assert rec.action_detail["system_prompt_hash"].startswith("sha256:")
    assert rec.action_detail["output_hash"].startswith("sha256:")
    # raw prompt/output never stored
    assert "secret system prompt" not in str(rec.action_detail)
    assert "secret output" not in str(rec.action_detail)
    assert client.chain.verify().is_intact


# ── MetricRecord ─────────────────────────────────────────────────────────


def test_metric_record_binds_to_chain_root() -> None:
    client = _client()
    # Lay down a conduct record first so the chain has prior events to bind to.
    ConductRecord(client).write(model_id="gpt-x", output="approved")

    metric = MetricRecord(client)
    metric.write("approval_rate", 0.42, sample_size=100)

    rec = client.chain.records()[-1]
    assert rec.action_detail["record"] == "metric"
    assert rec.action_detail["metric"] == "approval_rate"
    assert rec.action_detail["value"] == 0.42
    assert rec.action_detail["sample_size"] == 100
    # bound to the chain it was computed over
    assert "chain_root" in rec.action_detail
    assert client.chain.verify().is_intact
