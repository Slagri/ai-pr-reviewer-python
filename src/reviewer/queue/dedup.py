"""TTL-based webhook deduplication.

Prevents processing the same webhook delivery twice. Uses an in-memory
dict with expiration — suitable for single-instance deployments.
"""

from __future__ import annotations

import time
from typing import Final

DEFAULT_TTL_SECONDS: Final[int] = 300  # 5 minutes


class Deduplicator:
    """TTL-based deduplication for webhook delivery IDs.

    Thread-safe for single-threaded asyncio usage.
    Periodically evicts expired entries to prevent memory growth.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._seen: dict[str, float] = {}
        self._last_eviction = time.monotonic()
        self._eviction_interval = max(ttl_seconds, 60)

    def is_duplicate(self, delivery_id: str) -> bool:
        """Check if a delivery ID has been seen recently.

        Returns True if duplicate (should be skipped).
        Automatically records the ID if not a duplicate.
        """
        if not delivery_id:
            return False

        now = time.monotonic()
        self._maybe_evict(now)

        expires_at = self._seen.get(delivery_id)
        if expires_at is not None and now < expires_at:
            return True

        self._seen[delivery_id] = now + self._ttl
        return False

    def _maybe_evict(self, now: float) -> None:
        """Remove expired entries if enough time has passed."""
        if now - self._last_eviction < self._eviction_interval:
            return

        self._seen = {
            key: expires_at for key, expires_at in self._seen.items() if now < expires_at
        }
        self._last_eviction = now

    @property
    def size(self) -> int:
        """Number of tracked delivery IDs (including expired)."""
        return len(self._seen)

    def clear(self) -> None:
        """Remove all tracked delivery IDs."""
        self._seen.clear()
