"""Tests for the AAT-aligned Record model."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from headlights_chain.enums import ActionType, Outcome, TrustLevel
from headlights_chain.records import (
    MANDATORY_FIELDS,
    OPTIONAL_FIELDS,
    Record,
    utc_now_rfc3339,
)


def _minimal_kwargs(**overrides):
    base = dict(
        agent_id="urn:headlights:agent:test",
        agent_version="1.0.0",
        session_id=str(uuid.uuid4()),
        action_type="lifecycle",
        action_detail={"event": "session_start"},
        outcome="success",
        trust_level="L1",
        parent_record_id=None,
        prev_hash=None,
    )
    base.update(overrides)
    return base


def test_new_with_defaults_generates_uuid_and_timestamp() -> None:
    r = Record.new(**_minimal_kwargs())
    assert uuid.UUID(r.record_id).version == 4
    assert r.timestamp.endswith("Z")


def test_record_id_must_be_uuid_v4() -> None:
    with pytest.raises(ValidationError):
        Record.new(**_minimal_kwargs(record_id="not-a-uuid"))


def test_uuid_v1_rejected() -> None:
    v1 = str(uuid.uuid1())
    with pytest.raises(ValidationError, match="UUIDv4"):
        Record.new(**_minimal_kwargs(record_id=v1))


def test_timestamp_must_be_rfc3339_with_offset() -> None:
    with pytest.raises(ValidationError, match="RFC 3339"):
        Record.new(**_minimal_kwargs(timestamp="2026-05-18 08:00:00"))
    with pytest.raises(ValidationError, match="RFC 3339"):
        Record.new(**_minimal_kwargs(timestamp="2026-05-18T08:00:00"))  # no offset


def test_timestamp_accepts_z_and_numeric_offsets() -> None:
    Record.new(**_minimal_kwargs(timestamp="2026-05-18T08:00:00Z"))
    Record.new(**_minimal_kwargs(timestamp="2026-05-18T08:00:00.123Z"))
    Record.new(**_minimal_kwargs(timestamp="2026-05-18T08:00:00+10:00"))


def test_agent_version_must_be_semver() -> None:
    with pytest.raises(ValidationError, match="SemVer"):
        Record.new(**_minimal_kwargs(agent_version="1.0"))
    Record.new(**_minimal_kwargs(agent_version="1.0.0"))
    Record.new(**_minimal_kwargs(agent_version="2.1.3-beta.1"))


def test_agent_id_must_be_uri_like() -> None:
    with pytest.raises(ValidationError, match="URI"):
        Record.new(**_minimal_kwargs(agent_id="plain-string"))
    with pytest.raises(ValidationError, match="URI"):
        Record.new(**_minimal_kwargs(agent_id="urn: spaces:bad"))


def test_prev_hash_must_be_64_hex_lowercase_or_none() -> None:
    # Non-genesis: prev_hash set with a hex digest is fine.
    Record.new(
        **_minimal_kwargs(
            parent_record_id=str(uuid.uuid4()),
            prev_hash="a" * 64,
        )
    )
    with pytest.raises(ValidationError, match="hex SHA-256"):
        Record.new(
            **_minimal_kwargs(
                parent_record_id=str(uuid.uuid4()),
                prev_hash="A" * 64,  # uppercase
            )
        )
    with pytest.raises(ValidationError, match="hex SHA-256"):
        Record.new(
            **_minimal_kwargs(
                parent_record_id=str(uuid.uuid4()),
                prev_hash="too-short",
            )
        )


def test_risk_score_range() -> None:
    Record.new(**_minimal_kwargs(risk_score=0.0))
    Record.new(**_minimal_kwargs(risk_score=1.0))
    with pytest.raises(ValidationError, match=r"\[0\.0, 1\.0\]"):
        Record.new(**_minimal_kwargs(risk_score=1.5))
    with pytest.raises(ValidationError, match=r"\[0\.0, 1\.0\]"):
        Record.new(**_minimal_kwargs(risk_score=-0.1))


def test_jurisdiction_must_be_iso3166_alpha2_upper() -> None:
    Record.new(**_minimal_kwargs(jurisdiction="AU"))
    with pytest.raises(ValidationError, match="ISO 3166"):
        Record.new(**_minimal_kwargs(jurisdiction="au"))
    with pytest.raises(ValidationError, match="ISO 3166"):
        Record.new(**_minimal_kwargs(jurisdiction="AUS"))


def test_action_detail_must_be_non_empty() -> None:
    with pytest.raises(ValidationError, match="action_detail"):
        Record.new(**_minimal_kwargs(action_detail={}))


def test_genesis_invariants_enforced() -> None:
    # parent_record_id None but prev_hash set → invalid
    with pytest.raises(ValidationError, match="Genesis"):
        Record.new(
            **_minimal_kwargs(parent_record_id=None, prev_hash="a" * 64)
        )
    # parent_record_id set but prev_hash None → invalid
    with pytest.raises(ValidationError, match="Non-genesis"):
        Record.new(
            **_minimal_kwargs(parent_record_id=str(uuid.uuid4()), prev_hash=None)
        )


def test_to_canonical_dict_emits_all_mandatory_fields_including_nulls() -> None:
    r = Record.new(**_minimal_kwargs())
    d = r.to_canonical_dict()
    for f in MANDATORY_FIELDS:
        assert f in d
    assert d["parent_record_id"] is None
    assert d["prev_hash"] is None


def test_to_canonical_dict_omits_unset_optionals() -> None:
    r = Record.new(**_minimal_kwargs())
    d = r.to_canonical_dict()
    for f in OPTIONAL_FIELDS:
        assert f not in d


def test_to_canonical_dict_includes_set_optionals() -> None:
    r = Record.new(**_minimal_kwargs(risk_score=0.42, jurisdiction="AU"))
    d = r.to_canonical_dict()
    assert d["risk_score"] == 0.42
    assert d["jurisdiction"] == "AU"


def test_to_canonical_dict_signature_inclusion() -> None:
    r = Record.new(**_minimal_kwargs(signature="abc"))
    assert "signature" in r.to_canonical_dict(include_signature=True)
    assert "signature" not in r.to_canonical_dict(include_signature=False)


def test_enum_fields_serialise_to_strings() -> None:
    r = Record.new(**_minimal_kwargs())
    d = r.to_canonical_dict()
    assert d["action_type"] == "lifecycle"
    assert d["outcome"] == "success"
    assert d["trust_level"] == "L1"


def test_extra_fields_preserved() -> None:
    r = Record.new(**_minimal_kwargs(custom_field="kept"))
    d = r.to_canonical_dict()
    assert d.get("custom_field") == "kept"


def test_record_can_be_constructed_from_canonical_dict() -> None:
    """Round-trip: model_dump → kwargs → Record."""
    original = Record.new(**_minimal_kwargs(risk_score=0.5))
    canonical = original.to_canonical_dict()
    rebuilt = Record(**canonical)
    assert rebuilt.to_canonical_dict() == canonical


def test_utc_now_rfc3339_is_valid() -> None:
    ts = utc_now_rfc3339()
    Record.new(**_minimal_kwargs(timestamp=ts))  # should not raise


def test_enum_classes_accept_string_input() -> None:
    r = Record.new(
        **_minimal_kwargs(
            action_type=ActionType.LIFECYCLE,
            outcome=Outcome.SUCCESS,
            trust_level=TrustLevel.L2,
        )
    )
    assert r.action_type == ActionType.LIFECYCLE
    assert r.outcome == Outcome.SUCCESS
    assert r.trust_level == TrustLevel.L2
