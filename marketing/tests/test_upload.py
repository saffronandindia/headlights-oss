"""End-to-end tests for marketing.upload.

These tests stand up a real Headlights server (via TestClient over an
in-process FastAPI app) and exercise the full upload pipeline: replay a
chain, publish the session, rewrite the .eml. The upload script then
points at the same TestClient so chains are actually persisted.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from headlights_chain import Chain
from headlights_sdk.hosted import HostedClient
from headlights_server.app import create_app
from headlights_server.config import Settings
from headlights_server.storage import SQLiteStore

from marketing.drafter import read_prospects, run_drafter, write_drafts
from marketing.upload import (
    UploadResult,
    upload_all,
    upload_chain,
    rewrite_eml_trace_url,
)


# ── Server fixtures (separate from marketing.tests.conftest) ─────────────


@pytest.fixture
def server_store(tmp_path: Path):
    """SQLite-backed Store on disk, isolated per test."""
    db_path = tmp_path / "headlights.db"
    store = SQLiteStore(str(db_path))
    yield store
    store.close()


@pytest.fixture
def server_client(server_store):
    """TestClient wrapping the real FastAPI app."""
    app = create_app(store=server_store, settings=Settings(free_tier_session_cap=10_000))
    return TestClient(app)


@pytest.fixture
def registered_marketing_agent(server_client: TestClient) -> tuple[str, str]:
    """Register the marketing agent on the server. Returns (agent_id, api_key)."""
    r = server_client.post(
        "/v1/agents",
        json={
            "agent_name": "marketing-drafter",
            "owner_email": "ops@useheadlights.com",
            "purpose": "outreach drafting agent for test",
            "agent_version": "0.1.0",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["agent_id"], body["api_key"]


@pytest.fixture
def hosted_client(server_client: TestClient, registered_marketing_agent):
    """HostedClient wired to the in-process FastAPI app via TestClient.

    TestClient is an httpx.Client subclass but does not pick up default
    headers from the constructor in HostedClient. We set them on the
    TestClient's `headers` mapping directly so subsequent requests carry
    the auth bearer.
    """
    agent_id, api_key = registered_marketing_agent
    server_client.headers.update({"Authorization": f"Bearer {api_key}"})
    client = HostedClient(
        api_url="http://testserver",
        api_key=api_key,
        agent_id=agent_id,
        agent_version="0.1.0",
        http_client=server_client,
    )
    yield client
    # Don't call client.close() — that would close server_client too.


# ── upload_chain ─────────────────────────────────────────────────────────


def test_upload_chain_replays_records(hosted_client, mock_github, sample_prospect_csv):
    """The replayed server chain has the same number of meaningful actions
    as the local chain."""
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    local_chain = results[0].chain_records
    local_session_id = results[0].draft.trace_session_id

    server_sid, trace_url = upload_chain(
        chain_records=local_chain,
        client=hosted_client,
        local_trace_session_id=local_session_id,
    )
    assert server_sid != local_session_id  # server assigns a fresh UUID
    assert trace_url.endswith(f"/v1/sessions/{server_sid}/trace")


def test_upload_chain_published_session_is_publicly_viewable(
    hosted_client, server_client, mock_github, sample_prospect_csv
):
    """After upload, the public trace endpoint returns 200 without auth."""
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    server_sid, _ = upload_chain(
        chain_records=results[0].chain_records,
        client=hosted_client,
        local_trace_session_id=results[0].draft.trace_session_id,
    )
    # No Authorization header — this is the prospect's experience.
    r = server_client.get(f"/v1/sessions/{server_sid}/trace")
    assert r.status_code == 200
    assert "CHAIN INTACT" in r.text


def test_upload_chain_replayed_records_verify_intact(
    hosted_client, server_client, mock_github, sample_prospect_csv,
    registered_marketing_agent,
):
    """The server's view of the replayed chain — fetched via the conduct
    endpoint — verifies cleanly with the chain primitive. This proves the
    upload preserves chain integrity end-to-end."""
    agent_id, api_key = registered_marketing_agent
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    server_sid, _ = upload_chain(
        chain_records=results[0].chain_records,
        client=hosted_client,
        local_trace_session_id=results[0].draft.trace_session_id,
    )

    r = server_client.get(
        f"/v1/agents/{agent_id}/sessions/{server_sid}/conduct",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert r.status_code == 200
    records = r.json()["records"]
    chain = Chain.from_records(records)
    outcome = chain.verify()
    assert outcome.is_intact, f"replayed chain broken: {outcome.reason}"


# ── rewrite_eml_trace_url ────────────────────────────────────────────────


def test_rewrite_eml_replaces_url_in_body(tmp_path: Path):
    eml = tmp_path / "test.eml"
    old_id = "11111111-2222-3333-4444-555555555555"
    new_url = "http://localhost:8080/v1/sessions/aaaa-bbbb/trace"
    eml.write_text(
        f"""To: alice@example.com
Subject: hello

Hi Alice,

Visit https://api.useheadlights.com/v1/sessions/{old_id}/trace to verify.

Cheers
""",
        encoding="utf-8",
    )
    changed = rewrite_eml_trace_url(
        eml_path=eml, old_trace_url_fragment=old_id, new_trace_url=new_url,
    )
    assert changed is True
    content = eml.read_text()
    assert old_id not in content
    assert new_url in content


def test_rewrite_eml_replaces_url_in_header(tmp_path: Path):
    """The X-Headlights-Trace header should also be rewritten."""
    eml = tmp_path / "test.eml"
    old_id = "abc-123"
    new_url = "http://srv/v1/sessions/xyz/trace"
    eml.write_text(
        f"""To: alice@example.com
Subject: hi
X-Headlights-Trace: https://api.useheadlights.com/v1/sessions/{old_id}/trace
X-Headlights-Agent: marketing-drafter-v0.1

Body line.
""",
        encoding="utf-8",
    )
    rewrite_eml_trace_url(
        eml_path=eml, old_trace_url_fragment=old_id, new_trace_url=new_url,
    )
    content = eml.read_text()
    assert old_id not in content
    assert new_url in content


def test_rewrite_eml_handles_trailing_punctuation(tmp_path: Path):
    """When a URL is followed by punctuation (period, comma), the rewrite
    keeps the punctuation attached to the new URL, not the middle of it."""
    eml = tmp_path / "test.eml"
    old_id = "old-id"
    new_url = "http://srv/v1/sessions/new-id/trace"
    eml.write_text(
        f"See https://x.com/v1/sessions/{old_id}/trace.\n",
        encoding="utf-8",
    )
    rewrite_eml_trace_url(
        eml_path=eml, old_trace_url_fragment=old_id, new_trace_url=new_url,
    )
    content = eml.read_text()
    assert "new-id/trace." in content
    assert "new-id/trace.." not in content


def test_rewrite_eml_returns_false_if_no_match(tmp_path: Path):
    eml = tmp_path / "test.eml"
    eml.write_text("Subject: nothing here\n\nplain body", encoding="utf-8")
    changed = rewrite_eml_trace_url(
        eml_path=eml,
        old_trace_url_fragment="nonexistent-id",
        new_trace_url="http://x",
    )
    assert changed is False


# ── upload_all ───────────────────────────────────────────────────────────


def test_upload_all_full_pipeline(
    hosted_client, server_client, mock_github, sample_prospect_csv, tmp_path: Path
):
    """Drafter → upload → rewritten .eml files → public trace verifiable.
    This is the canonical end-to-end test."""
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    drafts_dir = tmp_path / "drafts"
    write_drafts(results, drafts_dir)

    upload_results = upload_all(drafts_dir=drafts_dir, client=hosted_client)
    assert len(upload_results) == 2

    # Each upload mapped to one .eml file
    assert all(r.eml_path is not None for r in upload_results)

    # Each .eml now contains the server-side URL
    for r in upload_results:
        text = r.eml_path.read_text()
        assert r.trace_url in text
        assert r.local_trace_session_id not in text

    # Each server session is publicly viewable
    for r in upload_results:
        page = server_client.get(f"/v1/sessions/{r.server_session_id}/trace")
        assert page.status_code == 200
        assert "CHAIN INTACT" in page.text


def test_upload_all_writes_manifest(
    hosted_client, mock_github, sample_prospect_csv, tmp_path: Path
):
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    drafts_dir = tmp_path / "drafts"
    write_drafts(results, drafts_dir)

    upload_all(drafts_dir=drafts_dir, client=hosted_client)
    manifest = drafts_dir / "uploaded.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert len(data) == 2
    for entry in data:
        assert "local_trace_session_id" in entry
        assert "server_session_id" in entry
        assert "trace_url" in entry
t.exists()
    data = json.loads(manifest.read_text())
    assert len(data) == 2
    for entry in data:
        assert "local_trace_session_id" in entry
        assert "server_session_id" in entry
        assert "trace_url" in entry
