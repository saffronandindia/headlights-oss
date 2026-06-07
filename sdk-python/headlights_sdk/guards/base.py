"""Base for the thin Headlights governance guards.

A guard wraps a :class:`headlights_sdk.client.Client`. Each named guard applies
one pre- or post-execution condition and records the governance decision as a
valid AAT record (draft-sharif-agent-audit-trail-00) on the client's chain.

The guard *names* are the Headlights taxonomy; the record *format* is the
spec's. Guards add no new crypto and no new record format — they delegate to
``client.record_action`` / ``Chain.append``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from headlights_chain.enums import ActionType, Outcome, TrustLevel

if TYPE_CHECKING:
    from headlights_sdk.client import Client


@dataclass(frozen=True)
class GuardResult:
    """Outcome of a guard check.

    ``allowed``          True when the action may proceed.
    ``reason``           Short human-readable explanation when denied, else None.
    ``record_position``  Index of the AAT record written for this decision.
    ``detail``           The ``action_detail`` that was recorded (minus the
                         ``guard`` key), for callers that want to inspect it.
    """

    allowed: bool
    reason: str | None
    record_position: int | None
    detail: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.allowed


class GuardDenied(RuntimeError):
    """Raised by ``Guard.enforce(...)`` when a check is denied."""

    def __init__(self, guard: str, reason: str, result: GuardResult) -> None:
        super().__init__(f"{guard}: {reason}")
        self.result = result


class Guard:
    """Common machinery for the named governance guards.

    Subclasses set :attr:`name` and implement a ``check(...)`` method that
    builds an ``action_detail`` dict, chooses an :class:`Outcome`, and calls
    :meth:`_record` to write the AAT record.
    """

    #: Human-facing guard name, written into ``action_detail["guard"]``.
    name: str = "Guard"
    #: AAT ``action_type`` for the recorded governance decision.
    action_type: ActionType = ActionType.DECISION

    def __init__(
        self,
        client: "Client",
        *,
        trust_level: TrustLevel | str | None = None,
    ) -> None:
        self._client = client
        self._trust_level = trust_level

    def _record(self, *, outcome: Outcome, detail: dict[str, Any]) -> int:
        """Write a valid AAT record for this decision; return its chain position."""
        position, _ = self._client.record_action(
            self.action_type,
            {"guard": self.name, **detail},
            outcome=outcome,
            trust_level=self._trust_level,
        )
        return position
