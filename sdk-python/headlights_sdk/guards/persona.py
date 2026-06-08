"""PersonaGuard — the identity-consistency gate.

"Does this reply match the agent's defined identity and scope?"

Catches persona drift and impersonation regardless of which subsystem produced
the reply. The caller supplies named drift patterns (for example: claiming to be
human, speaking as a different named assistant, or leaking a previous bot's
persona). A reply that matches any of them is denied and recorded. The raw reply
is never stored, only its SHA-256 hash and the matched signal labels.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Pattern

from headlights_chain.enums import ActionType, Outcome

from headlights_sdk.hashing import hash_value

from headlights_sdk.guards.base import Guard, GuardDenied, GuardResult


class PersonaGuard(Guard):
    """Detect persona drift and impersonation in an agent's reply."""

    name = "PersonaGuard"
    action_type = ActionType.DECISION

    def __init__(
        self,
        client,
        *,
        drift_patterns: Mapping[str, str | Pattern[str]] | None = None,
        trust_level=None,
    ) -> None:
        super().__init__(client, trust_level=trust_level)
        patterns = drift_patterns or {}
        self._patterns: dict[str, Pattern[str]] = {
            label: (p if isinstance(p, re.Pattern) else re.compile(p, re.IGNORECASE))
            for label, p in patterns.items()
        }

    def scan(self, reply: str) -> list[str]:
        """Return the labels of every drift pattern found in ``reply``."""
        return [label for label, pat in self._patterns.items() if pat.search(reply)]

    def check(self, *, reply: str, identity: str | None = None) -> GuardResult:
        signals = self.scan(reply)
        on_persona = not signals

        detail: dict[str, Any] = {
            "decision": "allow" if on_persona else "deny",
            "check": "persona_consistency",
            "on_persona": on_persona,
            "drift_signals": signals,
            "reply_hash": f"sha256:{hash_value(reply)}",
        }
        if identity is not None:
            detail["identity"] = identity

        outcome = Outcome.SUCCESS if on_persona else Outcome.DENIED
        position = self._record(outcome=outcome, detail=detail)
        reason = None if on_persona else f"reply shows persona drift: {', '.join(signals)}"
        return GuardResult(
            allowed=on_persona,
            reason=reason,
            record_position=position,
            detail=detail,
        )

    def enforce(self, *, reply: str, identity: str | None = None) -> GuardResult:
        result = self.check(reply=reply, identity=identity)
        if not result.allowed:
            raise GuardDenied(self.name, result.reason or "denied", result)
        return result
