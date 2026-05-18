"""Test fixtures for the server."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from headlights_server.app import create_app
from headlights_server.config import Settings
from headlights_server.storage import SQLiteStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SQLiteStore]:
    db_path = tmp_path / "test.db"
    store = SQLiteStore(str(db_path))
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def settings() -> Settings:
    return Settings(free_tier_session_cap=10_000)


@pytest.fixture
def client(store: SQLiteStore, settings: Settings) -> TestClient:
    app = create_app(store=store, settings=settings)
    return TestClient(app)


@pytest.fixture
def registered_agent(client: TestClient) -> tuple[str, str]:
    """Register an agent, return (agent_id, api_key)."""
    response = client.post(
        "/v1/agents",
        json={
            "agent_name": "test-agent",
            "owner_email": "test@example.com",
            "purpose": "fixtures",
            "agent_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["agent_id"], body["api_key"]
