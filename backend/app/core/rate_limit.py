"""In-process sliding-window rate limiter.

This deliberately avoids a Redis dependency so the application starts anywhere. Limits are
per process: when running several instances, each enforces its own window (documented in
SECURITY.md). Swap ``RateLimiter`` for a shared store if horizontal scaling is required.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from app.core.errors import AppError


class RateLimiter:
    def __init__(self, max_keys: int = 50_000):
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def hit(self, key: str, limit: int, window_seconds: float = 60.0) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""
        if limit <= 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                if len(self._hits) >= self._max_keys:
                    self._evict(now, window_seconds)
                bucket = self._hits[key] = deque()
            while bucket and now - bucket[0] >= window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = int(window_seconds - (now - bucket[0])) + 1
                return False, retry_after
            bucket.append(now)
            return True, 0

    def _evict(self, now: float, window_seconds: float) -> None:
        stale = [k for k, b in self._hits.items() if not b or now - b[-1] >= window_seconds]
        for k in stale:
            del self._hits[k]
        if len(self._hits) >= self._max_keys:  # still full: drop the oldest half
            for k in list(self._hits)[: self._max_keys // 2]:
                del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def enforce(key: str, limit: int, window_seconds: float = 60.0) -> None:
    allowed, retry_after = limiter.hit(key, limit, window_seconds)
    if not allowed:
        raise AppError(
            429,
            "rate_limited",
            "Too many requests. Please slow down.",
            headers={"Retry-After": str(retry_after)},
        )
