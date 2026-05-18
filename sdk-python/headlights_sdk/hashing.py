"""Helpers for hashing function inputs and outputs into AAT-suitable digests.

AAT records carry `input_hash` and `output_hash` as opaque strings. We produce
SHA-256 hex digests over a best-effort canonical JSON form of the value, so
identical inputs produce identical hashes within a session and across runs.

Non-JSON-serialisable values fall back to `repr(value)` — not perfect, but
better than crashing the decorator on first contact with an unusual object.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _json_default(value: Any) -> str:
    """Fallback serialiser for objects json.dumps cannot handle natively."""
    try:
        return repr(value)
    except Exception:  # noqa: BLE001 — keep the SDK from crashing on exotic objects
        return f"<unrepresentable {type(value).__name__}>"


def hash_value(value: Any) -> str:
    """Return a stable SHA-256 hex digest of a Python value.

    Sorts dict keys (sort_keys=True) for stability across calls.
    """
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")
    except (TypeError, ValueError):
        encoded = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()


def hash_call_inputs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Hash the inputs of a function call into a single digest."""
    return hash_value({"args": list(args), "kwargs": kwargs})
