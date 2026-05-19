"""Drafter agent — produce personalised email drafts from a prospect CSV.

Reads the CSV produced by `marketing.discovery`, fetches each prospect's
public repos, generates a templated email draft, and writes both the .eml
and the per-draft conduct chain to disk. Each prospect gets its own chain
so the trace URL is one-email = one-public-page.

CLI:

    python -m marketing.drafter --prospects prospects.csv --output drafts/

Drafts are NEVER sent automatically. The output is .eml files for human
review.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sys
import uuid
from pathlib import Path
from typing import Iterable

from headlights_sdk import Client

from marketing.github import GitHubClient
from marketing.templates import EmailDraft, draft_for


@dataclasses.dataclass(frozen=True)
class DrafterResult:
    """A single drafter output: the email draft plus its conduct chain.

    The chain is the audit trail of how this specific draft was produced.
    When uploaded to the Headlights server and published, it becomes the
    target of the trace URL embedded in the email.
    """

    draft: EmailDraft
    chain_records: list[dict]


def run_drafter(
    *,
    prospect_rows: Iterable[dict[str, str]],
    github: GitHubClient,
    chain_client: Client | None = None,
    max_repos_per_prospect: int = 10,
    agent_id: str = "urn:headlights:agent:marketing-drafter",
    agent_version: str = "0.1.0",
) -> list[DrafterResult]:
    """Generate drafts for every prospect.

    Each prospect gets its own Client + chain so the trace URL is
    one-email = one-public-page. Returns DrafterResults: each carries
    the draft plus the conduct chain for that one draft.

    The optional chain_client argument exists for callers that want a
    summary-level chain of the whole drafter run (one record per draft
    attempted). It is NOT the chain that backs each draft's trace URL —
    those live in the DrafterResult.chain_records.
    """
    results: list[DrafterResult] = []

    for row in prospect_rows:
        login = row["login"]
        target_library = row.get("target_library") or "an agent library"
        trace_session_id = str(uuid.uuid4())

        per_draft_client = Client(agent_id=agent_id, agent_version=agent_version)

        with per_draft_client.session(
            trust_level="L1",
            genesis_detail={
                "agent": "drafter",
                "prospect_login": login,
                "draft_session_id": trace_session_id,
            },
        ):
            per_draft_client.record_action(
                "tool_call",
                {"tool_name": "github.user", "parameters": {"login": login}},
            )
            try:
                user = github.user(login)
            except Exception as exc:
                per_draft_client.record_action(
                    "tool_response",
                    {
                        "tool_name": "github.user",
                        "outcome": "failure",
                        "error": str(exc)[:200],
                    },
                    outcome="failure",
                )
                if chain_client is not None:
                    chain_client.record_action(
                        "decision",
                        {
                            "decision_type": "draft_skipped",
                            "prospect_login": login,
                            "reason": str(exc)[:200],
                        },
                        outcome="failure",
                    )
                continue

            per_draft_client.record_action(
                "tool_call",
                {
                    "tool_name": "github.user_repos",
                    "parameters": {"login": login, "max_repos": max_repos_per_prospect},
                },
            )
            repos = github.user_repos(login, max_repos=max_repos_per_prospect)
            per_draft_client.record_action(
                "tool_response",
                {
                    "tool_name": "github.user_repos",
                    "result": {
                        "count": len(repos),
                        "top_repo": repos[0].full_name if repos else None,
                    },
                },
            )

            draft = draft_for(
                user, repos,
                target_library=target_library,
                trace_session_id=trace_session_id,
            )

            per_draft_client.record_action(
                "decision",
                {
                    "decision_type": "draft_generated",
                    "prospect_login": login,
                    "subject": draft.subject,
                    "body_length": len(draft.body),
                    "to_address": draft.to_address or "(none)",
                },
            )

        chain_records = per_draft_client.export()
        results.append(DrafterResult(draft=draft, chain_records=chain_records))

        if chain_client is not None:
            chain_client.record_action(
                "decision",
                {
                    "decision_type": "draft_completed",
                    "prospect_login": login,
                    "trace_session_id": trace_session_id,
                    "chain_length": len(chain_records),
                },
            )

    return results


def read_prospects(path: Path) -> list[dict[str, str]]:
    """Read prospects from the CSV produced by discovery."""
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_drafts(results: list[DrafterResult], output_dir: Path) -> list[Path]:
    """Write each draft to {output_dir}/{login}.eml and the corresponding
    chain to {output_dir}/chains/{trace_session_id}.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    chains_dir = output_dir / "chains"
    chains_dir.mkdir(exist_ok=True)
    written = []
    for result in results:
        draft = result.draft
        eml_path = output_dir / f"{draft.prospect_login}.eml"
        eml_path.write_text(draft.to_eml(), encoding="utf-8")
        chain_path = chains_dir / f"{draft.trace_session_id}.json"
        chain_path.write_text(json.dumps(result.chain_records, indent=2), encoding="utf-8")
        written.append(eml_path)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="marketing.drafter")
    parser.add_argument("--prospects", type=Path, default=Path("prospects.csv"))
    parser.add_argument("--output", type=Path, default=Path("drafts"))
    parser.add_argument("--summary-chain", type=Path, default=Path("drafter.chain.json"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/github"))
    args = parser.parse_args(argv)

    if not args.prospects.exists():
        print(f"error: {args.prospects} does not exist (run discovery first)", file=sys.stderr)
        return 2

    github = GitHubClient(cache_dir=args.cache_dir)
    summary_client = Client(
        agent_id="urn:headlights:agent:marketing-drafter",
        agent_version="0.1.0",
    )
    try:
        with summary_client.session(genesis_detail={"role": "summary"}):
            rows = read_prospects(args.prospects)
            results = run_drafter(
                prospect_rows=rows, github=github, chain_client=summary_client,
            )
        paths = write_drafts(results, args.output)
        args.summary_chain.write_text(json.dumps(summary_client.export(), indent=2))
    finally:
        github.close()

    print(f"Wrote {len(paths)} drafts to {args.output}/")
    print(f"Per-draft chains in {args.output}/chains/")
    print(f"Summary chain: {summary_client.record_count()} records -> {args.summary_chain}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
