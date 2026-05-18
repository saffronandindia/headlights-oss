"""Tests for the headlights-verify CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from headlights_chain import (
    Chain,
    Outcome,
    TrustLevel,
    generate_keypair,
)
from headlights_verify.cli import main
from headlights_verify.verify import (
    VerifyError,
    load_records_from_string,
    verify_file,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def intact_chain_path(tmp_path: Path) -> Path:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    for i in range(3):
        chain.append(
            action_type="tool_call",
            action_detail={"tool_name": f"t{i}", "parameters_hash": "h"},
            outcome=Outcome.SUCCESS,
            trust_level=TrustLevel.L1,
        )
    chain.close()
    p = tmp_path / "intact.json"
    p.write_text(json.dumps(chain.export_records()))
    return p


@pytest.fixture
def tampered_chain_path(tmp_path: Path) -> Path:
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test", agent_version="1.0.0"
    )
    for i in range(3):
        chain.append(
            action_type="tool_call",
            action_detail={"tool_name": f"t{i}", "parameters_hash": "h"},
            outcome=Outcome.SUCCESS,
            trust_level=TrustLevel.L1,
        )
    exported = chain.export_records()
    exported[2]["action_detail"]["tool_name"] = "tampered"
    p = tmp_path / "tampered.json"
    p.write_text(json.dumps(exported))
    return p


@pytest.fixture
def signed_chain(tmp_path: Path):
    signing, verifying = generate_keypair()
    chain = Chain.genesis(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        signing_key=signing,
    )
    chain.append(
        action_type="decision",
        action_detail={"decision_type": "approve"},
        outcome="success",
        trust_level="L2",
    )
    chain.close()

    chain_path = tmp_path / "signed.json"
    chain_path.write_text(json.dumps(chain.export_records()))
    key_path = tmp_path / "verify.pem"
    key_path.write_bytes(verifying.to_pem())
    return chain_path, key_path


# ── load_records_from_string ────────────────────────────────────────────


def test_load_records_accepts_json_array() -> None:
    records = [{"a": 1}, {"a": 2}]
    parsed = load_records_from_string(json.dumps(records))
    assert parsed == records


def test_load_records_accepts_ndjson() -> None:
    text = '{"a": 1}\n{"a": 2}\n'
    parsed = load_records_from_string(text)
    assert parsed == [{"a": 1}, {"a": 2}]


def test_load_records_rejects_empty() -> None:
    with pytest.raises(VerifyError, match="empty"):
        load_records_from_string("")
    with pytest.raises(VerifyError, match="empty"):
        load_records_from_string("   \n  ")


def test_load_records_rejects_invalid_json() -> None:
    with pytest.raises(VerifyError, match="invalid JSON"):
        load_records_from_string("[{not json}]")


def test_load_records_rejects_non_object_lines_in_ndjson() -> None:
    with pytest.raises(VerifyError, match="not a JSON object"):
        load_records_from_string('"just a string"\n')


# ── verify_file ─────────────────────────────────────────────────────────


def test_verify_file_intact(intact_chain_path: Path) -> None:
    outcome = verify_file(intact_chain_path)
    assert outcome.result.is_intact
    assert outcome.record_count == 5  # genesis + 3 + close


def test_verify_file_tampered(tampered_chain_path: Path) -> None:
    outcome = verify_file(tampered_chain_path)
    assert not outcome.result.is_intact
    assert outcome.result.failed_position == 3


def test_verify_file_missing(tmp_path: Path) -> None:
    with pytest.raises(VerifyError, match="not found"):
        verify_file(tmp_path / "does-not-exist.json")


def test_verify_file_with_public_key(signed_chain) -> None:
    chain_path, key_path = signed_chain
    outcome = verify_file(chain_path, public_key_pem=key_path.read_bytes())
    assert outcome.result.is_intact


def test_verify_file_with_wrong_public_key(signed_chain, tmp_path: Path) -> None:
    chain_path, _ = signed_chain
    _, wrong_verifying = generate_keypair()
    wrong_key = tmp_path / "wrong.pem"
    wrong_key.write_bytes(wrong_verifying.to_pem())
    outcome = verify_file(chain_path, public_key_pem=wrong_key.read_bytes())
    assert not outcome.result.is_intact
    assert "signature" in (outcome.result.reason or "")


# ── CLI entry point ─────────────────────────────────────────────────────


def test_cli_intact_returns_zero(intact_chain_path: Path) -> None:
    buf = io.StringIO()
    exit_code = main([str(intact_chain_path), "--no-color"], stdout=buf)
    assert exit_code == 0
    output = buf.getvalue()
    assert "intact" in output


def test_cli_tampered_returns_one(tampered_chain_path: Path) -> None:
    buf = io.StringIO()
    exit_code = main([str(tampered_chain_path), "--no-color"], stdout=buf)
    assert exit_code == 1
    output = buf.getvalue()
    assert "BROKEN" in output
    assert "position: 3" in output


def test_cli_missing_file_returns_two(tmp_path: Path) -> None:
    buf = io.StringIO()
    exit_code = main([str(tmp_path / "missing.json"), "--no-color"], stdout=buf)
    assert exit_code == 2


def test_cli_quiet_suppresses_output(intact_chain_path: Path) -> None:
    buf = io.StringIO()
    exit_code = main([str(intact_chain_path), "--quiet", "--no-color"], stdout=buf)
    assert exit_code == 0
    assert buf.getvalue() == ""


def test_cli_quiet_tampered_returns_one(tampered_chain_path: Path) -> None:
    buf = io.StringIO()
    exit_code = main([str(tampered_chain_path), "--quiet", "--no-color"], stdout=buf)
    assert exit_code == 1


def test_cli_with_public_key(signed_chain) -> None:
    chain_path, key_path = signed_chain
    buf = io.StringIO()
    exit_code = main(
        [str(chain_path), "--public-key", str(key_path), "--no-color"], stdout=buf
    )
    assert exit_code == 0


def test_cli_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_cli_version() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
