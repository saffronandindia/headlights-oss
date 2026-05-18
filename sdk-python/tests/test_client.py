"""Tests for the SDK Client and @record decorator."""

from __future__ import annotations

import pytest

from headlights_chain import Chain, TrustLevel, generate_keypair
from headlights_chain.enums import ActionType, Outcome
from headlights_sdk import Client, NoActiveSessionError


# ── Decorator basics ────────────────────────────────────────────────────


def test_decorator_records_a_successful_call() -> None:
    client = Client(agent_id="urn:headlights:agent:t", agent_version="1.0.0")

    @client.record
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5

    chain = client.chain
    assert chain is not None
    # genesis + tool_call + tool_response
    assert len(chain) == 3
    records = chain.records()
    assert records[1].action_type == ActionType.TOOL_CALL
    assert records[1].action_detail["tool_name"] == "add"
    assert records[2].action_type == ActionType.TOOL_RESPONSE
    assert records[2].action_detail["parent_call_id"] == records[1].record_id


def test_decorator_records_error_and_reraises() -> None:
    client = Client(agent_id="urn:headlights:agent:t", agent_version="1.0.0")

    @client.record
    def explode() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        explode()

    chain = client.chain
    assert chain is not None
    # genesis + tool_call + error
    assert len(chain) == 3
    err = chain.records()[2]
    assert err.action_type == ActionType.ERROR
    assert err.outcome == Outcome.FAILURE
    assert err.action_detail["error_code"] == "RuntimeError"
    assert err.action_detail["error_message"] == "boom"
    assert err.action_detail["recoverable"] is False


def test_decorator_with_arguments_works() -> None:
    client = Client(agent_id="urn:headlights:agent:t", agent_version="1.0.0")

    @client.record(action_type="decision", trust_level="L2", tool_name="evaluator")
    def evaluate(x: int) -> bool:
        return x > 0

    evaluate(7)

    chain = client.chain
    assert chain is not None
    call = chain.records()[1]
    assert call.action_type == ActionType.TOOL_CALL  # outer wrapper still emits tool_call
    assert call.action_detail["tool_name"] == "evaluator"
    assert call.trust_level == TrustLevel.L2


def test_multiple_calls_chain_correctly() -> None:
    client = Client(agent_id="urn:headlights:agent:t", agent_version="1.0.0")

    @client.record
    def f(x: int) -> int:
        return x * 2

    for i in range(3):
        f(i)

    chain = client.chain
    assert chain is not None
    # genesis + 3 * (tool_call + tool_response)
    assert len(chain) == 7
    assert chain.verify().is_intact


def test_input_hash_differs_per_arguments() -> None:
    client = Client(agent_id="urn:headlights:agent:t", agent_version="1.0.0")

    @client.record
    def f(x: int) -> int:
        return x

    f(1)
    f(2)
    chain = client.chain
    assert chain is not None
    call_1 = chain.records()[1].action_detail["parameters_hash"]
    call_2 = chain.records()[3].action_detail["parameters_hash"]
    assert call_1 != call_2


# ── Sessions ────────────────────────────────────────────────────────────


def test_auto_session_opens_on_first_call() -> None:
    client = Client(agent_id="urn:headlights:agent:t", agent_version="1.0.0")
    assert not client.is_session_active

    @client.record
    def f() -> int:
        return 1

    f()
    assert client.is_session_active


def test_auto_session_false_requires_explicit_session() -> None:
    client = Client(
        agent_id="urn:headlights:agent:t",
        agent_version="1.0.0",
        auto_session=False,
    )

    @client.record
    def f() -> int:
        return 1

    with pytest.raises(NoActiveSessionError):
        f()


def test_session_context_manager_opens_and_closes() -> None:
    client = Client(
        agent_id="urn:headlights:agent:t",
        agent_version="1.0.0",
        auto_session=False,
    )

    @client.record
    def f() -> int:
        return 1

    with client.session(genesis_detail={"config_hash": "sha256:abc"}):
        f()
        assert client.is_session_active

    assert not client.is_session_active
    assert client.chain is not None
    assert client.chain.is_closed
    # genesis includes the caller's detail
    assert client.chain.records()[0].action_detail.get("config_hash") == "sha256:abc"


def test_session_cm_rejects_double_open() -> None:
    client = Client(
        agent_id="urn:headlights:agent:t",
        agent_version="1.0.0",
        auto_session=False,
    )

    with client.session():
        with pytest.raises(RuntimeError, match="already active"):
            with client.session():
                pass


def test_close_is_idempotent() -> None:
    client = Client(agent_id="urn:headlights:agent:t", agent_version="1.0.0")
    client.close()  # no session yet — no-op
    client.close()  # still no-op


# ── Signing ─────────────────────────────────────────────────────────────


def test_records_are_signed_when_signing_key_set() -> None:
    signing, verifying = generate_keypair()
    client = Client(
        agent_id="urn:headlights:agent:t",
        agent_version="1.0.0",
        signing_key=signing,
    )

    @client.record
    def f() -> int:
        return 42

    f()
    f()
    client.close()

    chain = client.chain
    assert chain is not None
    for record in chain.records():
        assert record.signature is not None
    assert chain.verify(verifying_key=verifying).is_intact


# ── Export ──────────────────────────────────────────────────────────────


def test_export_round_trips_through_chain() -> None:
    signing, verifying = generate_keypair()
    client = Client(
        agent_id="urn:headlights:agent:t",
        agent_version="1.0.0",
        signing_key=signing,
    )

    @client.record
    def add(a: int, b: int) -> int:
        return a + b

    add(2, 3)
    add(4, 5)
    client.close()

    exported = client.export()
    rebuilt = Chain.from_records(exported)
    assert rebuilt.verify(verifying_key=verifying).is_intact


def test_export_before_first_call_raises() -> None:
    client = Client(agent_id="urn:headlights:agent:t", agent_version="1.0.0")
    with pytest.raises(RuntimeError, match="no chain"):
        client.export()
