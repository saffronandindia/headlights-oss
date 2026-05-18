"""Allow `python -m headlights_verify ...` invocation."""

from __future__ import annotations

import sys

from headlights_verify.cli import main


if __name__ == "__main__":
    sys.exit(main())
