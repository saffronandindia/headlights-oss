"""Command-line interface for headlights-verify.

Usage:
    headlights-verify <chain-export> [--public-key key.pem] [--strict] [--quiet]

Exit codes:
    0  chain is intact (with --strict: intact AND closed AND signatures verified)
    1  chain is broken (tampered or signature failure); with --strict, also an
       unsigned or open chain
    2  input error (file not found, bad JSON, etc.)

A green check is printed only for a signed, closed, fully-verified chain. A
weaker result (unsigned, or open and therefore truncatable) prints a "~" with
explicit warnings, because hash-linking alone is not tamper-evidence.
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
_YELLOW = "\033[33m"
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
        help=(
            "Suppress output; rely on the exit code. Exit 0 indicates structural "
            "hash-chain integrity; it does NOT imply signature verification unless "
            "--public-key is given and the chain is signed and closed. Combine with "
            "--strict to require the full guarantee."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Treat a chain as a pass only when it is intact AND closed AND its "
            "signatures were verified. Anything weaker exits 1. Use to gate CI."
        ),
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
    full_guarantee = result.is_intact and result.is_closed and result.signatures_checked

    # A key was supplied but matched nothing: flag it regardless of verbosity.
    if args.public_key is not None and not result.signatures_checked:
        print(
            "warning: --public-key was provided but no records are signed; "
            "the key was not used.",
            file=sys.stderr,
        )

    if args.quiet:
        if not result.is_intact:
            return 1
        return 1 if (args.strict and not full_guarantee) else 0

    if not result.is_intact:
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

    if full_guarantee:
        print(_coloured("✓ chain intact (signed + closed, fully verified)", _GREEN + _BOLD, use_color=use_color), file=out)
    else:
        print(_coloured("~ chain intact (WEAK GUARANTEE - see warnings below)", _YELLOW + _BOLD, use_color=use_color), file=out)
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
    if not result.signatures_checked:
        print(
            _coloured(
                "  ! signatures NOT verified (hash-chain only). "
                "Pass --public-key <key.pem> to verify cryptographic signatures.",
                _YELLOW,
                use_color=use_color,
            ),
            file=out,
        )
    if not result.is_closed:
        print(
            _coloured(
                "  ! chain is OPEN (no session_end); the tail may have been truncated. "
                "A closed chain is required for full tamper-evidence.",
                _YELLOW,
                use_color=use_color,
            ),
            file=out,
        )
    return 1 if (args.strict and not full_guarantee) else 0


if __name__ == "__main__":
    sys.exit(main())
