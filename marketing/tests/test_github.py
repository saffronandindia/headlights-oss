"""Tests for marketing.github — minimal API client + cache behaviour."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from marketing.github import GitHubClient, GitHubUser


def _user_payload(login: str) -> dict:
    return {
        "login": login,
        "name": "Test User",
        "company": "Stripe",
        "email": "x@example.com",
        "bio": "Engineer",
        "blog": "",
        "location": "Sydney",
        "public_repos": 10,
        "followers": 50,
        "created_at": "2022-01-01T00:00:00Z",
        "html_url": f"https://github.com/{login}",
    }


def test_user_parses_minimal_profile(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_user_payload("alice"))

    transport = httpx.MockTransport(handler)
    client = GitHubClient(cache_dir=tmp_path / "cache", transport=transport)
    user = client.user("alice")
    assert user.login == "alice"
    assert user.company == "Stripe"
    assert user.public_repos == 10
    client.close()


def test_response_is_cached_on_disk(tmp_path: Path) -> None:
    """Second call for the same URL should not hit the transport."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=_user_payload("alice"))

    transport = httpx.MockTransport(handler)
    client = GitHubClient(cache_dir=tmp_path / "cache", transport=transport)
    client.user("alice")
    client.user("alice")
    client.user("alice")
    assert call_count["n"] == 1, f"cache miss: {call_count['n']} actual calls"
    # Cache file should exist
    cache_files = list((tmp_path / "cache").glob("*.json"))
    assert len(cache_files) == 1
    client.close()


def test_cache_persists_across_clients(tmp_path: Path) -> None:
    """A fresh GitHubClient on the same cache_dir reads the cached response."""
    cache = tmp_path / "cache"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_user_payload("alice"))

    c1 = GitHubClient(cache_dir=cache, transport=httpx.MockTransport(handler))
    c1.user("alice")
    c1.close()

    # New client, transport that would 500 if hit
    def angry_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "should not be called"})

    c2 = GitHubClient(cache_dir=cache, transport=httpx.MockTransport(angry_handler))
    user = c2.user("alice")  # served from cache, no call to angry_handler
    assert user.login == "alice"
    c2.close()


def test_stargazers_paginates_until_empty(tmp_path: Path) -> None:
    pages_returned = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        pages_returned.append(page)
        if page == 1:
            return httpx.Response(200, json=[{"login": "u1"}, {"login": "u2"}])
        if page == 2:
            return httpx.Response(200, json=[{"login": "u3"}])
        return httpx.Response(200, json=[])

    client = GitHubClient(cache_dir=tmp_path / "cache", transport=httpx.MockTransport(handler))
    logins = list(client.stargazers("o/r"))
    assert logins == ["u1", "u2", "u3"]
    assert pages_returned[:3] == [1, 2, 3]
    client.close()


def test_stargazers_honours_max_users(tmp_path: Path) -> None:
    """A bounded walk must stop after max_users, not exhaust pagination."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"login": f"u{i}"} for i in range(100)])

    client = GitHubClient(cache_dir=tmp_path / "cache", transport=httpx.MockTransport(handler))
    logins = list(client.stargazers("o/r", max_users=5))
    assert len(logins) == 5
    client.close()


def test_rate_limit_retries_then_succeeds(tmp_path: Path) -> None:
    """First call returns 403 rate-limited, second succeeds."""
    state = {"hit": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["hit"] += 1
        if state["hit"] == 1:
            return httpx.Response(
                403,
                json={"message": "API rate limit exceeded for user."},
                headers={"X-RateLimit-Reset": "0"},  # past timestamp
            )
        return httpx.Response(200, json=_user_payload("alice"))

    # Mock sleep so the test stays fast
    sleep_calls = []
    def fake_sleep(secs: float) -> None:
        sleep_calls.append(secs)

    client = GitHubClient(
        cache_dir=tmp_path / "cache",
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
    )
    user = client.user("alice")
    assert user.login == "alice"
    assert state["hit"] == 2
    assert sleep_calls, "sleep was not called between retries"
    client.close()
