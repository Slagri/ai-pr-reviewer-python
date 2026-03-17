"""Tests for review cancellation."""

from __future__ import annotations

from reviewer.queue.cancel import CancellationRegistry


class TestCancellationRegistry:
    """Test PR review cancellation."""

    def test_register_returns_event(self) -> None:
        reg = CancellationRegistry()
        event = reg.register("org", "repo", 1)
        assert not event.is_set()

    def test_register_cancels_previous(self) -> None:
        reg = CancellationRegistry()
        first = reg.register("org", "repo", 1)
        _second = reg.register("org", "repo", 1)

        assert first.is_set()  # First was cancelled
        assert not _second.is_set()  # Second is active

    def test_different_prs_independent(self) -> None:
        reg = CancellationRegistry()
        event1 = reg.register("org", "repo", 1)
        event2 = reg.register("org", "repo", 2)

        assert not event1.is_set()
        assert not event2.is_set()

    def test_complete_removes_entry(self) -> None:
        reg = CancellationRegistry()
        reg.register("org", "repo", 1)
        reg.complete("org", "repo", 1)

        assert reg.active_count == 0

    def test_complete_nonexistent_no_error(self) -> None:
        reg = CancellationRegistry()
        reg.complete("org", "repo", 999)  # Should not raise

    def test_is_cancelled(self) -> None:
        reg = CancellationRegistry()
        reg.register("org", "repo", 1)
        assert reg.is_cancelled("org", "repo", 1) is False

        # Supersede it
        reg.register("org", "repo", 1)
        # The old event was set, but the registry now points to the new one
        assert reg.is_cancelled("org", "repo", 1) is False

    def test_is_cancelled_nonexistent(self) -> None:
        reg = CancellationRegistry()
        assert reg.is_cancelled("org", "repo", 999) is False

    def test_active_count(self) -> None:
        reg = CancellationRegistry()
        reg.register("org", "repo", 1)
        reg.register("org", "repo", 2)
        assert reg.active_count == 2

        reg.complete("org", "repo", 1)
        assert reg.active_count == 1

    def test_cancel_all(self) -> None:
        reg = CancellationRegistry()
        e1 = reg.register("org", "repo", 1)
        e2 = reg.register("org", "repo", 2)

        count = reg.cancel_all()
        assert count == 2
        assert e1.is_set()
        assert e2.is_set()
        assert reg.active_count == 0

    def test_cancel_all_empty(self) -> None:
        reg = CancellationRegistry()
        assert reg.cancel_all() == 0
