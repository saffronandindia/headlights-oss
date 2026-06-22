"""Simple per-IP rate limiting for unauthenticated endpoints.

Uses an in-process fixed-window counter so the limiter instance is per-app
rather than module-level. This lets test apps create isolated limiters with no
shared state, while production uses a single shared in-memory store.

Deployment note (single worker)
-------------------------------
This limiter keeps its counters in process memory, so it only works correctly
when the server runs as a **single worker process**. Running multiple workers
(``uvicorn ... --workers N`` or several gunicorn workers) gives each worker its
own counters, multiplying the effective limit by the worker count. The shipped
Docker image pins ``--workers 1`` for this reason. To scale out, replace this
limiter with a shared backend (e.g. Redis). See issue #3.

Client IP and proxies (security)
--------------------------------
By default the limiter identifies callers by the socket peer IP
(``request.client.host``) and **ignores** the ``X-Forwarded-For`` header,
because any caller can set that header and would otherwise be able to spoof a
fresh IP on every request and bypass the limit entirely. If, and only if, the
server runs behind a trusted reverse proxy that appends the real client IP,
set ``trust_forwarded_for=True`` (env ``HEADLIGHTS_TRUST_FORWARDED_FOR=true``);
the limiter then uses the right-most ``X-Forwarded-For`` entry, which is the
value your proxy appended and which a caller cannot forge. See issue #1.

Usage in create_app():

    from headlights_server.ratelimit import IPRateLimiter
    limiter = IPRateLimiter(trust_forwarded_for=settings.trust_forwarded_for)
    app.state.limiter = limiter

Usage in a route:

    def my_route(request: Request, ...):
        request.app.state.limiter.check(request, "10/hour", "register_agent")
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import RLock


@dataclass
class _Window:
    count: int = 0
    window_start: float = field(default_factory=time.monotonic)


class IPRateLimiter:
    """Thread-safe, in-process, per-IP fixed-window rate limiter.

    Each (ip, endpoint, window_seconds) triple gets its own counter.
    Uses a fixed window (not sliding) per period — adequate for registration
    abuse prevention and simpler to reason about than a token bucket.

    Expired counters are evicted opportunistically (see ``_EVICT_INTERVAL``) so
    the counter table cannot grow without bound as new IPs arrive.

    Parameters
    ----------
    enabled : bool
        Set False to disable all rate checks (useful in tests).
    trust_forwarded_for : bool
        When True, take the client IP from the right-most ``X-Forwarded-For``
        entry instead of the socket peer. Enable ONLY behind a trusted proxy
        that appends the real client IP. Default False (header ignored).
    """

    # Sweep stale windows at most once per this many seconds. Keeps eviction
    # cheap (O(n) at most once a minute) rather than scanning on every request.
    _EVICT_INTERVAL = 60.0

    def __init__(self, *, enabled: bool = True, trust_forwarded_for: bool = False) -> None:
        self.enabled = enabled
        self.trust_forwarded_for = trust_forwarded_for
        self._lock = RLock()
        # { (ip, endpoint, window_seconds) -> _Window }
        self._windows: dict[tuple, _Window] = defaultdict(_Window)
        self._last_evict = time.monotonic()

    def check(self, request, limit_string: str, endpoint_name: str) -> None:
        """Raise HTTP 429 if the caller has exceeded limit_string.

        Parameters
        ----------
        request : starlette.requests.Request
        limit_string : str
            ``"N/period"`` e.g. ``"10/hour"``, ``"5/minute"``.
        endpoint_name : str
            Logical name used to namespace the counter (use the route name).

        Raises
        ------
        fastapi.HTTPException with status_code 429 if the limit is exceeded.
        """
        if not self.enabled:
            return

        limit_int, period = _parse_limit(limit_string)
        ip = _get_ip(request, trust_forwarded_for=self.trust_forwarded_for)
        now = time.monotonic()
        key = (ip, endpoint_name, period)

        with self._lock:
            self._evict_expired(now)
            win = self._windows[key]
            if now - win.window_start >= period:
                # New window
                win.count = 1
                win.window_start = now
            else:
                win.count += 1
                if win.count > limit_int:
                    from fastapi import HTTPException
                    retry_after = int(period - (now - win.window_start)) + 1
                    raise HTTPException(
                        status_code=429,
                        detail=f"rate limit exceeded: {limit_string}",
                        headers={"Retry-After": str(retry_after)},
                    )

    def _evict_expired(self, now: float, *, force: bool = False) -> None:
        """Drop windows whose period has fully elapsed.

        An expired window would be reset on its next access anyway, so removing
        it changes no behaviour — it just stops the table growing without bound
        as one-off IPs accumulate. Throttled to once per ``_EVICT_INTERVAL`` so
        a busy server does not pay an O(n) scan on every request. The caller
        must hold ``self._lock``.
        """
        if not force and now - self._last_evict < self._EVICT_INTERVAL:
            return
        self._last_evict = now
        # key is (ip, endpoint, window_seconds); key[2] is the period.
        stale = [k for k, w in self._windows.items() if now - w.window_start >= k[2]]
        for k in stale:
            del self._windows[k]

    def evict_expired(self) -> None:
        """Force an immediate sweep of expired windows (ops/tests)."""
        with self._lock:
            self._evict_expired(time.monotonic(), force=True)

    def reset(self) -> None:
        """Clear all counters. Useful in tests."""
        with self._lock:
            self._windows.clear()
            self._last_evict = time.monotonic()


def _parse_limit(limit_string: str) -> tuple[int, float]:
    """Parse ``"N/period"`` into ``(count, seconds)``."""
    parts = limit_string.strip().split("/")
    if len(parts) != 2:
        raise ValueError(f"invalid limit string {limit_string!r}")
    count = int(parts[0])
    period_str = parts[1].lower()
    period_map = {
        "second": 1.0,
        "minute": 60.0,
        "hour": 3600.0,
        "day": 86400.0,
    }
    if period_str not in period_map:
        raise ValueError(f"unknown period {period_str!r} in {limit_string!r}")
    return count, period_map[period_str]


def _get_ip(request, *, trust_forwarded_for: bool = False) -> str:
    """Extract the client IP from the request.

    By default the ``X-Forwarded-For`` header is ignored and the socket peer
    (``request.client.host``) is used, so the header cannot be spoofed to
    bypass rate limits. When ``trust_forwarded_for`` is True (server is behind a
    trusted proxy), the right-most ``X-Forwarded-For`` entry is used: that is
    the value the trusted proxy appended, which a caller cannot forge.
    """
    if trust_forwarded_for:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
            if parts:
                return parts[-1]
    client = getattr(request, "client", None)
    if client and client.host:
        return client.host
    return "unknown"
