"""End-to-end tests for the discovery agent."""

from __future__ import annotations

from pathlib import Path

from headlights_chain import Chain
from headlights_sdk import Client

from marketing.discovery import (
    DEFAULT_TARGET_LIBRARIES,
    ProspectRow,
    run_discovery,
    write_csv,
)
from marketing.tests.conftest import STARGAZERS


def _chain_client() -> Client:
    return Client(
        agent_id="urn:headlights:agent:discovery-test",
        agent_version="0.1.0",
    )


def test_run_discovery_keeps_good_prospects(mock_github) -> None:
    chain_client = _chain_client()
    targets = [
        ("langchain-ai/langchain", "LangChain"),
        ("pydantic/pydantic-ai", "Pydantic AI"),
    ]
    rows = run_discovery(
        github=mock_github,
        chain_client=chain_client,
        targets=targets,
        max_prospects=10,
        max_stargazers_per_repo=10,
    )

    logins = [r.login for r in rows]
    # Alice (B2B engineer) and Diana (founder) should be kept
    assert "alice-engineer" in logins
    assert "diana-founder" in logins
    # Bob (student) and Charlie (thin profile) should be filtered out
    assert "bob-student" not in logins
    assert "charlie-thin" not in logins


def test_run_discovery_dedupes_logins(mock_github) -> None:
    """Alice stars both LangChain and Pydantic AI; she should appear once."""
    chain_client = _chain_client()
    targets = [
        ("langchain-ai/langchain", "LangChain"),
        ("pydantic/pydantic-ai", "Pydantic AI"),
    ]
    rows = run_discovery(
        github=mock_github,
        chain_client=chain_client,
        targets=targets,
        max_prospects=20,
    )
    logins = [r.login for r in rows]
    assert logins.count("alice-engineer") == 1


def test_run_discovery_respects_max_prospects(mock_github) -> None:
    chain_client = _chain_client()
    targets = [
        ("langchain-ai/langchain", "LangChain"),
        ("pydantic/pydantic-ai", "Pydantic AI"),
    ]
    rows = run_discovery(
        github=mock_github,
        chain_client=chain_client,
        targets=targets,
        max_prospects=1,
    )
    assert len(rows) == 1


def test_discovery_records_chain_intact(mock_github) -> None:
    """The agent's own conduct chain must verify cleanly.

    This is the dogfood property — the agent that finds prospects has
    itself produced a tamper-evident record of every decision it made.
    """
    chain_client = _chain_client()
    run_discovery(
        github=mock_github,
        chain_client=chain_client,
        targets=[("langchain-ai/langchain", "LangChain")],
        max_prospects=5,
        max_stargazers_per_repo=10,
    )

    records = chain_client.export()
    assert len(records) >= 3  # genesis + at least one decision + session_end
    chain = Chain.from_records(records)
    result = chain.verify()
    assert result.is_intact, f"chain broken: {result.reason} at {result.failed_position}"


def test_chain_records_include_filter_reasons(mock_github) -> None:
    """The chain should record WHY each prospect was kept or dropped."""
    chain_client = _chain_client()
    run_discovery(
        github=mock_github,
        chain_client=chain_client,
        targets=[("langchain-ai/langchain", "LangChain")],
        max_prospects=10,
    )
    records = chain_client.export()
    decision_records = [
        r for r in records
        if r.get("action_type") == "decision"
        and r.get("action_detail", {}).get("decision_type") == "filter_prospect"
    ]
    assert len(decision_records) >= 3  # alice, bob, charlie at minimum
    # Each filter decision should carry the reasons list
    for d in decision_records:
        assert "reasons" in d["action_detail"]
        assert isinstance(d["action_detail"]["reasons"], list)


def test_write_csv_round_trips(tmp_path: Path, mock_github) -> None:
    chain_client = _chain_client()
    rows = run_discovery(
        github=mock_github,
        chain_client=chain_client,
        targets=[("langchain-ai/langchain", "LangChain")],
        max_prospects=5,
    )
    out = tmp_path / "prospects.csv"
    write_csv(rows, out)

    text = out.read_text()
    assert "login,name,company" in text.splitlines()[0]
    # Each row should be on its own line
    assert len(text.splitlines()) == len(rows) + 1


def test_default_targets_are_well_formed() -> None:
    """The hard-coded library list must be (repo, label) tuples."""
    for entry in DEFAULT_TARGET_LIBRARIES:
        assert isinstance(entry, tuple)
        assert len(entry) == 2
        repo, label = entry
        assert "/" in repo
        assert label  # non-empty
