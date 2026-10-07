"""HTTP hardening for the public demo: response headers and a rate limit.

Both are deliberately small. The demo runs as a single process on one free
CPU, so an in-memory limiter is enough to keep one client from starving the
others; a multi-replica deployment would need a shared store instead
(ADR-0008).
"""

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping

# The web UI loads only its own files plus Google Fonts. No inline script or
# style is allowed, so injected markup cannot execute even if it slipped in.
# frame-ancestors admits huggingface.co because a Space page embeds the app in
# an iframe; any other site framing it is refused (clickjacking).
_STRICT_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self' https://huggingface.co",
    ]
)

# FastAPI's Swagger UI page is generated with an inline bootstrap script and
# assets from jsDelivr. It is a developer tool with no user content, so it gets
# this narrower exception instead of weakening the policy for the whole app.
_DOCS_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "img-src 'self' data: https://fastapi.tiangolo.com",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'self' https://huggingface.co",
    ]
)

DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect"})

_COMMON_HEADERS: Mapping[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def security_headers(path: str) -> dict[str, str]:
    """The headers every response for ``path`` carries.

    Args:
        path: The request path; only the API docs get the relaxed policy.
    """
    csp = _DOCS_CSP if path in DOCS_PATHS else _STRICT_CSP
    return {**_COMMON_HEADERS, "Content-Security-Policy": csp}


class RateLimiter:
    """Sliding-window request limit per client key (typically an IP address).

    A sliding window, unlike a fixed one, cannot be gamed by sending a burst at
    the end of one minute and another at the start of the next.

    Example:
        >>> now = [0.0]
        >>> limiter = RateLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
        >>> limiter.retry_after("1.2.3.4"), limiter.retry_after("1.2.3.4")
        (None, None)
        >>> limiter.retry_after("1.2.3.4")
        60.0
        >>> now[0] = 60.0
        >>> limiter.retry_after("1.2.3.4") is None
        True
    """

    def __init__(
        self,
        limit: int = 30,
        window_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = 10_000,
    ) -> None:
        """Create a limiter.

        Args:
            limit: Requests allowed per client within one window.
            window_seconds: Length of the sliding window.
            clock: Monotonic time source (injectable for tests).
            max_clients: Clients tracked at once; bounds memory under a flood
                of distinct addresses.

        Raises:
            ValueError: If a bound is not positive.
        """
        if limit < 1 or window_seconds <= 0 or max_clients < 1:
            raise ValueError("limit, window_seconds and max_clients must be positive")
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._max_clients = max_clients
        self._requests: dict[str, deque[float]] = {}
        # Uvicorn runs middleware on one event loop, but the limiter is a plain
        # object that may be shared with threads; the lock keeps it correct anywhere.
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        """Requests allowed per client within one window."""
        return self._limit

    def retry_after(self, key: str) -> float | None:
        """Record a request from ``key`` unless it is over the limit.

        Args:
            key: The client identity.

        Returns:
            ``None`` if the request is allowed (and counted), otherwise the
            seconds until the oldest counted request leaves the window.
        """
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            times = self._requests.get(key)
            if times is None:
                self._evict(cutoff)
                times = self._requests[key] = deque()
            while times and times[0] <= cutoff:
                times.popleft()
            if len(times) >= self._limit:
                return times[0] - cutoff
            times.append(now)
            return None

    def _evict(self, cutoff: float) -> None:
        """Make room for a new client: drop idle ones, then the oldest tracked."""
        if len(self._requests) < self._max_clients:
            return
        idle = [key for key, times in self._requests.items() if not times or times[-1] <= cutoff]
        for key in idle:
            del self._requests[key]
        while len(self._requests) >= self._max_clients:
            del self._requests[next(iter(self._requests))]
