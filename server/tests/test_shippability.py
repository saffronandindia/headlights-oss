"""Tests for the shippability tasks.

- DB migration M-002: key_prefix 16→24 for existing rows
- Rate limiting: POST /v1/agents returns 429 after 10/hour
- app.create_app: rate_limit_enabled=False disables limits
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from headlights_server.app import create_app
from headlights_server.auth import hash_api_key
from headlights_server.config import Settings
from headlights_server.ratelimit import IPRateLimiter, _get_ip, _parse_limit
from headlights_server.storage import AgentRow, ApiKeyRow, SQLiteStore


# ── Helpers ──────────────────────────────────────────────────────────────


def _register(client: TestClient, name: str = "t") -> dict:
    import uuid
    r = client.post(
        "/v1/agents",
        json={
            "agent_name": f"{name}-{uuid.uuid4().hex[:4]}",
            "owner_email": "t@t.com",
            "purpose": "test",
        },
    )
    return r


# ── DB migration M-002 ────────────────────────────────────────────────────


def test_migration_m002_extends_short_prefixes(tmp_path: Path) -> None:
    """Short (16-char) key_prefix rows are rewritten to 24-char sentinel on startup."""
    db_path = str(tmp_path / "migrate.db")

    # Seed a database with a short-prefix row before instantiating SQLiteStore.
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY, agent_name TEXT NOT NULL,
            owner_email TEXT NOT NULL, purpose TEXT NOT NULL,
            agent_version TEXT NOT NULL, public_key_pem TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
            started_at TEXT NOT NULL, closed_at TEXT,
            session_hash TEXT, public_view INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            key_prefix TEXT PRIMARY KEY, key_hash TEXT NOT NULL,
            agent_id TEXT NOT NULL, created_at TEXT NOT NULL,
            revoked_at TEXT
        );
        INSERT INTO agents VALUES (
            'urn:headlights:agent:migrate-test-aabbccddee',
            'migrate-test', 'x@x.com', 'test', '1.0', NULL,
            '2024-01-01T00:00:00.000Z'
        );
        INSERT INTO api_keys VALUES (
            'hl_live_AAAAAAAA',
            'aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899',
            'urn:headlights:agent:migrate-test-aabbccddee',
            '2024-01-01T00:00:00.000Z',
            NULL
        );
    """)
    conn.commit()
    conn.close()

    # Opening SQLiteStore triggers _migrate — should rewrite the 16-char prefix.
    store = SQLiteStore(db_path)
    try:
        row = store.lookup_api_key("hl_live_AAAAAAAA")
        # Old 16-char prefix should no longer be findable
        assert row is None, "old 16-char prefix should not be findable after migration"

        # A sentinel row with 24-char key starting 'MIGRATED_' should exist
        import sqlite3 as _sqlite3
        with _sqlite3.connect(db_path) as c:
            cur = c.execute("SELECT key_prefix FROM api_keys")
            prefixes = [r[0] for r in cur.fetchall()]
        assert any(p.startswith("MIGRATED_") for p in prefixes), (
            f"expected a MIGRATED_ row, got: {prefixes}"
        )
        assert all(len(p) == 24 for p in prefixes), (
            f"all prefixes must be 24 chars after migration, got: {prefixes}"
        )
    finally:
        store.close()


def test_migration_m002_no_op_on_clean_db(tmp_path: Path) -> None:
    """A fresh DB (all 24-char prefixes) is unchanged after migration."""
    store = SQLiteStore(str(tmp_path / "clean.db"))
    try:
        from headlights_server.chains import utc_now
        now = utc_now()
        from headlights_server.storage import AgentRow, ApiKeyRow
        store.create_agent_with_key(
            AgentRow("urn:headlights:agent:clean-aabbccddee", "clean", "c@c.com",
                     "test", "1.0", None, now),
            ApiKeyRow("hl_live_AABBCCDDEEAABBCC", "x" * 64,
                      "urn:headlights:agent:clean-aabbccddee", now, None),
        )
        # Re-open to trigger migration again
        store.close()
        store2 = SQLiteStore(str(tmp_path / "clean.db"))
        row = store2.lookup_api_key("hl_live_AABBCCDDEEAABBCC")
        assert row is not None, "24-char prefix should be unchanged after migration"
        store2.close()
    finally:
        pass


# ── Rate limiter unit tests ───────────────────────────────────────────────


def test_parse_limit_hour() -> None:
    count, secs = _parse_limit("10/hour")
    assert count == 10
    assert secs == 3600.0


def test_parse_limit_minute() -> None:
    count, secs = _parse_limit("5/minute")
    assert count == 5
    assert secs == 60.0


def test_parse_limit_invalid_raises() -> None:
    with pytest.raises(ValueError):
        _parse_limit("no-slash")


def test_ipratelimiter_allows_under_limit() -> None:
    """Requests under the limit must not raise."""
    from unittest.mock import MagicMock
    limiter = IPRateLimiter(enabled=True)
    req = MagicMock()
    req.headers = {}
    req.client.host = "1.2.3.4"

    for _ in range(5):
        limiter.check(req, "10/hour", "test_ep")  # no exception


def test_ipratelimiter_raises_on_exceeded() -> None:
    """The (N+1)th request in a window must raise HTTP 429."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException

    limiter = IPRateLimiter(enabled=True)
    req = MagicMock()
    req.headers = {}
    req.client.host = "10.0.0.1"

    for _ in range(3):
        limiter.check(req, "3/hour", "test_ep")

    with pytest.raises(HTTPException) as exc_info:
        limiter.check(req, "3/hour", "test_ep")
    assert exc_info.value.status_code == 429


def test_ipratelimiter_disabled_never_raises() -> None:
    """Disabled limiter must never raise regardless of call count."""
    from unittest.mock import MagicMock
    limiter = IPRateLimiter(enabled=False)
    req = MagicMock()
    req.headers = {}
    req.client.host = "5.5.5.5"

    for _ in range(100):
        limiter.check(req, "1/hour", "test_ep")  # no exception


def test_ipratelimiter_reset_clears_state() -> None:
    """After reset(), counters are cleared and the limit restarts."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException

    limiter = IPRateLimiter(enabled=True)
    req = MagicMock()
    req.headers = {}
    req.client.host = "9.9.9.9"

    for _ in range(2):
        limiter.check(req, "2/hour", "ep")

    with pytest.raises(HTTPException):
        limiter.check(req, "2/hour", "ep")

    limiter.reset()
    # Should not raise after reset
    limiter.check(req, "2/hour", "ep")


def test_ipratelimiter_different_ips_are_independent() -> None:
    """Two different IPs have independent counters."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException

    limiter = IPRateLimiter(enabled=True)

    def make_req(ip: str):
        req = MagicMock()
        req.headers = {}
        req.client.host = ip
        return req

    req_a = make_req("1.1.1.1")
    req_b = make_req("2.2.2.2")

    for _ in range(2):
        limiter.check(req_a, "2/hour", "ep")

    with pytest.raises(HTTPException):
        limiter.check(req_a, "2/hour", "ep")

    # IP B is unaffected
    limiter.check(req_b, "2/hour", "ep")


# ── Rate limit integration: POST /v1/agents returns 429 ──────────────────


def test_registration_rate_limit_429_after_limit(tmp_path: Path) -> None:
    """POST /v1/agents returns 429 once the per-IP limit is exceeded."""
    store = SQLiteStore(str(tmp_path / "rl.db"))
    app = create_app(
        store=store,
        settings=Settings(),
        rate_limit_enabled=True,
        debug=False,
    )
    # Override the limiter with a tight 2/hour limit for this test
    from headlights_server.ratelimit import IPRateLimiter as _IPRateLimiter
    app.state.limiter = _IPRateLimiter(enabled=True)

    # Monkey-patch _REGISTER_RATE in agents module for this test
    import headlights_server.routes.agents as agents_mod
    original_rate = agents_mod._REGISTER_RATE
    agents_mod._REGISTER_RATE = "2/hour"
    try:
        with TestClient(app) as c:
            r1 = _register(c, "a")
            assert r1.status_code == 201
            r2 = _register(c, "b")
            assert r2.status_code == 201
            r3 = _register(c, "c")
            assert r3.status_code == 429
            assert "rate limit" in r3.json().get("detail", "").lower()
    finally:
        agents_mod._REGISTER_RATE = original_rate
        store.close()


def test_registration_rate_limit_disabled_in_test_client(
    client: TestClient,
) -> None:
    """The default test client (rate_limit_enabled=False) never hits 429."""
    import uuid
    for i in range(15):
        r = client.post(
            "/v1/agents",
            json={
                "agent_name": f"rl-test-{uuid.uuid4().hex[:4]}",
                "owner_email": "r@t.com",
                "purpose": "test",
            },
        )
        assert r.status_code == 201, f"request {i} unexpectedly got {r.status_code}"
