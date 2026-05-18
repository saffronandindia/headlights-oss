"""Integration tests for HostedClient against the in-process FastAPI server.

Uses FastAPI's TestClient (an httpx.Client subclass) so the SDK's HTTP calls
go straight through the ASGI app without binding to a network port.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from headlights_chain import Chain
from headlights_sdk import HostedClient, HostedClientError
from headlights_server.app import create_app
from headlights_server.config import Settings
from headlights_server.storage import SQLiteStore


@pytest.fixture
def server(tmp_path: Path) -> Iterator[TestClient]:
    """A TestClient bound to a fresh FastAPI app + SQLite DB."""
    db_path = tmp_path / "hosted_test.db"
    store = SQLiteStore(str(db_path))
    app = create_app(store=store, settings=Settings(free_tier_session_cap=10_000))
    with TestClient(app, base_url="http://testserver") as c:
        yield c
    store.close()


def _register(server: TestClient, name: str = "demo") -> dict:
    response = server.post(
        "/v1/agents",
        json={
            "agent_name": name,
            "owner_email": "e@example.com",
            "purpose": "tests",
            "agent_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _build_hosted_client(server: TestClient, name: str = "demo") -> HostedClient:
    """Build a HostedClient whose HTTP client IS the test app's TestClient.

    TestClient subclasses httpx.Client, so it slots in as the http_client.
    """
    reg = _register(server, name)
    # Construct a new TestClient on the same app for the SDK to use, so we
    # don't accidentally share state with the fixture client.
    sdk_http = TestClient(
        server.app,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {reg['api_key']}"},
    )
    return HostedClient(
        api_url="http://testserver",
        api_key=reg["api_key"],
        agent_id=reg["agent_id"],
        agent_version="1.0.0",
        http_client=sdk_http,
    )


# ── Registration ────────────────────────────────────────────────────────


def test_register_returns_ready_client(server: TestClient) -> None:
    body = _register(server, "test-agent")
    assert body["agent_id"].startswith("urn:headlights:agent:test-agent-")
    assert body["api_key"].startswith("hl_live_")


# ── Decorator + chain integrity ─────────────────────────────────────────


def test_decorator_posts_records_to_server(server: TestClient) -> None:
    client = _build_hosted_client(server)

    @client.record
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5
    assert add(10, 20) == 30
    client.close()

    records = client.get_conduct(session_id=client.session_id)
    # genesis + tool_call + tool_response + tool_call + tool_response + close
    assert len(records) == 6
    chain = Chain.from_records(records)
    assert chain.verify().is_intact


def test_decorator_records_errors(server: TestClient) -> None:
    client = _build_hosted_client(server, "boom-test")

    @client.record
    def boom() -> None:
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        boom()

    client.close()
    records = client.get_conduct(session_id=client.session_id)
    # genesis + tool_call + error + close
    assert len(records) == 4
    assert records[2]["action_type"] == "error"
    assert records[2]["action_detail"]["error_message"] == "kaboom"
    chain = Chain.from_records(records)
    assert chain.verify().is_intact


def test_explicit_session_context_manager(server: TestClient) -> None:
    client = _build_hosted_client(server, "ctx-test")

    @client.record
    def f() -> int:
        return 1

    with client.session(genesis_detail={"config_hash": "sha256:abc"}):
        f()
        f()
        sid = client.session_id

    records = client.get_conduct(session_id=sid)
    chain = Chain.from_records(records)
    assert chain.verify().is_intact
    assert records[0]["action_detail"].get("config_hash") == "sha256:abc"
    assert records[-1]["action_detail"]["event"] == "session_end"


def test_unauthenticated_call_fails(server: TestClient) -> None:
    bad_http = TestClient(
        server.app,
        base_url="http://testserver",
        headers={"Authorization": "Bearer hl_live_garbage"},
    )
    unauth = HostedClient(
        api_url="http://testserver",
        api_key="hl_live_garbage",
        agent_id="urn:headlights:agent:does-not-exist",
        agent_version="1.0.0",
        http_client=bad_http,
    )

    @unauth.record
    def f() -> int:
        return 1

    with pytest.raises(HostedClientError) as exc:
        f()
    assert exc.value.status_code in (401, 403)


def test_get_conduct_filters_by_time(server: TestClient) -> None:
    client = _build_hosted_client(server, "filter-test")

    @client.record
    def f() -> int:
        return 1

    f()
    f()
    client.close()

    records = client.get_conduct(since="2099-01-01T00:00:00Z")
    assert records == []


def test_close_is_idempotent(server: TestClient) -> None:
    client = _build_hosted_client(server, "idem-test")

    @client.record
    def f() -> int:
        return 1

    f()
    client.close()
    client.close()  # no-op
