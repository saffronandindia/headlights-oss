"""Tests for the rate-limiter hardening (issues #1 and #2).

#1 security: X-Forwarded-For must not be trusted unless explicitly enabled, so a
   caller cannot spoof a fresh IP per request and bypass the limit.
#2 ops: the internal window table must not grow without bound; expired windows
   are evicted.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from headlights_server.ratelimit import IPRateLimiter, _get_ip


def _req(*, host: str, xff: str | None = None):
    req = MagicMock()
    req.headers = {} if xff is None else {"x-forwarded-for": xff}
    req.client.host = host
    return req


# ── #1 X-Forwarded-For trust ────────────────────────────────────────────────


def test_xff_ignored_by_default() -> None:
    """With trust off, a spoofed X-Forwarded-For does not change the identity:
    every request from the same socket IP shares one counter."""
    limiter = IPRateLimiter(enabled=True)  # trust_forwarded_for defaults to False

    limiter.check(_req(host="9.9.9.9", xff="1.1.1.1"), "2/hour", "ep")
    limiter.check(_req(host="9.9.9.9", xff="2.2.2.2"), "2/hour", "ep")
    with pytest.raises(HTTPException) as exc:
        # Third request, different spoofed XFF, same socket IP -> blocked.
        limiter.check(_req(host="9.9.9.9", xff="3.3.3.3"), "2/hour", "ep")
    assert exc.value.status_code == 429


def test_get_ip_default_uses_socket_peer() -> None:
    assert _get_ip(_req(host="9.9.9.9", xff="1.1.1.1")) == "9.9.9.9"


def test_get_ip_trusted_uses_rightmost_xff() -> None:
    """When trusted, the right-most XFF entry (appended by the proxy) wins;
    a client-injected left-most value is ignored."""
    assert (
        _get_ip(_req(host="10.0.0.1", xff="evil, 1.2.3.4"), trust_forwarded_for=True)
        == "1.2.3.4"
    )


def test_xff_used_when_trusted() -> None:
    limiter = IPRateLimiter(enabled=True, trust_forwarded_for=True)

    # Same real client (right-most), spoofed prefix -> shared counter.
    limiter.check(_req(host="10.0.0.1", xff="evil, 1.2.3.4"), "2/hour", "ep")
    limiter.check(_req(host="10.0.0.1", xff="evil, 1.2.3.4"), "2/hour", "ep")
    with pytest.raises(HTTPException):
        limiter.check(_req(host="10.0.0.1", xff="evil, 1.2.3.4"), "2/hour", "ep")

    # A genuinely different client (different right-most) is independent.
    limiter.check(_req(host="10.0.0.1", xff="evil, 5.6.7.8"), "2/hour", "ep")


# ── #2 unbounded growth / eviction ──────────────────────────────────────────


def test_expired_windows_are_evicted() -> None:
    limiter = IPRateLimiter(enabled=True)
    limiter.check(_req(host="1.2.3.4"), "5/second", "ep")
    assert len(limiter._windows) == 1

    # Age every window well beyond its period (1s), then force a sweep.
    for win in limiter._windows.values():
        win.window_start -= 10.0
    limiter.evict_expired()
    assert len(limiter._windows) == 0


def test_active_windows_survive_eviction() -> None:
    limiter = IPRateLimiter(enabled=True)
    limiter.check(_req(host="1.2.3.4"), "5/hour", "ep")  # 1-hour window, still active
    limiter.evict_expired()
    assert len(limiter._windows) == 1
