"""Headlights public verifier.

Consumes a chain export (JSON array or NDJSON) and re-runs the integrity
checks defined by `headlights_chain.Chain.verify`. Designed to be redistributable
on PyPI as `headlights-verify` and runnable as a console script.
"""

from headlights_verify.verify import (
    VerifyError,
    load_records,
    load_records_from_string,
    verify_file,
)

__version__ = "0.1.0a1"
__all__ = [
    "load_records",
    "load_records_from_string",
    "verify_file",
    "VerifyError",
]
