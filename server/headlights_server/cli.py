"""Console-script entry point: `headlights-server` to launch uvicorn."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="headlights-server",
        description="Launch the Headlights FastAPI backend.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true", help="enable hot reload (dev only)")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. `pip install headlights-server` should pull it in.", file=sys.stderr)
        return 1

    uvicorn.run(
        "headlights_server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
