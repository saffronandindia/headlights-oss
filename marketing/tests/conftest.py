"""Shared fixtures for marketing agent tests.

The big one is a MockTransport-backed GitHubClient that returns canned
responses for stargazers / users / repos endpoints. Tests pass it into
run_discovery / run_drafter so the full pipelines run deterministically
without network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from marketing.github import GitHubClient


# ── Canned fixtures ──────────────────────────────────────────────────────


def _user_payload(
    login: str,
    *,
    name: str = "",
    company: str = "",
    email: str = "",
    bio: str = "",
    public_repos: int = 10,
    followers: int = 50,
    location: str = "Sydney",
) -> dict[str, Any]:
    return {
        "login": login,
        "name": name or login.title(),
        "company": company,
        "email": email,
        "bio": bio,
        "blog": "",
        "location": location,
        "public_repos": public_repos,
        "followers": followers,
        "created_at": "2022-01-01T00:00:00Z",
        "html_url": f"https://github.com/{login}",
    }


def _repo_payload(
    full_name: str,
    *,
    description: str = "A test repo",
    language: str = "Python",
    stars: int = 5,
) -> dict[str, Any]:
    return {
        "full_name": full_name,
        "description": description,
        "language": language,
        "stargazers_count": stars,
        "pushed_at": "2026-05-10T00:00:00Z",
        "html_url": f"https://github.com/{full_name}",
    }


# Three personas to test the filters end-to-end:
# - good_prospect: real B2B engineer
# - bad_prospect_student: bio contains "student" → filtered out
# - bad_prospect_thin: no company, low repos → filtered out
USERS = {
    "alice-engineer": _user_payload(
        "alice-engineer",
        name="Alice Engineer",
        company="@stripe",
        email="alice@example.com",
        bio="Staff engineer working on agent infrastructure",
        public_repos=42,
        followers=300,
    ),
    "bob-student": _user_payload(
        "bob-student",
        name="Bob Smith",
        company="University of Sydney",
        email="",
        bio="CS student learning AI",
        public_repos=8,
        followers=10,
    ),
    "charlie-thin": _user_payload(
        "charlie-thin",
        name="",
        company="",
        email="",
        bio="",
        public_repos=2,
        followers=1,
    ),
    "diana-founder": _user_payload(
        "diana-founder",
        name="Diana Founder",
        company="Acme Labs Pty Ltd",
        email="diana@acme.example",
        bio="Founder / CTO building MLOps for agents",
        public_repos=27,
        followers=180,
    ),
}

USER_REPOS = {
    "alice-engineer": [
        _repo_payload("alice-engineer/agent-runtime", description="Fast agent orchestration", stars=120),
        _repo_payload("alice-engineer/eval-harness", description="Eval harness for LLM tools", stars=22),
    ],
    "bob-student": [
        _repo_payload("bob-student/homework-1", description="Class project", stars=0),
    ],
    "charlie-thin": [],
    "diana-founder": [
        _repo_payload("acme/agent-platform", description="Agent platform internals", stars=45),
    ],
}

STARGAZERS = {
    "langchain-ai/langchain": [
        {"login": "alice-engineer"},
        {"login": "bob-student"},
        {"login": "charlie-thin"},
    ],
    "pydantic/pydantic-ai": [
        {"login": "diana-founder"},
        {"login": "alice-engineer"},  # duplicate — discovery should dedupe
    ],
}


def _handler(request: httpx.Request) -> httpx.Response:
    """MockTransport handler routing the GitHub endpoints we use."""
    path = request.url.path

    # Stargazers: /repos/{owner}/{repo}/stargazers
    if path.endswith("/stargazers"):
        repo = path.removeprefix("/repos/").removesuffix("/stargazers")
        return _paginated_json(STARGAZERS.get(repo, []), request)

    # User profile: /users/{login}
    if path.startswith("/users/") and "/repos" not in path:
        login = path.removeprefix("/users/")
        user = USERS.get(login)
        if user is None:
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json=user)

    # User repos: /users/{login}/repos
    if path.startswith("/users/") and path.endswith("/repos"):
        login = path.removeprefix("/users/").removesuffix("/repos")
        repos = USER_REPOS.get(login, [])
        return httpx.Response(200, json=repos)

    return httpx.Response(404, json={"message": f"Unrouted: {path}"})


def _paginated_json(items: list[Any], request: httpx.Request) -> httpx.Response:
    """Tiny pagination emulator. The discovery client only ever pages forward
    in increments of per_page, so we honour `page` and return [] when out of bounds."""
    params = dict(request.url.params)
    per_page = int(params.get("per_page", 30))
    page = int(params.get("page", 1))
    start = (page - 1) * per_page
    end = start + per_page
    return httpx.Response(200, json=items[start:end])


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def mock_github(tmp_path: Path) -> GitHubClient:
    """A GitHubClient wired to a deterministic MockTransport.

    The on-disk cache lives in tmp_path so tests are isolated and resumable
    rerun behaviour is observable.
    """
    transport = httpx.MockTransport(_handler)
    return GitHubClient(cache_dir=tmp_path / "cache", transport=transport, token=None)


@pytest.fixture
def sample_prospect_csv(tmp_path: Path) -> Path:
    """A pre-built prospects.csv with two prospects, ready to feed the drafter."""
    import csv as csv_mod

    path = tmp_path / "prospects.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv_mod.DictWriter(
            f,
            fieldnames=[
                "login", "name", "company", "email", "location", "bio",
                "public_repos", "followers", "profile_url",
                "target_library", "target_repo", "score", "filter_reasons",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "login": "alice-engineer",
            "name": "Alice Engineer",
            "company": "@stripe",
            "email": "alice@example.com",
            "location": "Sydney",
            "bio": "Staff engineer working on agent infrastructure",
            "public_repos": "42",
            "followers": "300",
            "profile_url": "https://github.com/alice-engineer",
            "target_library": "LangChain",
            "target_repo": "langchain-ai/langchain",
            "score": "6",
            "filter_reasons": "company looks B2B | 42 public repos | bio positive",
        })
        writer.writerow({
            "login": "diana-founder",
            "name": "Diana Founder",
            "company": "Acme Labs Pty Ltd",
            "email": "diana@acme.example",
            "location": "Sydney",
            "bio": "Founder / CTO building MLOps for agents",
            "public_repos": "27",
            "followers": "180",
            "profile_url": "https://github.com/diana-founder",
            "target_library": "Pydantic AI",
            "target_repo": "pydantic/pydantic-ai",
            "score": "6",
            "filter_reasons": "company looks B2B | 27 public repos | bio positive",
        })
    return path
