"""Tests for the public trace viewer + publish endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from headlights_chain import Chain


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _session_with_actions(
    client: TestClient, agent_id: str, api_key: str, n_actions: int = 3
) -> str:
    """Open a session and append n_actions. Returns session_id."""
    open_resp = client.post(
        f"/v1/agents/{agent_id}/sessions",
        json={"trust_level": "L1"},
        headers=_auth(api_key),
    )
    assert open_resp.status_code == 201
    session_id = open_resp.json()["session_id"]
    for i in range(n_actions):
        r = client.post(
            f"/v1/agents/{agent_id}/actions",
            json={
                "session_id": session_id,
                "action_type": "tool_call",
                "action_detail": {"tool_name": f"step_{i}", "parameters_hash": "h"},
                "outcome": "success",
                "trust_level": "L1",
            },
            headers=_auth(api_key),
        )
        assert r.status_code == 201
    return session_id


# ── Publish endpoint ────────────────────────────────────────────────────


def test_publish_requires_auth(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    sid = _session_with_actions(client, agent_id, key, 1)
    r = client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
    )
    assert r.status_code == 401


def test_publish_other_agents_session_is_forbidden(client: TestClient) -> None:
    """A key for agent A cannot publish agent B's session."""
    # Two agents
    r1 = client.post(
        "/v1/agents",
        json={"agent_name": "owner", "owner_email": "x@y.com", "purpose": "x"},
    )
    r2 = client.post(
        "/v1/agents",
        json={"agent_name": "intruder", "owner_email": "x@y.com", "purpose": "x"},
    )
    agent_a, key_a = r1.json()["agent_id"], r1.json()["api_key"]
    key_b = r2.json()["api_key"]

    sid = _session_with_actions(client, agent_a, key_a, 1)

    r = client.post(
        f"/v1/agents/{agent_a}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key_b),
    )
    assert r.status_code == 403


def test_publish_returns_trace_url(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    sid = _session_with_actions(client, agent_id, key, 2)
    r = client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid
    assert body["public"] is True
    assert body["trace_url"] == f"/v1/sessions/{sid}/trace"


def test_publish_unknown_session_is_404(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    r = client.post(
        f"/v1/agents/{agent_id}/sessions/00000000-0000-4000-8000-000000000000/publish",
        json={"public": True},
        headers=_auth(key),
    )
    assert r.status_code == 404


# ── Public trace (HTML) ─────────────────────────────────────────────────


def test_trace_html_404_when_unpublished(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    """Default-private sessions must not leak via the trace URL."""
    agent_id, key = registered_agent
    sid = _session_with_actions(client, agent_id, key, 2)
    r = client.get(f"/v1/sessions/{sid}/trace")
    assert r.status_code == 404


def test_trace_html_404_for_unknown_session(client: TestClient) -> None:
    """Unknown and unpublished return identical 404 (no enumeration oracle)."""
    r = client.get("/v1/sessions/00000000-0000-4000-8000-000000000000/trace")
    assert r.status_code == 404


def test_trace_html_200_after_publish(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    sid = _session_with_actions(client, agent_id, key, 2)
    client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key),
    )
    r = client.get(f"/v1/sessions/{sid}/trace")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # Branding signals
    assert "Headlights" in body
    assert sid in body
    # Verification badge
    assert "CHAIN INTACT" in body
    # Records rendered as cards
    assert "step_0" in body
    assert "step_1" in body
    # Download CTA present
    assert f"/v1/sessions/{sid}/trace.json" in body


def test_trace_html_reflects_unpublish(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    sid = _session_with_actions(client, agent_id, key, 1)

    # Publish, then unpublish
    client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key),
    )
    assert client.get(f"/v1/sessions/{sid}/trace").status_code == 200
    client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": False},
        headers=_auth(key),
    )
    assert client.get(f"/v1/sessions/{sid}/trace").status_code == 404


def test_trace_html_no_auth_header_works(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    """The public trace URL must work without any Authorization header."""
    agent_id, key = registered_agent
    sid = _session_with_actions(client, agent_id, key, 1)
    client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key),
    )
    # No headers at all
    r = client.get(f"/v1/sessions/{sid}/trace")
    assert r.status_code == 200


# ── Public trace (JSON download) ────────────────────────────────────────


def test_trace_json_404_when_unpublished(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    sid = _session_with_actions(client, agent_id, key, 1)
    r = client.get(f"/v1/sessions/{sid}/trace.json")
    assert r.status_code == 404


def test_trace_json_returns_canonical_records_after_publish(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    sid = _session_with_actions(client, agent_id, key, 3)
    client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key),
    )
    r = client.get(f"/v1/sessions/{sid}/trace.json")
    assert r.status_code == 200
    records = r.json()
    # 1 genesis + 3 actions
    assert len(records) == 4
    assert records[0]["action_type"] == "lifecycle"
    assert records[0]["action_detail"]["event"] == "session_start"
    # Sets up the email-as-demo loop: the downloaded JSON must validate
    # with the offline verifier.
    chain = Chain.from_records(records)
    result = chain.verify()
    assert result.is_intact, result.reason


def test_trace_json_has_attachment_filename(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    agent_id, key = registered_agent
    sid = _session_with_actions(client, agent_id, key, 1)
    client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key),
    )
    r = client.get(f"/v1/sessions/{sid}/trace.json")
    assert r.status_code == 200
    assert sid in r.headers.get("content-disposition", "")


# ── End-to-end: the email-as-demo loop ──────────────────────────────────


def test_end_to_end_email_demo_loop(
    client: TestClient, registered_agent: tuple[str, str]
) -> None:
    """The full path a prospect would walk:
    1. Marketing agent runs a session, records actions
    2. Owner publishes the session
    3. Prospect (unauthenticated) loads the HTML trace
    4. Prospect downloads the canonical JSON
    5. Prospect runs `headlights-verify` (here: Chain.verify) on the JSON
    6. The result is GREEN
    """
    agent_id, key = registered_agent

    # 1. Agent does work
    sid = _session_with_actions(client, agent_id, key, 4)
    client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/close",
        headers=_auth(key),
    )

    # 2. Owner publishes
    pub = client.post(
        f"/v1/agents/{agent_id}/sessions/{sid}/publish",
        json={"public": True},
        headers=_auth(key),
    )
    trace_url = pub.json()["trace_url"]

    # 3. Prospect (no auth) loads the HTML page
    html_resp = client.get(trace_url)
    assert html_resp.status_code == 200
    assert "CHAIN INTACT" in html_resp.text

    # 4. Prospect downloads the JSON
    json_resp = client.get(trace_url + ".json")
    assert json_resp.status_code == 200
    records = json_resp.json()

    # 5 + 6. The downloaded JSON validates offline
    chain = Chain.from_records(records)
    result = chain.verify()
    assert result.is_intact
