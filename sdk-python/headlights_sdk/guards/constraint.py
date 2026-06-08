"""ConstraintGate — the standing-rules policy gate.

"Does this action comply with the declared standing rules?"

A policy gate on tool calls and actions. An action that is on the disallowed
list, or that fails the supplied policy callable, is denied and recorded as a
DECISION/denied AAT record. Violations require explicit, recorded approval
(re-run the action through an out-of-band approval path that records its own
record); the gate itself does not silently permit them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from headlights_chain.enums import ActionType, Outcome

from headlights_sdk.hashing import hash_value

from headlights_sdk.guards.base import Guard, GuardDenied, GuardResult


class ConstraintGate(Guard):
    """Check an action against the declared standing rules."""

    name = "ConstraintGate"
    action_type = ActionType.DECISION

    def __init__(
        self,
        client,
        *,
        disallowed_actions: Iterable[str] | None = None,
        policy: Callable[[str, dict[str, Any]], bool] | None = None,
        trust_level=None,
    ) -> None:
        super().__init__(client, trust_level=trust_level)
        self._disallowed: set[str] = set(disallowed_actions or ())
        # policy returns True when the action complies.
        self._policy = policy

    def check(self, *, action: str, parameters: dict[str, Any] | None = None) -> GuardResult:
        parameters = parameters or {}
        breaks_list = action in self._disallowed
        breaks_policy = self._policy is not None and not self._policy(action, parameters)
        compliant = not (breaks_list or breaks_policy)

        detail: dict[str, Any] = {
            "decision": "allow" if compliant else "deny",
            "check": "standing_rules_compliance",
            "action": action,
            "compliant": compliant,
        }
        if parameters:
            detail["parameters_hash"] = f"sha256:{hash_value(parameters)}"

        outcome = Outcome.SUCCESS if compliant else Outcome.DENIED
        position = self._record(outcome=outcome, detail=detail)
        reason = None if compliant else f"action {action!r} violates the declared standing rules"
        return GuardResult(
            allowed=compliant,
            reason=reason,
            record_position=position,
            detail=detail,
        )

    def enforce(self, *, action: str, parameters: dict[str, Any] | None = None) -> GuardResult:
        result = self.check(action=action, parameters=parameters)
        if not result.allowed:
            raise GuardDenied(self.name, result.reason or "denied", result)
        return result
