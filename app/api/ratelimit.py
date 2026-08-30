"""Request rate limiting.

An in-process fixed-window counter, keyed by a peppered hash of the client
address so the limiter never holds a raw IP.

The limitation is stated rather than hidden: this counts per process. Two
application containers each allow the configured rate, so the effective limit
is the configured value times the number of processes. That is acceptable for
a prototype and wrong for production, where the counter belongs in Redis so
every process shares it. The production checklist records it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.security.hashing import hash_client_address


@dataclass
class RateDecision:
    """Whether a request may proceed."""

    allowed: bool
    retry_after_seconds: int = 0


class FixedWindowLimiter:
    """Counts requests per key within a fixed window."""

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self._limit = limit
        self._window = window_seconds
        self._counts: dict[str, tuple[int, float]] = {}
        # The web server runs handlers in a thread pool, so the dictionary is
        # touched concurrently.
        self._lock = threading.Lock()

    def check(self, key: str) -> RateDecision:
        """Record a request and say whether it is allowed."""
        now = time.monotonic()
        window_start = now - (now % self._window)

        with self._lock:
            count, started = self._counts.get(key, (0, window_start))
            if started < window_start:
                count, started = 0, window_start
            count += 1
            self._counts[key] = (count, started)

            # Opportunistic cleanup, so an abandoned key does not live forever.
            # Cheap because it only runs when the table is already large.
            if len(self._counts) > 10_000:
                cutoff = window_start - self._window
                self._counts = {
                    k: v for k, v in self._counts.items() if v[1] >= cutoff
                }

        if count > self._limit:
            return RateDecision(False, retry_after_seconds=int(started + self._window - now) + 1)
        return RateDecision(True)


def client_key(client_host: str | None, fallback: str = "unknown") -> str:
    """Return a rate-limit key that is not a raw client address.

    Falls back to a shared key when the address is unavailable or hashing is
    disabled. A shared bucket is stricter than no limit at all, which is the
    correct direction to fail.
    """
    hashed = hash_client_address(client_host)
    return hashed or fallback
