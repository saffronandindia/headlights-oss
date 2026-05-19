"""Minimal GitHub API client for discovery.

Scope is deliberately tiny: list stargazers of a repo and fetch user profiles.
Caches responses to `.cache/github/` on disk so reruns are fast and resumable.
Token comes from the GITHUB_TOKEN env var; unauthenticated rate limits are
60/hour, which is enough only for tiny dry-runs.

The class is constructor-injected with an HTTP transport so tests can pass
a fake without monkey-patching httpx.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

import httpx

API_BASE = "https://api.github.com"
USER_AGENT = "headlights-discovery/0.1 (+https://github.com/saffronandindia/headlights-oss)"


@dataclass(frozen=True)
class GitHubUser:
    """A minimal projection of a GitHub user profile."""

    login: str
    name: str | None
    company: str | None
    email: str | None
    bio: str | None
    blog: str | None
    location: str | None
    public_repos: int
    followers: int
    created_at: str
    profile_url: str

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "GitHubUser":
        return cls(
            login=payload["login"],
            name=payload.get("name"),
            company=payload.get("company"),
            email=payload.get("email"),
            bio=payload.get("bio"),
            blog=payload.get("blog") or None,
            location=payload.get("location"),
            public_repos=int(payload.get("public_repos", 0)),
            followers=int(payload.get("followers", 0)),
            created_at=payload.get("created_at", ""),
            profile_url=payload.get("html_url", f"https://github.com/{payload['login']}"),
        )


@dataclass(frozen=True)
class GitHubRepo:
    """A minimal projection of a GitHub repo."""

    full_name: str
    description: str | None
    language: str | None
    stargazers_count: int
    pushed_at: str
    html_url: str

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "GitHubRepo":
        return cls(
            full_name=payload["full_name"],
            description=payload.get("description"),
            language=payload.get("language"),
            stargazers_count=int(payload.get("stargazers_count", 0)),
            pushed_at=payload.get("pushed_at", ""),
            html_url=payload.get("html_url", ""),
        )


class GitHubClient:
    """Read-only GitHub API client with on-disk caching.

    Pass `transport=` for tests (httpx.MockTransport). Production callers
    just instantiate it bare and read GITHUB_TOKEN from env.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        cache_dir: str | os.PathLike[str] = ".cache/github",
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN")
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._sleep = sleep
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        # transport is None in production (use real network); set in tests.
        self._client = httpx.Client(
            base_url=API_BASE,
            headers=headers,
            timeout=15.0,
            transport=transport,
        )

    # ── Public API ──────────────────────────────────────────────────────

    def stargazers(self, repo: str, *, max_users: int | None = None) -> Iterator[str]:
        """Yield stargazer logins for `owner/repo`, paginated.

        Stops at `max_users` if given. Uses the v3 GET /repos/{r}/stargazers
        endpoint, which returns logins (not full profiles).
        """
        yielded = 0
        for page in range(1, 1000):  # GitHub caps at ~400 pages
            payload = self._get(f"/repos/{repo}/stargazers", params={"per_page": 100, "page": page})
            if not isinstance(payload, list) or not payload:
                return
            for entry in payload:
                yield entry["login"]
                yielded += 1
                if max_users is not None and yielded >= max_users:
                    return

    def user(self, login: str) -> GitHubUser:
        payload = self._get(f"/users/{login}")
        return GitHubUser.from_api(payload)

    def user_repos(self, login: str, *, max_repos: int = 30) -> list[GitHubRepo]:
        payload = self._get(
            f"/users/{login}/repos",
            params={"per_page": max_repos, "sort": "pushed", "type": "owner"},
        )
        if not isinstance(payload, list):
            return []
        return [GitHubRepo.from_api(r) for r in payload]

    def readme_text(self, repo: str) -> str:
        """Return decoded README content or empty string on failure."""
        try:
            payload = self._get(f"/repos/{repo}/readme")
        except httpx.HTTPStatusError:
            return ""
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            return ""
        import base64

        try:
            return base64.b64decode(payload.get("content", "")).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""

    def close(self) -> None:
        self._client.close()

    # ── Internals ───────────────────────────────────────────────────────

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        cache_key = self._cache_key(path, params or {})
        cache_path = self._cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text())

        for attempt in range(5):
            response = self._client.get(path, params=params)
            if response.status_code == 200:
                payload = response.json()
                cache_path.write_text(json.dumps(payload))
                return payload
            if response.status_code in (403, 429) and "rate limit" in response.text.lower():
                # Honour the X-RateLimit-Reset header if present.
                reset = response.headers.get("X-RateLimit-Reset")
                wait = max(1.0, float(reset) - time.time()) if reset else 60.0
                self._sleep(min(wait, 60.0))
                continue
            response.raise_for_status()
        raise RuntimeError(f"exhausted retries fetching {path}")

    @staticmethod
    def _cache_key(path: str, params: dict[str, Any]) -> str:
        canonical = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
