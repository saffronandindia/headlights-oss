"""Discovery agent — find B2B prospects building agent systems.

Walks the stargazer lists of major AI-agent libraries, fetches user
profiles, applies B2B filters, and outputs a CSV of prospects. Every
step records into a Headlights chain so the agent itself is auditable.

CLI:

    python -m marketing.discovery --output prospects.csv --max-prospects 20

By default runs against a small curated library list with a low cap, so
a single run consumes ~50 unauthenticated GitHub API calls. Set the
GITHUB_TOKEN env var to lift the rate limit.

For tests, the run_discovery() function takes an injected GitHubClient
so a MockTransport can drive the whole pipeline deterministically.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sys
from pathlib import Path
from typing import Iterable

from headlights_sdk import Client

from marketing.filters import ProspectVerdict, classify
from marketing.github import GitHubClient, GitHubUser

# A small curated default list of agent-related repos. Each line is
# (owner/repo, library label used in output + drafter context).
DEFAULT_TARGET_LIBRARIES = [
    ("langchain-ai/langchain", "LangChain"),
    ("pydantic/pydantic-ai", "Pydantic AI"),
    ("crewAIInc/crewAI", "CrewAI"),
    ("microsoft/autogen", "AutoGen"),
    ("modelcontextprotocol/python-sdk", "MCP Python SDK"),
]


@dataclasses.dataclass(frozen=True)
class ProspectRow:
    """A single row in the output CSV."""

    login: str
    name: str
    company: str
    email: str
    location: str
    bio: str
    public_repos: int
    followers: int
    profile_url: str
    target_library: str
    target_repo: str
    score: int
    filter_reasons: str

    @classmethod
    def from_user(
        cls,
        user: GitHubUser,
        verdict: ProspectVerdict,
        *,
        target_library: str,
        target_repo: str,
    ) -> "ProspectRow":
        return cls(
            login=user.login,
            name=user.name or "",
            company=user.company or "",
            email=user.email or "",
            location=user.location or "",
            bio=(user.bio or "").replace("\n", " ").strip(),
            public_repos=user.public_repos,
            followers=user.followers,
            profile_url=user.profile_url,
            target_library=target_library,
            target_repo=target_repo,
            score=verdict.score,
            filter_reasons=" | ".join(verdict.reasons),
        )


def run_discovery(
    *,
    github: GitHubClient,
    chain_client: Client,
    targets: Iterable[tuple[str, str]] = DEFAULT_TARGET_LIBRARIES,
    max_prospects: int = 20,
    max_stargazers_per_repo: int = 50,
) -> list[ProspectRow]:
    """Walk targets, fetch and filter users, return prospect rows.

    Records every major decision into the chain_client. Caller is
    responsible for opening + closing the SDK session.
    """
    prospects: list[ProspectRow] = []
    seen_logins: set[str] = set()

    with chain_client.session(
        trust_level="L1",
        genesis_detail={
            "agent": "discovery",
            "max_prospects": max_prospects,
            "target_count": len(list(targets)) if not isinstance(targets, list) else len(targets),
        },
    ):
        # Re-bind targets as a list since we may have just exhausted it
        target_list = list(targets)
        for repo, library_label in target_list:
            if len(prospects) >= max_prospects:
                chain_client.record_action(
                    "decision",
                    {
                        "decision_type": "stop_walking_targets",
                        "reason": "max_prospects reached",
                        "prospects_so_far": len(prospects),
                    },
                )
                break

            chain_client.record_action(
                "tool_call",
                {
                    "tool_name": "github.stargazers",
                    "parameters": {"repo": repo, "max": max_stargazers_per_repo},
                },
            )
            stargazers = list(github.stargazers(repo, max_users=max_stargazers_per_repo))
            chain_client.record_action(
                "tool_response",
                {
                    "tool_name": "github.stargazers",
                    "result": {"count": len(stargazers)},
                },
            )

            for login in stargazers:
                if login in seen_logins:
                    continue
                seen_logins.add(login)
                if len(prospects) >= max_prospects:
                    break

                chain_client.record_action(
                    "tool_call",
                    {
                        "tool_name": "github.user",
                        "parameters": {"login": login},
                    },
                )
                try:
                    user = github.user(login)
                except Exception as exc:  # noqa: BLE001
                    chain_client.record_action(
                        "tool_response",
                        {
                            "tool_name": "github.user",
                            "outcome": "failure",
                            "error": str(exc)[:200],
                        },
                        outcome="failure",
                    )
                    continue

                verdict = classify(user)
                chain_client.record_action(
                    "decision",
                    {
                        "decision_type": "filter_prospect",
                        "login": login,
                        "is_prospect": verdict.is_prospect,
                        "score": verdict.score,
                        "reasons": verdict.reasons,
                    },
                )

                if verdict.is_prospect:
                    prospects.append(
                        ProspectRow.from_user(
                            user,
                            verdict,
                            target_library=library_label,
                            target_repo=repo,
                        )
                    )

        chain_client.record_action(
            "decision",
            {
                "decision_type": "discovery_complete",
                "prospect_count": len(prospects),
                "users_examined": len(seen_logins),
            },
        )

    return prospects


def write_csv(rows: list[ProspectRow], path: Path) -> None:
    """Write prospect rows to a CSV file with a stable header."""
    if not rows:
        path.write_text("")
        return
    fieldnames = list(dataclasses.asdict(rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dataclasses.asdict(row))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marketing.discovery")
    parser.add_argument("--output", type=Path, default=Path("prospects.csv"))
    parser.add_argument("--chain-output", type=Path, default=Path("discovery.chain.json"))
    parser.add_argument("--max-prospects", type=int, default=20)
    parser.add_argument("--max-stargazers", type=int, default=50)
    parser.add_argument(
        "--cache-dir", type=Path, default=Path(".cache/github"),
        help="On-disk cache for GitHub API responses.",
    )
    args = parser.parse_args(argv)

    github = GitHubClient(cache_dir=args.cache_dir)
    chain_client = Client(
        agent_id="urn:headlights:agent:marketing-discovery",
        agent_version="0.1.0",
    )
    try:
        rows = run_discovery(
            github=github,
            chain_client=chain_client,
            max_prospects=args.max_prospects,
            max_stargazers_per_repo=args.max_stargazers,
        )
        write_csv(rows, args.output)
        args.chain_output.write_text(json.dumps(chain_client.export(), indent=2))
    finally:
        github.close()

    print(f"Wrote {len(rows)} prospects to {args.output}")
    print(f"Wrote chain ({chain_client.record_count()} records) to {args.chain_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
