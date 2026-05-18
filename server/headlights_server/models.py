"""Pydantic request/response models for the FastAPI app."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from headlights_chain.enums import ActionType, Outcome, TrustLevel


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


class AppendActionResponse(BaseModel):
    session_id: str
    position: int
    record_id: str
    record_hash: str


# ── Conduct retrieval ───────────────────────────────────────────────────


class ConductResponse(BaseModel):
    """Records returned by GET /conduct endpoints."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent_id: str
    record_count: int
    records: list[dict[str, Any]]


# ── Error envelope ──────────────────────────────────────────────────────


class ErrorBody(BaseModel):
    error: str
    detail: str | None = None
