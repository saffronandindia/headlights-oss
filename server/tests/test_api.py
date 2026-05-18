"""Integration tests for the FastAPI app."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from headlights_chain import Chain
from headlights_server.storage import SQLiteStore


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# ── Health ──────────────────────────────────────────────────────────────


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── Agent registration ──────────────────────────────────────────────────


def test_register_agent_returns_id_and_key(client: TestClient) -> None:
    response = client.post(
        "/v1/agents",
        json={
            "agent_name": "loan-analyser",
            "owner_email": "test@example.com",
            "purpose": "registration smoke test",
            "agent_version": "1.0.0",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["agent_id"].startswith("urn:headlights:agent:loan-analyser-")
    assert body["api_key"].startswith("hl_live_")
    assert "created_at" in body


def test_register_agent_rejects_empty_name(client: TestClient) -> None:
    response = client.post(
        "/v1/agents",
        json={
            "agent_name": "",
            "owner_email": "test@example.com",
            "purpose": "x",
        },
    )
    assert response.status_code == 422


# ── Auth ────────────────────────────────────────────────────────────────


def test_missing_auth_header_is_rejected(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, _ = registered_agent
    response = client.post(f"/v1/agents/{agent_id}/sessions", json={})
    assert response.status_code == 401


def test_invalid_api_key_is_rejected(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, _ = registered_agent
    response = client.post(
        f"/v1/agents/{agent_id}/sessions",
        json={},
        headers=_auth("hl_live_not_a_real_key_value"),
    )
    assert response.status_code == 401


def test_key_for_one_agent_cannot_access_another(client: TestClient) -> None:
    r1 = client.post(
        "/v1/agents",
        json={"agent_name": "a1", "owner_email": "a@b.com", "purpose": "x"},
    )
    r2 = client.post(
        "/v1/agents",
        json={"agent_name": "a2", "owner_email": "a@b.com", "purpose": "x"},
    )
    agent_1 = r1.json()["agent_id"]
    key_2 = r2.json()["api_key"]
    response = client.post(
        f"/v1/agents/{agent_1}/sessions", json={}, headers=_auth(key_2)
    )
    assert response.status_code == 403


def test_malformed_authorization_header(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, _ = registered_agent
    response = client.post(
        f"/v1/agents/{agent_id}/sessions",
        json={},
        headers={"Authorization": "not-bearer-format"},
    )
    assert response.status_code == 401


# ── Sessions ────────────────────────────────────────────────────────────


def test_open_session_writes_genesis(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    response = client.post(
        f"/v1/agents/{agent_id}/sessions",
        json={"genesis_detail": {"config_hash": "sha256:abc"}, "trust_level": "L2"},
        headers=_auth(key),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["genesis_position"] == 0
    assert len(body["session_id"]) == 36  # UUID
    assert len(body["genesis_record_hash"]) == 64


def test_close_session_emits_session_hash(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    s = client.post(
        f"/v1/agents/{agent_id}/sessions", json={}, headers=_auth(key)
    ).json()
    sid = s["session_id"]
    # add a couple of records
    for i in range(2):
        client.post(
            f"/v1/agents/{agent_id}/actions",
            json={
                "session_id": sid,
                "action_type": "tool_call",
                "action_detail": {"tool_name": f"t{i}", "parameters_hash": "h"},
                "outcome": "success",
                "trust_level": "L1",
            },
            headers=_auth(key),
        )
    close_resp = client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/close", headers=_auth(key)
    )
    assert close_resp.status_code == 200
    body = close_resp.json()
    assert body["record_count"] == 4  # genesis + 2 actions + close
    assert len(body["session_hash"]) == 64


def test_close_session_twice_is_409(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    s = client.post(
        f"/v1/agents/{agent_id}/sessions", json={}, headers=_auth(key)
    ).json()
    sid = s["session_id"]
    client.post(f"/v1/agents/{agent_id}/sessions/{sid}/close", headers=_auth(key))
    response = client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/close", headers=_auth(key)
    )
    assert response.status_code == 409


# ── Actions ─────────────────────────────────────────────────────────────


def test_action_auto_opens_session(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    response = client.post(
        f"/v1/agents/{agent_id}/actions",
        json={
            "action_type": "decision",
            "action_detail": {"decision_type": "approve"},
            "outcome": "success",
            "trust_level": "L1",
        },
        headers=_auth(key),
    )
    assert response.status_code == 201
    body = response.json()
    # genesis at position 0, action at position 1
    assert body["position"] == 1
    assert len(body["record_id"]) == 36
    assert len(body["record_hash"]) == 64


def test_three_actions_chain_correctly(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    positions = []
    for i in range(3):
        response = client.post(
            f"/v1/agents/{agent_id}/actions",
            json={
                "action_type": "tool_call",
                "action_detail": {"tool_name": f"t{i}", "parameters_hash": "h"},
                "outcome": "success",
                "trust_level": "L1",
            },
            headers=_auth(key),
        )
        assert response.status_code == 201
        positions.append(response.json()["position"])
    assert positions == [1, 2, 3]


def test_action_with_optional_fields(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    response = client.post(
        f"/v1/agents/{agent_id}/actions",
        json={
            "action_type": "decision",
            "action_detail": {"decision_type": "x"},
            "outcome": "success",
            "trust_level": "L2",
            "risk_score": 0.42,
            "latency_ms": 120,
            "jurisdiction": "AU",
        },
        headers=_auth(key),
    )
    assert response.status_code == 201
    # Read back and check the optional fields landed in the record
    conduct = client.get(
        f"/v1/agents/{agent_id}/conduct", headers=_auth(key)
    ).json()
    last = conduct["records"][-1]
    assert last["risk_score"] == 0.42
    assert last["latency_ms"] == 120
    assert last["jurisdiction"] == "AU"


def test_action_to_unknown_session_is_404(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    response = client.post(
        f"/v1/agents/{agent_id}/actions",
        json={
            "session_id": "00000000-0000-4000-8000-000000000000",
            "action_type": "tool_call",
            "action_detail": {"tool_name": "x", "parameters_hash": "h"},
            "outcome": "success",
            "trust_level": "L1",
        },
        headers=_auth(key),
    )
    assert response.status_code == 404


def test_action_to_closed_session_is_409(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    s = client.post(
        f"/v1/agents/{agent_id}/sessions", json={}, headers=_auth(key)
    ).json()
    sid = s["session_id"]
    client.post(f"/v1/agents/{agent_id}/sessions/{sid}/close", headers=_auth(key))
    response = client.post(
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
    assert response.status_code == 409


# ── Conduct retrieval ──────────────────────────────────────────────────


def test_get_conduct_returns_chain_in_order(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    for i in range(3):
        client.post(
            f"/v1/agents/{agent_id}/actions",
            json={
                "action_type": "tool_call",
                "action_detail": {"tool_name": f"t{i}", "parameters_hash": "h"},
                "outcome": "success",
                "trust_level": "L1",
            },
            headers=_auth(key),
        )

    response = client.get(f"/v1/agents/{agent_id}/conduct", headers=_auth(key))
    assert response.status_code == 200
    body = response.json()
    assert body["record_count"] == 4  # genesis + 3
    # Records should round-trip through Chain.from_records + verify
    chain = Chain.from_records(body["records"])
    assert chain.verify().is_intact


def test_get_session_conduct(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    s = client.post(
        f"/v1/agents/{agent_id}/sessions", json={}, headers=_auth(key)
    ).json()
    sid = s["session_id"]
    for i in range(2):
        client.post(
            f"/v1/agents/{agent_id}/actions",
            json={
                "session_id": sid,
                "action_type": "tool_call",
                "action_detail": {"tool_name": f"t{i}", "parameters_hash": "h"},
                "outcome": "success",
                "trust_level": "L1",
            },
            headers=_auth(key),
        )

    response = client.get(
        f"/v1/agents/{agent_id}/sessions/{sid}/conduct", headers=_auth(key)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["record_count"] == 3
    chain = Chain.from_records(body["records"])
    assert chain.verify().is_intact


def test_get_conduct_filters_by_time(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    for _ in range(3):
        client.post(
            f"/v1/agents/{agent_id}/actions",
            json={
                "action_type": "tool_call",
                "action_detail": {"tool_name": "t", "parameters_hash": "h"},
                "outcome": "success",
                "trust_level": "L1",
            },
            headers=_auth(key),
        )
    # since the far future
    response = client.get(
        f"/v1/agents/{agent_id}/conduct",
        headers=_auth(key),
        params={"since": "2099-01-01T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["record_count"] == 0


# ── End-to-end tamper detection through the API ─────────────────────────


def test_db_tamper_is_caught_by_verifier(
    client: TestClient,
    registered_agent: tuple[str, str],
    store: SQLiteStore,
) -> None:
    """The most important integration test: mutate a record in the DB directly
    (simulating a malicious DBA) and confirm Chain.from_records().verify()
    catches it."""
    agent_id, key = registered_agent
    for i in range(3):
        client.post(
            f"/v1/agents/{agent_id}/actions",
            json={
                "action_type": "tool_call",
                "action_detail": {"tool_name": f"t{i}", "parameters_hash": "h"},
                "outcome": "success",
                "trust_level": "L1",
            },
            headers=_auth(key),
        )

    # Read original records
    conduct = client.get(f"/v1/agents/{agent_id}/conduct", headers=_auth(key)).json()
    assert Chain.from_records(conduct["records"]).verify().is_intact

    # Tamper directly in the DB — modify the action_detail of position 2 in
    # that session.
    target = conduct["records"][2]
    session_id = target["session_id"]
    tampered = dict(target)
    tampered["action_detail"] = {"tool_name": "tampered", "parameters_hash": "h"}
    # Update the canonical_json row in SQLite.
    with store._cursor() as cur:  # noqa: SLF001 — test access to internals
        cur.execute(
            "UPDATE records SET canonical_json = ? WHERE session_id = ? AND position = 2",
            (json.dumps(tampered), session_id),
        )

    # Re-fetch and verify
    new_conduct = client.get(
        f"/v1/agents/{agent_id}/conduct", headers=_auth(key)
    ).json()
    result = Chain.from_records(new_conduct["records"]).verify()
    assert not result.is_intact
    assert result.failed_position == 3  # the record AFTER the tampered one
