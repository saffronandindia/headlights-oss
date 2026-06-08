"""VerificationGate — the ground-truth gate.

"Is this real?"

A claim the model proposes is routed to a trusted source, never back to the
model. The model proposes; a database disposes. The caller supplies a ``source``
callable that resolves the claim against authoritative data and returns True when
it checks out. An unverified claim is denied and recorded; the raw claim is never
stored, only its SHA-256 hash.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from headlights_chain.enums import ActionType, Outcome

from headlights_sdk.hashing import hash_value

from headlights_sdk.guards.base import Guard, GuardDenied, GuardResult


class VerificationGate(Guard):
    """Verify a model-proposed claim against a trusted source."""

    name = "VerificationGate"
    action_type = ActionType.DECISION

    def __init__(
        self,
        client,
        *,
        source: Callable[[Any], bool],
        trust_level=None,
    ) -> None:
        super().__init__(client, trust_level=trust_level)
        if not callable(source):
            raise TypeError("source must be a callable trusted resolver, not the model")
        self._source = source

    def check(self, *, claim: Any) -> GuardResult:
        verified = bool(self._source(claim))

        detail: dict[str, Any] = {
            "decision": "allow" if verified else "deny",
            "check": "verification_against_trusted_source",
            "verified": verified,
            "claim_hash": f"sha256:{hash_value(claim)}",
        }

        outcome = Outcome.SUCCESS if verified else Outcome.DENIED
        position = self._record(outcome=outcome, detail=detail)
        reason = None if verified else "claim could not be verified against the trusted source"
        return GuardResult(
            allowed=verified,
            reason=reason,
            record_position=position,
            detail=detail,
        )

    def enforce(self, *, claim: Any) -> GuardResult:
        result = self.check(claim=claim)
        if not result.allowed:
            raise GuardDenied(self.name, result.reason or "denied", result)
        return result
