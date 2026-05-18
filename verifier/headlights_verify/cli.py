"""Command-line interface for headlights-verify.

Usage:
    headlights-verify <chain-export> [--public-key key.pem] [--quiet]

Exit codes:
    0  chain is intact
    1  chain is broken (tampered or signature failure)
    2  input error (file not found, bad JSON, etc.)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import IO

from headlights_verify import __version__
from headlights_verify.verify import VerifyError, verify_file


# ANSI color codes — disabled automatically when stdout is not a TTY.
_GREEN = "\033[32m"
_RED = "\033[31m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _coloured(text: str, code: str, *, use_color: bool) -> str:
    return f"{code}{text}{_RESET}" if use_color else text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="headlights-verify",
        description=(
            "Verify a Headlights AI agent conduct chain. "
            "Implements draft-sharif-agent-audit-trail-00 verification."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to a chain export (JSON array or NDJSON).",
    )
    parser.add_argument(
        "--public-key",
        type=Path,
        default=None,
        metavar="PEM",
        help="Path to a PEM-encoded ECDSA P-256 public key for signature verification.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output; rely on exit code.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable coloured output.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"headlights-verify {__version__}",
    )
    return parser


def main(argv: list[str] | None = None, *, stdout: IO[str] | None = None) -> int:
    """Entry point. Returns the exit code; the console_scripts wrapper calls
    sys.exit on the return value."""
    parser = build_parser()
    args = parser.parse_args(argv)

    out = stdout if stdout is not None else sys.stdout
    use_color = (not args.no_color) and out.isatty()

    public_key_pem: bytes | None = None
    if args.public_key is not None:
        try:
            public_key_pem = args.public_key.read_bytes()
        except OSError as e:
            print(f"error: cannot read public key {args.public_key}: {e}", file=sys.stderr)
            return 2

    try:
        outcome = verify_file(args.path, public_key_pem=public_key_pem)
    except VerifyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    result = outcome.result
    if args.quiet:
        return 0 if result.is_intact else 1

    if result.is_intact:
        print(_coloured("✓ chain intact", _GREEN + _BOLD, use_color=use_color), file=out)
        print(
            _coloured(
                f"  {outcome.record_count} records, "
                f"session {outcome.session_id}, "
                f"agent {outcome.agent_id}",
                _DIM,
                use_color=use_color,
            ),
            file=out,
        )
        return 0

    print(_coloured("✗ chain BROKEN", _RED + _BOLD, use_color=use_color), file=out)
    print(
        _coloured(
            f"  first failing position: {result.failed_position} of {outcome.record_count}",
            _RED,
            use_color=use_color,
        ),
        file=out,
    )
    print(_coloured(f"  reason: {result.reason}", _RED, use_color=use_color), file=out)
    return 1


if __name__ == "__main__":
    sys.exit(main())
