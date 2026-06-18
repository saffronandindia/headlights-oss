"""Tests for the NICE-TO-HAVE items from the server security review.

Issue 5  — key_prefix length increased to 24
Issue 14 — degraded-mode banner when agent row is missing
Issue 15 — global exception handler returns generic 500
Issue 16 — /docs and /openapi.json disabled by default (enabled with debug=True)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from headlights_server.app import create_app
from headlights_server.auth import generate_api_key, key_prefix
from headlights_server.storage import SQLiteStore


# ── Helpers ──────────────────────────────────────────────────────────────


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _register(client: TestClient) -> tuple[str, str]:
    import uuid
    r = client.post(
        "/v1/agents",
        json={
            "agent_name": f"ntf-{uuid.uuid4().hex[:6]}",
            "owner_email": "ntf@test.com",
            "purpose": "nice-to-have fixes test",
        },
    )
    assert r.status_code == 201
    body = r.json()
    return body["agent_id"], body["api_key"]


# ── Issue 5: key_prefix length ───────────────────────────────────────────


def test_key_prefix_length_is_24() -> None:
    """key_prefix must return 24 characters by default (up from 16)."""
    key = generate_api_key("hl_live_")
    prefix = key_prefix(key)
    assert len(prefix) == 24, f"expected 24 chars, got {len(prefix)}: {prefix!r}"


def test_key_prefix_starts_with_fixed_portion() -> None:
    """The first 8 chars are always the fixed prefix; chars 9-24 are payload."""
    key = generate_api_key("hl_live_")
    prefix = key_prefix(key)
    assert prefix.startswith("hl_live_")
    # The remaining 16 chars are base64url payload — at least some variation
    payload_part = prefix[8:]
    assert len(payload_part) == 16


def test_registered_api_key_has_24_char_prefix_in_db(
    client: TestClient, store: SQLiteStore
) -> None:
    """The key_prefix stored in api_keys must be 24 characters."""
    _agent_id, api_key = _register(client)
    stored_prefix = key_prefix(api_key)
    row = store.lookup_api_key(stored_prefix)
    assert row is not None, "key not found in DB at 24-char prefix"
    assert len(row.key_prefix) == 24


# ── Issue 14: Degraded-mode banner on missing agent ──────────────────────


def test_trace_shows_degraded_banner_when_agent_deleted(
    client: TestClient, store: SQLiteStore
) -> None:
    """When the agent row is deleted after publishing, the trace renders a degraded banner."""
    agent_id, key = _register(client)

    # Open, append, close, publish
    sid_resp = client.post(
        f"/v1/agents/{agent_id}/sessions",
        json={"trust_level": "L1"},
        headers=_auth(key),
    )
    assert sid_resp.status_code == 201
    sid = sid_resp.json()["session_id"]

    client.post(
        f"/v1/agents/{agent_id}/actions",
        json={
            "session_id": sid,
            "action_type": "tool_call",
            "action_detail": {"tool_name": "x", "parameters_hash": "h"},
            "outcome": "success",
            "trust_level": "L1",
        },
        headers=_auth(key),
    )
    client.post(f"/v1/agents/{agent_id}/sessions/{sid}/close", headers=_auth(key))
    client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key),
    )

    # Delete the agent row directly (simulates a hard delete).
    # Must disable FK enforcement for the duration because sessions.agent_id
    # references agents.agent_id — in production this would be a hard delete
    # triggered by a GDPR erasure request.
    with store._lock:  # noqa: SLF001
        cur = store._conn.cursor()
        try:
            cur.execute("PRAGMA foreign_keys = OFF")
            cur.execute("DELETE FROM api_keys WHERE agent_id = ?", (agent_id,))
            cur.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
            store._conn.commit()
            cur.execute("PRAGMA foreign_keys = ON")
        finally:
            cur.close()

    # Trace must still render (200), not 500 or 404
    r = client.get(f"/v1/sessions/{sid}/trace")
    assert r.status_code == 200
    body = r.text
    # Degraded banner present
    assert "Degraded mode" in body or "degraded" in body.lower()
    # agent_id used as display name (no AttributeError crash)
    assert agent_id in body
    # Chain was closed and intact — must still show CHAIN INTACT badge
    assert "CHAIN INTACT" in body


def test_trace_shows_degraded_badge_still_shows_open_on_open_session(
    client: TestClient, store: SQLiteStore
) -> None:
    """Open session + deleted agent → OPEN SESSION badge, degraded banner."""
    agent_id, key = _register(client)

    sid_resp = client.post(
        f"/v1/agents/{agent_id}/sessions",
        json={"trust_level": "L1"},
        headers=_auth(key),
    )
    assert sid_resp.status_code == 201
    sid = sid_resp.json()["session_id"]

    client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key),
    )

    # Delete the agent row (FK off for the same reason as above)
    with store._lock:  # noqa: SLF001
        cur = store._conn.cursor()
        try:
            cur.execute("PRAGMA foreign_keys = OFF")
            cur.execute("DELETE FROM api_keys WHERE agent_id = ?", (agent_id,))
            cur.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
            store._conn.commit()
            cur.execute("PRAGMA foreign_keys = ON")
        finally:
            cur.close()

    r = client.get(f"/v1/sessions/{sid}/trace")
    assert r.status_code == 200
    assert "OPEN SESSION" in r.text
    assert "CHAIN INTACT" not in r.text


# ── Issue 15: Global exception handler ───────────────────────────────────


def test_global_exception_handler_returns_generic_500(tmp_path) -> None:
    """An unhandled exception in a route must return 500 with generic detail."""
    from headlights_server.config import Settings
    from headlights_server.storage import SQLiteStore

    store = SQLiteStore(str(tmp_path / "test.db"))
    test_app = create_app(store=store, settings=Settings(), debug=True)

    # Inject a route that raises an unhandled RuntimeError
    from fastapi import APIRouter
    boom_router = APIRouter()

    @boom_router.get("/test-boom")
    def boom():
        raise RuntimeError("INTERNAL_SECRET_DETAIL_abc123")

    test_app.include_router(boom_router)

    with TestClient(test_app, raise_server_exceptions=False) as c:
        r = c.get("/test-boom")
    assert r.status_code == 500
    body = r.json()
    # Generic message — no internal detail leaked
    assert "INTERNAL_SECRET" not in body.get("detail", "")
    assert "internal server error" in body.get("detail", "").lower()


# ── Issue 16: /docs and /openapi.json disabled by default ────────────────


def test_docs_disabled_by_default(client: TestClient) -> None:
    """/docs must return 404 on a default (non-debug) app."""
    r = client.get("/docs")
    assert r.status_code == 404


def test_openapi_disabled_by_default(client: TestClient) -> None:
    """/openapi.json must return 404 on a default app."""
    r = client.get("/openapi.json")
    assert r.status_code == 404


def test_redoc_disabled_by_default(client: TestClient) -> None:
    """/redoc must return 404 on a default app."""
    r = client.get("/redoc")
    assert r.status_code == 404


def test_docs_enabled_in_debug_mode(tmp_path) -> None:
    """/docs must return 200 when debug=True is passed to create_app."""
    from headlights_server.config import Settings

    store = SQLiteStore(str(tmp_path / "debug.db"))
    debug_app = create_app(store=store, settings=Settings(), debug=True)
    with TestClient(debug_app) as c:
        r = c.get("/docs")
    assert r.status_code == 200


def test_openapi_enabled_in_debug_mode(tmp_path) -> None:
    """/openapi.json must be accessible when debug=True."""
    from headlights_server.config import Settings

    store = SQLiteStore(str(tmp_path / "debug2.db"))
    debug_app = create_app(store=store, settings=Settings(), debug=True)
    with TestClient(debug_app) as c:
        r = c.get("/openapi.json")
    assert r.status_code == 200
    assert "openapi" in r.json()
