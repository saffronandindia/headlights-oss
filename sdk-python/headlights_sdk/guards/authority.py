"""AuthorityGate — the first Layer-2 gate.

"Who issued this instruction, and is that source authorised to bind the agent?"

Scope is source-and-authority only. It does NOT check whether the instruction
complies with policy — that is ConstraintGate's job. An instruction from an
unrecognised or unauthorised source is denied and recorded as a DECISION/denied
AAT record *before* the agent acts on it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from headlights_chain.enums import ActionType, Outcome

from headlights_sdk.hashing import hash_value

from headlights_sdk.guards.base import Guard, GuardDenied, GuardResult


class AuthorityGate(Guard):
    """Verify that an instruction's source is authorised to bind the agent."""

    name = "AuthorityGate"
    action_type = ActionType.DECISION

    def __init__(
        self,
        client,
        *,
        authorised_sources: Iterable[str],
        trust_level=None,
    ) -> None:
        super().__init__(client, trust_level=trust_level)
        self._authorised: set[str] = set(authorised_sources)

    def check(self, *, source: str, instruction: str | None = None) -> GuardResult:
        """Record an authority decision for ``source`` and return the result."""
        authorised = source in self._authorised
        detail: dict[str, Any] = {
            "decision": "allow" if authorised else "deny",
            "check": "instruction_source_authority",
            "instruction_source": source,
            "authorised": authorised,
        }
        if instruction is not None:
            # Record a hash of the instruction, never the raw text.
            detail["instruction_hash"] = f"sha256:{hash_value(instruction)}"

        outcome = Outcome.SUCCESS if authorised else Outcome.DENIED
        position = self._record(outcome=outcome, detail=detail)
        reason = None if authorised else f"unauthorised instruction source: {source!r}"
        return GuardResult(
            allowed=authorised,
            reason=reason,
            record_position=position,
            detail=detail,
        )

    def enforce(self, *, source: str, instruction: str | None = None) -> GuardResult:
        """Like :meth:`check`, but raise :class:`GuardDenied` on an unauthorised source."""
        result = self.check(source=source, instruction=instruction)
        if not result.allowed:
            raise GuardDenied(self.name, result.reason or "denied", result)
        return result
