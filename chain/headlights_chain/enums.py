"""Enumerations defined by draft-sharif-agent-audit-trail-00.

These are the closed vocabularies the spec mandates. Strings are used so the
canonical JSON form matches the spec exactly (no integer encodings).
"""

from __future__ import annotations

from enum import Enum


class ActionType(str, Enum):
    """AAT §5 — registered action_type values (IANA registry §12.1)."""

    TOOL_CALL = "tool_call"
    TOOL_RESPONSE = "tool_response"
    DECISION = "decision"
    DELEGATION = "delegation"
    ESCALATION = "escalation"
    ERROR = "error"
    LIFECYCLE = "lifecycle"


class Outcome(str, Enum):
    """AAT §3.1 outcome — registered values (IANA registry §12.2)."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    DENIED = "denied"
    ESCALATED = "escalated"


class TrustLevel(str, Enum):
    """AAT §3.1 trust_level — L0..L4.

    L0 — no verification
    L1 — self-signed
    L2 — authority-signed
    L3 — mutual authentication
    L4 — full mutual + revocation + monitoring
    """

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class LifecycleEvent(str, Enum):
    """AAT §5.7 — lifecycle.event values."""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PAUSE = "pause"
    RESUME = "resume"
    CONFIGURATION_CHANGE = "configuration_change"
    KEY_ROTATION = "key_rotation"
    TRUST_LEVEL_CHANGE = "trust_level_change"
    # Tombstone marker per AAT §6 (record deletion)
    RECORD_DELETED = "record_deleted"


class SanctionsResult(str, Enum):
    """AAT §3.2 sanctions_check.result."""

    CLEAR = "clear"
    MATCH = "match"
    ERROR = "error"


class ErrorCategory(str, Enum):
    """AAT §5.6 action_detail.error_category for action_type=error."""

    TRANSPORT = "transport"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    TIMEOUT = "timeout"
    INTERNAL = "internal"
    EXTERNAL = "external"
