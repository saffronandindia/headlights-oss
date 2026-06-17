"""Tests for the post-review verifier fixes: guarantee transparency + robustness."""

from __future__ import annotations

import io
import json

import pytest

from headlights_chain import Chain, Outcome, TrustLevel, generate_keypair
from headlights_verify.cli import main
from headlights_verify.verify import VerifyError, load_records_from_string


def _write(tmp_path, name, records):
    p = tmp_path / name
    p.write_text(json.dumps(records))
    return p


def _unsigned_closed(tmp_path):
    c = Chain.genesis(agent_id="urn:test:agent", agent_version="1.0.0")
    c.append(action_type="decision", action_detail={"d": "x"}, outcome=Outcome.SUCCESS, trust_level=TrustLevel.L1)
    c.close()
    return _write(tmp_path, "unsigned_closed.json", c.export_records())


def _unsigned_open(tmp_path):
    c = Chain.genesis(agent_id="urn:test:agent", agent_version="1.0.0")
    c.append(action_type="decision", action_detail={"d": "x"}, outcome=Outcome.SUCCESS, trust_level=TrustLevel.L1)
    return _write(tmp_path, "unsigned_open.json", c.export_records())


def _signed_open(tmp_path):
    signing, verifying = generate_keypair()
    c = Chain.genesis(agent_id="urn:test:agent", agent_version="1.0.0", signing_key=signing)
    c.append(action_type="decision", action_detail={"d": "x"}, outcome=Outcome.SUCCESS, trust_level=TrustLevel.L1)
    key_path = tmp_path / "k.pem"
    key_path.write_bytes(verifying.to_pem())
    return _write(tmp_path, "signed_open.json", c.export_records()), key_path


def _signed_closed(tmp_path):
    signing, verifying = generate_keypair()
    c = Chain.genesis(agent_id="urn:test:agent", agent_version="1.0.0", signing_key=signing)
    c.append(action_type="decision", action_detail={"d": "x"}, outcome=Outcome.SUCCESS, trust_level=TrustLevel.L1)
    c.close()
    key_path = tmp_path / "k.pem"
    key_path.write_bytes(verifying.to_pem())
    return _write(tmp_path, "signed_closed.json", c.export_records()), key_path


# ── #1 / #2: weak guarantees are surfaced, not hidden ────────────────────


def test_unsigned_chain_shows_weak_and_signature_warning(tmp_path):
    buf = io.StringIO()
    code = main([str(_unsigned_closed(tmp_path)), "--no-color"], stdout=buf)
    out = buf.getvalue()
    assert code == 0
    assert "WEAK" in out
    assert "signatures NOT verified" in out
    assert "✓" not in out  # no full-confidence tick on an unsigned chain


def test_open_chain_shows_truncation_warning(tmp_path):
    buf = io.StringIO()
    code = main([str(_unsigned_open(tmp_path)), "--no-color"], stdout=buf)
    out = buf.getvalue()
    assert code == 0
    assert "OPEN" in out


def test_signed_closed_chain_shows_full_tick(tmp_path):
    chain_path, key_path = _signed_closed(tmp_path)
    buf = io.StringIO()
    code = main([str(chain_path), "--public-key", str(key_path), "--no-color"], stdout=buf)
    out = buf.getvalue()
    assert code == 0
    assert "✓" in out
    assert "WEAK" not in out


# ── #3: --strict gates CI on the full guarantee ──────────────────────────


def test_strict_fails_unsigned_chain(tmp_path):
    code = main([str(_unsigned_closed(tmp_path)), "--strict", "--quiet"], stdout=io.StringIO())
    assert code == 1


def test_strict_fails_open_signed_chain(tmp_path):
    chain_path, key_path = _signed_open(tmp_path)
    code = main([str(chain_path), "--public-key", str(key_path), "--strict", "--quiet"], stdout=io.StringIO())
    assert code == 1


def test_strict_passes_signed_closed_chain(tmp_path):
    chain_path, key_path = _signed_closed(tmp_path)
    code = main([str(chain_path), "--public-key", str(key_path), "--strict", "--quiet"], stdout=io.StringIO())
    assert code == 0


# ── #4: key supplied but chain unsigned -> stderr warning ────────────────


def test_key_supplied_but_unsigned_warns(tmp_path, capsys):
    _, key_path = _signed_closed(tmp_path)  # a valid key...
    code = main([str(_unsigned_closed(tmp_path)), "--public-key", str(key_path), "--no-color"])
    captured = capsys.readouterr()
    assert code == 0
    assert "key was not used" in captured.err


# ── #5 / #6: adversarial input fails cleanly (exit 2, no traceback) ───────


def test_json_array_with_non_object_element_is_clean_error(tmp_path):
    p = _write(tmp_path, "bad.json", [1, 2, 3])
    code = main([str(p), "--no-color"], stdout=io.StringIO())
    assert code == 2


def test_valid_json_but_invalid_records_is_clean_error(tmp_path):
    p = tmp_path / "empty_objs.json"
    p.write_text(json.dumps([{}, {}]))
    code = main([str(p), "--no-color"], stdout=io.StringIO())
    assert code == 2


def test_load_records_array_rejects_non_objects():
    with pytest.raises(VerifyError, match="must be a JSON object"):
        load_records_from_string("[1, 2, 3]")
