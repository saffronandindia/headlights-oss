"""Pydantic request/response models for the FastAPI app."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from headlights_chain.enums import ActionType, Outcome, TrustLevel

# Maximum serialised byte length for action_detail / genesis_detail.
# Prevents a single oversized record from exhausting SQLite page budget or
# ballooning public trace HTML.
_ACTION_DETAIL_MAX_BYTES = 65_536  # 64 KiB


# ── Registration ────────────────────────────────────────────────────────


class RegisterAgentRequest(BaseModel):
    agent_name: str = Field(min_length=1, max_length=200)
    owner_email: str = Field(min_length=3, max_length=320)
    purpose: str = Field(min_length=1, max_length=2000)
    agent_version: str = Field(default="0.0.1", min_length=1, max_length=64)
    public_key_pem: str | None = Field(
        default=None,
        description="PEM-encoded ECDSA P-256 public key for signature verification.",
    )


class RegisterAgentResponse(BaseModel):
    agent_id: str
    api_key: str = Field(description="Shown ONCE at registration. Store this securely.")
    created_at: str


# ── Sessions ────────────────────────────────────────────────────────────


class OpenSessionRequest(BaseModel):
    trust_level: TrustLevel = TrustLevel.L1
    genesis_detail: dict[str, Any] = Field(default_factory=dict)

    @field_validator("genesis_detail")
    @classmethod
    def _check_genesis_detail_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        serialised = json.dumps(v)
        if len(serialised.encode()) > _ACTION_DETAIL_MAX_BYTES:
            raise ValueError(
                f"genesis_detail exceeds {_ACTION_DETAIL_MAX_BYTES // 1024} KiB limit"
            )
        return v


class OpenSessionResponse(BaseModel):
    session_id: str
    genesis_position: int
    genesis_record_hash: str
    started_at: str


class CloseSessionResponse(BaseModel):
    session_id: str
    record_count: int
    session_hash: str
    closed_at: str


# ── Publishing (Trace viewer access) ────────────────────────────────────


class PublishSessionRequest(BaseModel):
    """Toggle the public-trace view for a session.

    Sessions are private by default. Publishing makes the public trace URL
    (GET /v1/sessions/{sid}/trace) accessible without authentication. This
    is the mechanism that powers the email-as-demo loop — agent owners
    explicitly opt in to public auditability for sessions they want to
    showcase.
    """

    public: bool = Field(default=True, description="Set False to un-publish.")


class PublishSessionResponse(BaseModel):
    session_id: str
    public: bool
    trace_url: str = Field(description="Path to the public trace view (relative to server root).")


# ── Actions ─────────────────────────────────────────────────────────────


class AppendActionRequest(BaseModel):
    """Server-signed action append (v1 default).

    The server constructs and stores the AAT record. The client only supplies
    the action-level details. Records have no per-record signature unless the
    /signed variant is used (TBD post-v1).
    """

    session_id: str | None = Field(
        default=None,
        description="If omitted, appends to the agent's most recent open session, opening one if none exists.",
    )
    action_type: ActionType
    action_detail: dict[str, Any]
    outcome: Outcome = Outcome.SUCCESS
    trust_level: TrustLevel = TrustLevel.L1

    # Optional AAT §3.2 fields the client may want to record
    risk_score: float | None = Field(default=None, ge=0.0, le=1.0)
    input_hash: str | None = None
    output_hash: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    jurisdiction: str | None = None

    @field_validator("action_detail")
    @classmethod
    def _check_action_detail_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        serialised = json.dumps(v)
        if len(serialised.encode()) > _ACTION_DETAIL_MAX_BYTES:
            raise ValueError(
                f"action_detail exceeds {_ACTION_DETAIL_MAX_BYTES // 1024} KiB limit"
            )
        return v


class AppendActionResponse(BaseModel):
    session_id: str
    position: int
    record_id: str
    record_hash: str


# ── Conduct retrieval ───────────────────────────────────────────────────

# Maximum records returned in a single GET /conduct response.
CONDUCT_PAGE_SIZE = 1_000


class ConductResponse(BaseModel):
    """Records returned by GET /conduct endpoints."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent_id: str
    record_count: int
    records: list[dict[str, Any]]
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Opaque cursor for the next page. Pass as `cursor=` to retrieve the next batch. "
            "Null when no further records exist."
        ),
    )


# ── Error envelope ──────────────────────────────────────────────────────


class ErrorBody(BaseModel):
    error: str
    detail: str | None = None
