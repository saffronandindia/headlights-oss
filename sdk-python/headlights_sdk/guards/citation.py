"""CitationVerifier — the citation-reality gate.

"Is every citation real?"

Extracts citations from a document and checks each one against a trusted source
(a set of known-valid identifiers and/or a verifier callable that queries a real
legal, academic, or technical database) before the document can ship. A document
containing any citation that cannot be verified is denied and recorded, with the
unverifiable citations named in the record.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any, Pattern

from headlights_chain.enums import ActionType, Outcome

from headlights_sdk.guards.base import Guard, GuardDenied, GuardResult


class CitationVerifier(Guard):
    """Verify that every citation in a document is real."""

    name = "CitationVerifier"
    action_type = ActionType.DECISION

    def __init__(
        self,
        client,
        *,
        known_valid: Iterable[str] | None = None,
        verifier: Callable[[str], bool] | None = None,
        citation_pattern: str | Pattern[str] = r"\[([^\]]+)\]",
        trust_level=None,
    ) -> None:
        super().__init__(client, trust_level=trust_level)
        self._known_valid: set[str] = set(known_valid or ())
        # verifier queries a trusted source; returns True if the citation is real.
        self._verifier = verifier
        self._pattern: Pattern[str] = (
            citation_pattern
            if isinstance(citation_pattern, re.Pattern)
            else re.compile(citation_pattern)
        )

    def extract(self, content: str) -> list[str]:
        """Return the citation tokens found in ``content``."""
        return self._pattern.findall(content)

    def _is_real(self, citation: str) -> bool:
        if citation in self._known_valid:
            return True
        if self._verifier is not None:
            return bool(self._verifier(citation))
        return False

    def check(self, *, content: str) -> GuardResult:
        citations = self.extract(content)
        unverified = [c for c in citations if not self._is_real(c)]
        all_real = not unverified

        detail: dict[str, Any] = {
            "decision": "allow" if all_real else "deny",
            "check": "citation_verification",
            "citations_checked": len(citations),
            "unverified_citations": unverified,
            "all_verified": all_real,
        }

        outcome = Outcome.SUCCESS if all_real else Outcome.DENIED
        position = self._record(outcome=outcome, detail=detail)
        reason = (
            None
            if all_real
            else f"{len(unverified)} citation(s) could not be verified: {unverified}"
        )
        return GuardResult(
            allowed=all_real,
            reason=reason,
            record_position=position,
            detail=detail,
        )

    def enforce(self, *, content: str) -> GuardResult:
        result = self.check(content=content)
        if not result.allowed:
            raise GuardDenied(self.name, result.reason or "denied", result)
        return result
