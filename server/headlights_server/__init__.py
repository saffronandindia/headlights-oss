"""Headlights server — FastAPI backend for the four MVP endpoints.

  POST /v1/agents                              register an agent
  POST /v1/agents/{id}/sessions                open a session
  POST /v1/agents/{id}/actions                 append an action
  POST /v1/agents/{id}/sessions/{sid}/close    close a session
  GET  /v1/agents/{id}/conduct                 list records for the agent
  GET  /v1/agents/{id}/sessions/{sid}/conduct  list records for one session

Local-only storage at v1 (SQLite). Postgres adapter is a swap-out via the
`Store` interface.
"""

# __version__ MUST be defined before importing app, because app.py imports it.
__version__ = "0.1.0a1"

from headlights_server.app import create_app  # noqa: E402

__all__ = ["create_app"]
