"""
In-memory sliding-window rate limiter for the account endpoints.

Keys are (bucket, identifier) — e.g. ("login_ip", "203.0.113.7") or
("forgot_email", "x@y.z"). Limits apply per backend process: the project runs a
single backend instance; a multi-instance deployment would need a shared store
(Redis or the database) instead.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

from app.core.config import settings


class RateLimiter:
    def __init__(self, max_keys: int = 50_000):
        self._hits: dict[tuple[str, str], deque] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def hit(self, bucket: str, key: str, limit: int, window_seconds: int) -> Optional[int]:
        """
        Record one attempt. Returns None when allowed, or the number of seconds
        to wait (Retry-After) when *limit* attempts already happened in the window.
        """
        if not settings.RATE_LIMIT_ENABLED:
            return None
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault((bucket, key), deque())
            while q and q[0] <= now - window_seconds:
                q.popleft()
            if len(q) >= limit:
                return max(1, math.ceil(q[0] + window_seconds - now))
            q.append(now)
            if len(self._hits) > self._max_keys:
                self._prune(now, window_seconds)
        return None

    def _prune(self, now: float, window_seconds: int) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - window_seconds]:
            del self._hits[k]

    def forget(self, key: str) -> None:
        """Drop every counter kept for *key* (e.g. a deleted account's e-mail)."""
        with self._lock:
            for k in [k for k in self._hits if k[1] == key or k[1] == (key or "").lower()]:
                del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()

# (limit, window in seconds) per bucket
LIMITS = {
    "login_ip": (20, 60),            # many accounts from one address
    "login_email": (10, 900),        # one account (the account lock triggers earlier)
    "register_ip": (5, 3600),
    "forgot_ip": (10, 3600),
    "forgot_email": (3, 3600),
    "resend_email": (3, 3600),
    "token_ip": (20, 3600),          # password-reset token attempts
    "change_password": (5, 900),
}
