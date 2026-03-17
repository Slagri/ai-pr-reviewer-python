"""Tests for webhook deduplication."""

from __future__ import annotations

import time

from reviewer.queue.dedup import Deduplicator


class TestDeduplicator:
    """Test TTL-based deduplication."""

    def test_first_seen_is_not_duplicate(self) -> None:
        dedup = Deduplicator()
        assert dedup.is_duplicate("delivery-1") is False

    def test_second_seen_is_duplicate(self) -> None:
        dedup = Deduplicator()
        dedup.is_duplicate("delivery-1")
        assert dedup.is_duplicate("delivery-1") is True

    def test_different_ids_not_duplicate(self) -> None:
        dedup = Deduplicator()
        dedup.is_duplicate("delivery-1")
        assert dedup.is_duplicate("delivery-2") is False

    def test_expired_entry_not_duplicate(self) -> None:
        dedup = Deduplicator(ttl_seconds=1)
        dedup.is_duplicate("delivery-1")

        # Simulate time passing beyond TTL
        dedup._seen["delivery-1"] = time.monotonic() - 1
        assert dedup.is_duplicate("delivery-1") is False

    def test_empty_delivery_id_not_duplicate(self) -> None:
        dedup = Deduplicator()
        assert dedup.is_duplicate("") is False
        assert dedup.is_duplicate("") is False

    def test_size_tracking(self) -> None:
        dedup = Deduplicator()
        assert dedup.size == 0
        dedup.is_duplicate("a")
        dedup.is_duplicate("b")
        assert dedup.size == 2

    def test_clear(self) -> None:
        dedup = Deduplicator()
        dedup.is_duplicate("a")
        dedup.is_duplicate("b")
        dedup.clear()
        assert dedup.size == 0
        assert dedup.is_duplicate("a") is False

    def test_eviction_removes_expired(self) -> None:
        dedup = Deduplicator(ttl_seconds=1)
        dedup._eviction_interval = 0  # Force eviction on every check

        dedup.is_duplicate("old")
        dedup._seen["old"] = time.monotonic() - 10  # Expired

        dedup.is_duplicate("new")  # Triggers eviction
        assert "old" not in dedup._seen
        assert "new" in dedup._seen
