"""AAT-aligned conduct record.

Implements the record schema in draft-sharif-agent-audit-trail-00:

  §3.1 — REQUIRED fields (always emitted, including the nullable ones):
    record_id, timestamp, agent_id, agent_version, session_id, action_type,
    action_detail, outcome, trust_level, parent_record_id, prev_hash

  §3.2 — OPTIONAL fields (emitted only when set):
    human_override, risk_score, model_id, input_hash, output_hash,
    latency_ms, cost_estimate, sanctions_check, jurisdiction, signature

Unknown fields are preserved (AAT §3.1) so that downstream processors do not
silently drop information they do not understand. Field names beginning with
`aat_` are reserved by the spec; we do not enforce this beyond a soft warning
in v1.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from headlights_chain.canonical import is_valid_hex_hash
from headlights_chain.enums import ActionType, Outcome, TrustLevel

# RFC 3339 with mandatory UTC offset (AAT §3.1).
# Accepts Z or ±HH:MM offsets; permits 1-9 fractional-second digits.
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$"
)

# SemVer 2.0.0 (subset that covers the cases we care about).
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(-[\w.-]+)?(\+[\w.-]+)?$")

MANDATORY_FIELDS: tuple[str, ...] = (
    "record_id",
    "timestamp",
    "agent_id",
    "agent_version",
    "session_id",
    "action_type",
    "action_detail",
    "outcome",
    "trust_level",
    "parent_record_id",
    "prev_hash",
)

OPTIONAL_FIELDS: tuple[str, ...] = (
    "human_override",
    "risk_score",
    "model_id",
    "input_hash",
    "output_hash",
    "latency_ms",
    "cost_estimate",
    "sanctions_check",
    "jurisdiction",
    "signature",
)


class Record(BaseModel):
    """A single AAT conduct record."""

    model_config = ConfigDict(
        validate_assignment=True,
        extra="allow",  # AAT §3.1: "Unknown fields ... SHOULD be preserved"
    )

    # ── Mandatory fields (always emitted) ───────────────────────────────
    record_id: str = Field(description="UUIDv4 per RFC 9562")
    timestamp: str = Field(description="RFC 3339 with mandatory UTC offset")
    agent_id: str = Field(description="URI per RFC 3986")
    agent_version: str = Field(description="SemVer 2.0.0")
    session_id: str = Field(description="UUIDv4; shared across the session")
    action_type: ActionType
    action_detail: dict[str, Any]
    outcome: Outcome
    trust_level: TrustLevel
    parent_record_id: str | None
    prev_hash: str | None

    # ── Optional fields (emitted only when set) ─────────────────────────
    human_override: dict[str, Any] | None = None
    risk_score: float | None = None
    model_id: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    latency_ms: int | None = None
    cost_estimate: dict[str, Any] | None = None
    sanctions_check: dict[str, Any] | None = None
    jurisdiction: str | None = None
    signature: str | None = None

    # ── Validators ──────────────────────────────────────────────────────

    @field_validator("record_id", "session_id")
    @classmethod
    def _check_uuid_v4(cls, v: str) -> str:
        try:
            u = uuid.UUID(v)
        except ValueError as e:
            raise ValueError(f"must be a valid UUID: {e}") from e
        if u.version != 4:
            raise ValueError(f"must be UUIDv4 per RFC 9562; got version {u.version}")
        return v

    @field_validator("timestamp")
    @classmethod
    def _check_rfc3339(cls, v: str) -> str:
        if not RFC3339_PATTERN.match(v):
            raise ValueError(
                f"timestamp must match RFC 3339 with UTC offset; got {v!r}"
            )
        return v

    @field_validator("agent_version")
    @classmethod
    def _check_semver(cls, v: str) -> str:
        if not SEMVER_PATTERN.match(v):
            raise ValueError(f"agent_version must be SemVer 2.0.0; got {v!r}")
        return v

    @field_validator("agent_id")
    @classmethod
    def _check_uri(cls, v: str) -> str:
        # Light validation: must contain a scheme separator and no whitespace.
        if ":" not in v or v.startswith(":") or any(c.isspace() for c in v):
            raise ValueError(f"agent_id must be a URI; got {v!r}")
        return v

    @field_validator("prev_hash")
    @classmethod
    def _check_prev_hash(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not is_valid_hex_hash(v):
            raise ValueError(
                "prev_hash must be a 64-character lowercase hex SHA-256 digest"
            )
        return v

    @field_validator("risk_score")
    @classmethod
    def _check_risk_score(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"risk_score must be in [0.0, 1.0]; got {v}")
        return v

    @field_validator("jurisdiction")
    @classmethod
    def _check_iso3166(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not (len(v) == 2 and v.isalpha() and v == v.upper()):
            raise ValueError(
                f"jurisdiction must be ISO 3166-1 alpha-2 uppercase; got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _check_action_detail_not_empty(self) -> "Record":
        if not self.action_detail:
            raise ValueError(
                "action_detail must contain at least one field relevant to action_type"
            )
        return self

    @model_validator(mode="after")
    def _check_genesis_invariants(self) -> "Record":
        if self.parent_record_id is None and self.prev_hash is not None:
            raise ValueError(
                "Genesis: when parent_record_id is null, prev_hash must also be null"
            )
        if self.parent_record_id is not None and self.prev_hash is None:
            raise ValueError(
                "Non-genesis: when parent_record_id is set, prev_hash must also be set"
            )
        return self

    # ── Serialisation helpers ───────────────────────────────────────────

    def to_canonical_dict(self, *, include_signature: bool = True) -> dict[str, Any]:
        """Return the dict that will be JCS-canonicalised.

        Mandatory fields are always emitted, even when None.
        Optional fields are emitted only when not None.
        The `signature` field is omitted when include_signature is False, so
        callers can compute the digest covered by the signature itself.
        Unknown extra fields are preserved.
        """
        full = self.model_dump(mode="json", exclude_none=False)
        body: dict[str, Any] = {}

        for name in MANDATORY_FIELDS:
            body[name] = full[name]

        for name in OPTIONAL_FIELDS:
            value = full.get(name)
            if value is None:
                continue
            if name == "signature" and not include_signature:
                continue
            body[name] = value

        known = set(MANDATORY_FIELDS) | set(OPTIONAL_FIELDS)
        for name, value in full.items():
            if name in known:
                continue
            if value is None:
                continue
            body[name] = value

        return body

    @classmethod
    def new(
        cls,
        *,
        agent_id: str,
        agent_version: str,
        session_id: str,
        action_type: ActionType | str,
        action_detail: dict[str, Any],
        outcome: Outcome | str,
        trust_level: TrustLevel | str,
        parent_record_id: str | None,
        prev_hash: str | None,
        timestamp: str | None = None,
        record_id: str | None = None,
        **optional: Any,
    ) -> "Record":
        """Convenience constructor with auto-generated record_id and timestamp."""
        return cls(
            record_id=record_id or str(uuid.uuid4()),
            timestamp=timestamp or utc_now_rfc3339(),
            agent_id=agent_id,
            agent_version=agent_version,
            session_id=session_id,
            action_type=action_type,
            action_detail=action_detail,
            outcome=outcome,
            trust_level=trust_level,
            parent_record_id=parent_record_id,
            prev_hash=prev_hash,
            **optional,
        )


def utc_now_rfc3339() -> str:
    """Current UTC time as an RFC 3339 string with millisecond precision.

    AAT §3.1 RECOMMENDS millisecond precision; microsecond is OPTIONAL. We
    emit milliseconds by default so the canonical form is stable across
    platforms that vary in microsecond support.
    """
    now = datetime.now(timezone.utc)
    millis = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"
