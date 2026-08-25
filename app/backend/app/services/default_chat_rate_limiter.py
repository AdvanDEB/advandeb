"""
Process-global sliding-window rate limiter for the default chat API key.

Enforces DEFAULT_CHAT_RPM across all concurrent users. The window is 60 s;
once the bucket fills requests are rejected immediately rather than queued,
which avoids latency pile-up under the expected ≤2 concurrent users.
"""
from __future__ import annotations

import asyncio
from collections import deque
from time import monotonic

from app.core.config import settings


class _SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float = 60.0) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Return True if the request is within quota; False if rate-limited."""
        async with self._lock:
            now = monotonic()
            cutoff = now - self._window
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._max:
                return False
            self._timestamps.append(now)
            return True

    @property
    def remaining(self) -> int:
        now = monotonic()
        cutoff = now - self._window
        active = sum(1 for t in self._timestamps if t >= cutoff)
        return max(0, self._max - active)


# Singleton — instantiated once at import time with the configured RPM cap.
# asyncio.Lock() is safe to create outside a running event loop in Python 3.10+.
default_rate_limiter = _SlidingWindowRateLimiter(
    max_requests=settings.DEFAULT_CHAT_RPM
)
