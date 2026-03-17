"""Context cancellation for superseded reviews.

When a new push arrives for the same PR, any in-flight review for the
previous commit should be cancelled to avoid posting stale results.
"""

from __future__ import annotations

import asyncio

import structlog

logger = structlog.get_logger()


def _pr_key(owner: str, repo: str, number: int) -> str:
    return f"{owner}/{repo}#{number}"


class CancellationRegistry:
    """Tracks cancellation tokens for in-flight reviews.

    Each PR can have at most one active review. When a new review starts,
    any previous review for the same PR is cancelled via its asyncio.Event.
    """

    def __init__(self) -> None:
        self._active: dict[str, asyncio.Event] = {}

    def register(self, owner: str, repo: str, number: int) -> asyncio.Event:
        """Register a new review and cancel any existing one for this PR.

        Returns a cancellation event. The review should periodically check
        `event.is_set()` and abort if True.
        """
        key = _pr_key(owner, repo, number)

        existing = self._active.get(key)
        if existing is not None:
            logger.info("cancelling superseded review", pr_key=key)
            existing.set()

        cancel_event = asyncio.Event()
        self._active[key] = cancel_event
        return cancel_event

    def complete(self, owner: str, repo: str, number: int) -> None:
        """Mark a review as complete, removing it from the registry."""
        key = _pr_key(owner, repo, number)
        self._active.pop(key, None)

    def is_cancelled(self, owner: str, repo: str, number: int) -> bool:
        """Check if the review for a PR has been cancelled."""
        key = _pr_key(owner, repo, number)
        event = self._active.get(key)
        if event is None:
            return False
        return event.is_set()

    @property
    def active_count(self) -> int:
        """Number of in-flight reviews."""
        return len(self._active)

    def cancel_all(self) -> int:
        """Cancel all in-flight reviews. Returns count cancelled."""
        count = 0
        for event in self._active.values():
            if not event.is_set():
                event.set()
                count += 1
        self._active.clear()
        return count
