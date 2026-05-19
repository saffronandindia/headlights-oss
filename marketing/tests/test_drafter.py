"""End-to-end tests for the drafter agent."""

from __future__ import annotations

from pathlib import Path

from headlights_chain import Chain

from marketing.drafter import (
    DrafterResult,
    read_prospects,
    run_drafter,
    write_drafts,
)


def test_run_drafter_produces_one_result_per_prospect(mock_github, sample_prospect_csv):
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    assert len(results) == 2
    assert {r.draft.prospect_login for r in results} == {"alice-engineer", "diana-founder"}


def test_each_draft_has_unique_trace_session(mock_github, sample_prospect_csv):
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    trace_ids = {r.draft.trace_session_id for r in results}
    assert len(trace_ids) == len(results)


def test_draft_subject_references_prospect_work(mock_github, sample_prospect_csv):
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    alice = next(r for r in results if r.draft.prospect_login == "alice-engineer")
    assert "agent-runtime" in alice.draft.subject


def test_each_per_draft_chain_is_intact(mock_github, sample_prospect_csv):
    """Every drafted email leaves an intact chain trail. This is the dogfood
    property the email-as-demo loop depends on."""
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    assert len(results) > 0
    for result in results:
        chain = Chain.from_records(result.chain_records)
        outcome = chain.verify()
        assert outcome.is_intact, (
            f"chain for {result.draft.prospect_login} broken: "
            f"{outcome.reason} at {outcome.failed_position}"
        )


def test_drafter_skips_unknown_user_gracefully(mock_github, tmp_path):
    import csv as csv_mod
    bad_csv = tmp_path / "bad.csv"
    with bad_csv.open("w", newline="") as f:
        writer = csv_mod.DictWriter(f, fieldnames=["login", "target_library"])
        writer.writeheader()
        writer.writerow({"login": "no-such-user", "target_library": "LangChain"})
        writer.writerow({"login": "alice-engineer", "target_library": "LangChain"})

    rows = read_prospects(bad_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    assert [r.draft.prospect_login for r in results] == ["alice-engineer"]


def test_write_drafts_creates_eml_and_chain_files(
    mock_github, sample_prospect_csv, tmp_path
):
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    output_dir = tmp_path / "drafts"
    paths = write_drafts(results, output_dir)
    assert len(paths) == 2
    for path in paths:
        assert path.suffix == ".eml"
        content = path.read_text()
        assert "To: " in content
        assert "Subject: " in content
        assert "X-Headlights-Trace: " in content
    chain_files = list((output_dir / "chains").glob("*.json"))
    assert len(chain_files) == 2


def test_draft_body_contains_repo_url(mock_github, sample_prospect_csv):
    rows = read_prospects(sample_prospect_csv)
    results = run_drafter(prospect_rows=rows, github=mock_github)
    for result in results:
        assert "github.com/saffronandindia/headlights-oss" in result.draft.body


def test_optional_summary_chain_gets_one_record_per_draft(
    mock_github, sample_prospect_csv
):
    """When a summary chain_client is passed, it records a per-draft summary
    — useful for the agent-level audit trail without losing the per-draft
    chains."""
    from headlights_sdk import Client
    summary = Client(
        agent_id="urn:headlights:agent:drafter-summary",
        agent_version="0.1.0",
    )
    rows = read_prospects(sample_prospect_csv)
    with summary.session(genesis_detail={"role": "summary"}):
        run_drafter(prospect_rows=rows, github=mock_github, chain_client=summary)

    records = summary.export()
    decision_records = [
        r for r in records
        if r.get("action_type") == "decision"
        and r.get("action_detail", {}).get("decision_type") == "draft_completed"
    ]
    assert len(decision_records) == 2
    chain = Chain.from_records(records)
    assert chain.verify().is_intact
