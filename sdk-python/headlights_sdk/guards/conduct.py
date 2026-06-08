"""ConductRecord — the Layer-1 foundation record helper.

The signed, hash-chained log that every other module writes through. This helper
assembles one AAT record per AI action with full context: the model version, a
hash of the system prompt, the retrieved sources, the tool calls, and a hash of
the output. The record is written through the client's chain, so it is signed and
linked like any other conduct record. Prompts and outputs are hashed, never
stored raw.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from headlights_chain.enums import ActionType, Outcome

from headlights_sdk.hashing import hash_value


class ConductRecord:
    """Write a full AAT conduct record for one AI action."""

    name = "ConductRecord"

    def __init__(self, client, *, trust_level=None) -> None:
        self._client = client
        self._trust_level = trust_level

    def write(
        self,
        *,
        model_id: str | None = None,
        system_prompt: str | None = None,
        retrieved: Sequence[Any] | None = None,
        tool_calls: Sequence[str] | None = None,
        output: Any | None = None,
        action_type: ActionType | str = ActionType.DECISION,
        outcome: Outcome | str = Outcome.SUCCESS,
        **extra: Any,
    ) -> tuple[int, str]:
        """Assemble and append a conduct record. Returns ``(position, hash)``."""
        detail: dict[str, Any] = {"record": "conduct"}
        if model_id is not None:
            detail["model_id"] = model_id
        if system_prompt is not None:
            detail["system_prompt_hash"] = f"sha256:{hash_value(system_prompt)}"
        if retrieved is not None:
            detail["retrieved_count"] = len(retrieved)
            detail["retrieved_hash"] = f"sha256:{hash_value(list(retrieved))}"
        if tool_calls is not None:
            detail["tool_calls"] = list(tool_calls)
        if output is not None:
            detail["output_hash"] = f"sha256:{hash_value(output)}"
        detail.update(extra)

        return self._client.record_action(
            action_type,
            detail,
            outcome=outcome,
            trust_level=self._trust_level,
        )
