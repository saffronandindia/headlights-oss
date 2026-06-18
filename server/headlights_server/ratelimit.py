"""Simple per-IP rate limiting for unauthenticated endpoints.

Uses the `limits` library directly (the same backend as slowapi) so the
limiter instance is per-app rather than module-level. This lets test apps
create isolated limiters with no shared state, while production uses
a single shared in-memory store.

Usage in create_app():

    from headlights_server.ratelimit import IPRateLimiter
    limiter = IPRateLimiter()
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
    """Thread-safe, in-process, per-IP sliding-window rate limiter.

    Each (key, endpoint, window_seconds) triple gets its own counter.
    Uses a fixed window (not sliding) per period — adequate for registration
    abuse prevention and simpler to reason about than a token bucket.

    Parameters
    ----------
    enabled : bool
        Set False to disable all rate checks (useful in tests).
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._lock = RLock()
        # { (ip, endpoint, window_seconds) -> _Window }
        self._windows: dict[tuple, _Window] = defaultdict(_Window)

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
        ip = _get_ip(request)
        now = time.monotonic()
        key = (ip, endpoint_name, period)

        with self._lock:
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

    def reset(self) -> None:
        """Clear all counters. Useful in tests."""
        with self._lock:
            self._windows.clear()


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


def _get_ip(request) -> str:
    """Extract the client IP from the request (respects X-Forwarded-For)."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    client = getattr(request, "client", None)
    if client and client.host:
        return client.host
    return "unknown"
