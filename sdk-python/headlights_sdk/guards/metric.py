"""MetricRecord — the Layer-1 aggregate-metric record helper.

A signed aggregate metric computed over the signed conduct records already on the
chain, with the chain's current root hash recorded alongside it. That root binds
the aggregate to the underlying events: a regulator, union, or board can recompute
the metric from the verified records and confirm it was not fabricated after the
fact. Use it for workforce or automated-decision metrics that need to be provable.
"""

from __future__ import annotations

from typing import Any

from headlights_chain.enums import ActionType, Outcome


class MetricRecord:
    """Write a signed aggregate metric bound to the chain root."""

    name = "MetricRecord"

    def __init__(self, client, *, trust_level=None) -> None:
        self._client = client
        self._trust_level = trust_level

    def write(
        self,
        name: str,
        value: Any,
        *,
        sample_size: int | None = None,
        outcome: Outcome | str = Outcome.SUCCESS,
        **extra: Any,
    ) -> tuple[int, str]:
        """Append an aggregate-metric record. Returns ``(position, hash)``.

        The chain's current last hash is recorded as ``chain_root`` (when a chain
        already exists), binding this aggregate to every record that preceded it.
        """
        detail: dict[str, Any] = {
            "record": "metric",
            "metric": name,
            "value": value,
        }
        if sample_size is not None:
            detail["sample_size"] = sample_size

        chain = self._client.chain
        if chain is not None:
            detail["chain_root"] = chain.state.last_hash

        detail.update(extra)

        return self._client.record_action(
            ActionType.DECISION,
            detail,
            outcome=outcome,
            trust_level=self._trust_level,
        )
