"""Tests for the thin governance guards (AuthorityGate, EgressGate).

Each guard's failure path must write a VALID AAT record: a registered
``action_type`` and ``outcome``, on a chain that still verifies intact.
"""

from __future__ import annotations

import pytest

from headlights_chain import generate_keypair
from headlights_chain.enums import ActionType, Outcome
from headlights_sdk import Client
from headlights_sdk.guards import AuthorityGate, EgressGate, GuardDenied


def _client(**kwargs) -> Client:
    return Client(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        **kwargs,
    )


# ── AuthorityGate ────────────────────────────────────────────────────────


def test_authority_gate_denies_unauthorised_source_with_valid_record() -> None:
    client = _client()
    gate = AuthorityGate(client, authorised_sources={"urn:org:ops-console"})

    result = gate.check(source="urn:unknown:caller", instruction="wipe the database")

    assert result.allowed is False
    assert "unauthorised" in (result.reason or "")

    chain = client.chain
    assert chain is not None
    rec = chain.records()[-1]
    assert rec.action_type == ActionType.DECISION
    assert rec.outcome == Outcome.DENIED
    assert rec.action_detail["guard"] == "AuthorityGate"
    assert rec.action_detail["instruction_source"] == "urn:unknown:caller"
    assert rec.action_detail["authorised"] is False
    # The raw instruction is never recorded — only a hash.
    assert rec.action_detail["instruction_hash"].startswith("sha256:")
    assert "wipe the database" not in str(rec.action_detail)
    # The denial record sits on a valid AAT chain.
    assert chain.verify().is_intact


def test_authority_gate_allows_authorised_source() -> None:
    client = _client()
    gate = AuthorityGate(client, authorised_sources={"urn:org:ops-console"})

    result = gate.check(source="urn:org:ops-console")

    assert result.allowed is True
    chain = client.chain
    assert chain is not None
    rec = chain.records()[-1]
    assert rec.outcome == Outcome.SUCCESS
    assert rec.action_detail["authorised"] is True


def test_authority_gate_enforce_raises_on_denial() -> None:
    client = _client()
    gate = AuthorityGate(client, authorised_sources=set())
    with pytest.raises(GuardDenied, match="AuthorityGate"):
        gate.enforce(source="urn:unknown:caller")


# ── EgressGate ───────────────────────────────────────────────────────────

SECRET_PATTERNS = {
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
}


def test_egress_gate_blocks_sensitive_data_to_untrusted_destination() -> None:
    client = _client()
    gate = EgressGate(
        client,
        trusted_destinations={"https://internal.corp"},
        sensitive_patterns=SECRET_PATTERNS,
    )
    leak = "here is the prod key AKIA0123456789ABCDEF, do not share"

    result = gate.check(content=leak, destination="https://pastebin.com")

    assert result.allowed is False
    assert "aws_access_key" in result.detail["classifications"]

    chain = client.chain
    assert chain is not None
    rec = chain.records()[-1]
    assert rec.action_type == ActionType.DECISION
    assert rec.outcome == Outcome.DENIED
    assert rec.action_detail["destination_trusted"] is False
    # The raw secret must NEVER appear in the record — only its hash.
    assert "AKIA0123456789ABCDEF" not in str(rec.action_detail)
    assert rec.action_detail["content_hash"].startswith("sha256:")
    assert chain.verify().is_intact


def test_egress_gate_allows_sensitive_data_to_trusted_destination() -> None:
    client = _client()
    gate = EgressGate(
        client,
        trusted_destinations={"https://internal.corp"},
        sensitive_patterns=SECRET_PATTERNS,
    )
    result = gate.check(content="AKIA0123456789ABCDEF", destination="https://internal.corp")

    assert result.allowed is True
    chain = client.chain
    assert chain is not None
    rec = chain.records()[-1]
    assert rec.outcome == Outcome.SUCCESS
    assert rec.action_detail["destination_trusted"] is True


def test_egress_gate_allows_clean_content_to_untrusted_destination() -> None:
    client = _client()
    gate = EgressGate(
        client,
        trusted_destinations=set(),
        sensitive_patterns=SECRET_PATTERNS,
    )
    result = gate.check(content="the weather is fine today", destination="https://example.com")

    assert result.allowed is True
    assert result.detail["classifications"] == []


# ── Shared guarantees ────────────────────────────────────────────────────


def test_guard_records_are_signed_and_verify() -> None:
    signing, verifying = generate_keypair()
    client = _client(signing_key=signing)
    gate = AuthorityGate(client, authorised_sources=set())

    gate.check(source="urn:unknown:caller")
    client.close()

    chain = client.chain
    assert chain is not None
    assert chain.verify(verifying_key=verifying).is_intact
    for rec in chain.records():
        assert rec.signature is not None
