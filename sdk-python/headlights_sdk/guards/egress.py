"""EgressGate — the Layer-2 gate that runs where data would LEAVE.

"Does this output contain sensitive data, and is the destination inside the
trust boundary?"

Scope is data-classification + destination only. It is NOT content moderation.
Output bound for a destination outside the trust boundary that carries sensitive
data is blocked and recorded. The raw content is never written to the AAT
record — only a SHA-256 hash of it and the list of matched categories.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Pattern

from headlights_chain.enums import ActionType, Outcome

from headlights_sdk.hashing import hash_value

from headlights_sdk.guards.base import Guard, GuardDenied, GuardResult


class EgressGate(Guard):
    """Block sensitive data leaving the trust boundary; record every decision."""

    name = "EgressGate"
    action_type = ActionType.DECISION

    def __init__(
        self,
        client,
        *,
        trusted_destinations: Iterable[str],
        sensitive_patterns: Mapping[str, str | Pattern[str]] | None = None,
        trust_level=None,
    ) -> None:
        super().__init__(client, trust_level=trust_level)
        self._trusted: set[str] = set(trusted_destinations)
        patterns = sensitive_patterns or {}
        self._patterns: dict[str, Pattern[str]] = {
            label: (p if isinstance(p, re.Pattern) else re.compile(p))
            for label, p in patterns.items()
        }

    def classify(self, content: str) -> list[str]:
        """Return the labels of every sensitive pattern found in ``content``."""
        return [label for label, pat in self._patterns.items() if pat.search(content)]

    def check(self, *, content: str, destination: str) -> GuardResult:
        """Record an egress decision for ``content`` -> ``destination``."""
        trusted = destination in self._trusted
        categories = self.classify(content)
        blocked = (not trusted) and bool(categories)

        detail: dict[str, Any] = {
            "decision": "deny" if blocked else "allow",
            "check": "egress_data_classification",
            "destination": destination,
            "destination_trusted": trusted,
            "classifications": categories,
            # The raw content is deliberately omitted; only its hash is recorded.
            "content_hash": f"sha256:{hash_value(content)}",
        }

        outcome = Outcome.DENIED if blocked else Outcome.SUCCESS
        position = self._record(outcome=outcome, detail=detail)
        reason = (
            f"sensitive data ({', '.join(categories)}) bound for untrusted "
            f"destination {destination!r}"
            if blocked
            else None
        )
        return GuardResult(
            allowed=not blocked,
            reason=reason,
            record_position=position,
            detail=detail,
        )

    def enforce(self, *, content: str, destination: str) -> GuardResult:
        """Like :meth:`check`, but raise :class:`GuardDenied` when egress is blocked."""
        result = self.check(content=content, destination=destination)
        if not result.allowed:
            raise GuardDenied(self.name, result.reason or "denied", result)
        return result
