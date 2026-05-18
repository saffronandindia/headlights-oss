"""Core verifier logic: parse a chain export, run Chain.verify, return result.

The CLI in `cli.py` is a thin wrapper around these functions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from headlights_chain import Chain, VerificationResult, VerifyingKey


class VerifyError(Exception):
    """Raised when the input cannot be parsed as a chain export."""


@dataclass(frozen=True)
class VerifyOutcome:
    """The result returned by `verify_file`."""

    result: VerificationResult
    record_count: int
    session_id: str | None
    agent_id: str | None


def load_records_from_string(text: str) -> list[dict[str, Any]]:
    """Parse a chain export.

    Accepts either:
      - A JSON array of records: `[{...}, {...}]`
      - NDJSON: one record per line
    Auto-detected from the first non-whitespace character.
    """
    stripped = text.lstrip()
    if not stripped:
        raise VerifyError("input is empty")

    if stripped.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise VerifyError(f"invalid JSON: {e}") from e
        if not isinstance(data, list):
            raise VerifyError("expected a JSON array of records")
        return data

    # NDJSON
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            raise VerifyError(f"invalid JSON on line {line_number}: {e}") from e
        if not isinstance(record, dict):
            raise VerifyError(f"line {line_number} is not a JSON object")
        records.append(record)

    if not records:
        raise VerifyError("input contained no records")
    return records


def load_records(path: Path | str) -> list[dict[str, Any]]:
    """Load records from a filesystem path."""
    p = Path(path)
    if not p.exists():
        raise VerifyError(f"file not found: {p}")
    if not p.is_file():
        raise VerifyError(f"not a file: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise VerifyError(f"cannot read {p}: {e}") from e
    return load_records_from_string(text)


def verify_file(
    path: Path | str,
    *,
    public_key_pem: bytes | None = None,
) -> VerifyOutcome:
    """Load records from `path`, run Chain.verify, return the outcome.

    If `public_key_pem` is provided and any records carry a `signature`, the
    signatures are verified against that key.
    """
    records = load_records(path)
    chain = Chain.from_records(records)

    verifying_key: VerifyingKey | None = None
    if public_key_pem is not None:
        try:
            verifying_key = VerifyingKey.from_pem(public_key_pem)
        except ValueError as e:
            raise VerifyError(f"cannot load public key: {e}") from e

    result = chain.verify(verifying_key=verifying_key)
    first = chain.records()[0] if len(chain) > 0 else None
    return VerifyOutcome(
        result=result,
        record_count=len(chain),
        session_id=first.session_id if first else None,
        agent_id=first.agent_id if first else None,
    )
