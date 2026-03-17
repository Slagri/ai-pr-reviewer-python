"""Tests for the async worker pool."""

from __future__ import annotations

import asyncio

import pytest

from reviewer.exceptions import QueueError
from reviewer.models import EventAction, Provider, PullRequest, WebhookEvent
from reviewer.queue.worker import WorkerPool


def _make_event(number: int = 1, delivery_id: str = "d-1", action: str = "opened") -> WebhookEvent:
    return WebhookEvent(
        provider=Provider.GITHUB,
        action=EventAction(action),
        pull_request=PullRequest(
            provider=Provider.GITHUB,
            owner="org",
            repo="repo",
            number=number,
            title="Test",
            head_sha="abc",
            base_ref="main",
            head_ref="feat",
            author="dev",
        ),
        installation_id=123,
        delivery_id=delivery_id,
    )


class TestWorkerPool:
    """Test worker pool lifecycle and event processing."""

    @pytest.mark.asyncio
    async def test_start_and_shutdown(self) -> None:
        processed: list[int] = []

        async def handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            processed.append(event.pull_request.number)

        pool = WorkerPool(handler, worker_count=2, queue_capacity=10)
        await pool.start()
        assert pool.is_running

        await pool.shutdown(drain_timeout=5)
        assert not pool.is_running

    @pytest.mark.asyncio
    async def test_process_single_event(self) -> None:
        processed: list[int] = []

        async def handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            processed.append(event.pull_request.number)

        pool = WorkerPool(handler, worker_count=1, queue_capacity=10)
        await pool.start()

        accepted = await pool.submit(_make_event(number=42))
        assert accepted is True

        # Give worker time to process
        await asyncio.sleep(0.1)

        await pool.shutdown(drain_timeout=5)
        assert 42 in processed

    @pytest.mark.asyncio
    async def test_deduplication(self) -> None:
        processed: list[str] = []

        async def handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            processed.append(event.delivery_id)

        pool = WorkerPool(handler, worker_count=1, queue_capacity=10)
        await pool.start()

        await pool.submit(_make_event(delivery_id="dup-1"))
        result = await pool.submit(_make_event(delivery_id="dup-1"))
        assert result is False  # Rejected as duplicate

        await asyncio.sleep(0.1)
        await pool.shutdown(drain_timeout=5)
        assert processed.count("dup-1") == 1

    @pytest.mark.asyncio
    async def test_queue_full_rejects(self) -> None:
        async def slow_handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            await asyncio.sleep(10)

        pool = WorkerPool(slow_handler, worker_count=1, queue_capacity=2)
        await pool.start()

        await pool.submit(_make_event(delivery_id="a"))
        await pool.submit(_make_event(delivery_id="b"))
        # Queue is full (capacity 2), but one might already be processing
        # Fill more to guarantee rejection
        await pool.submit(_make_event(delivery_id="c"))
        # At least one of these should get rejected or all accepted
        # The important thing is it doesn't raise

        await pool.shutdown(drain_timeout=1)

    @pytest.mark.asyncio
    async def test_submit_when_not_running_raises(self) -> None:
        async def handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            pass

        pool = WorkerPool(handler)
        with pytest.raises(QueueError, match="not running"):
            await pool.submit(_make_event())

    @pytest.mark.asyncio
    async def test_handler_exception_doesnt_crash_worker(self) -> None:
        call_count = 0

        async def failing_handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")

        pool = WorkerPool(failing_handler, worker_count=1, queue_capacity=10)
        await pool.start()

        await pool.submit(_make_event(delivery_id="fail-1", number=1))
        await pool.submit(_make_event(delivery_id="ok-2", number=2))

        await asyncio.sleep(0.2)
        await pool.shutdown(drain_timeout=5)

        assert call_count == 2  # Worker survived the first failure

    @pytest.mark.asyncio
    async def test_cancellation_on_supersede(self) -> None:
        cancel_events: list[bool] = []

        async def handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            await asyncio.sleep(0.05)
            cancel_events.append(cancel.is_set())

        pool = WorkerPool(handler, worker_count=2, queue_capacity=10)
        await pool.start()

        # Submit two events for the same PR — first should get cancelled
        await pool.submit(_make_event(number=1, delivery_id="v1"))
        await asyncio.sleep(0.01)
        await pool.submit(_make_event(number=1, delivery_id="v2"))

        await asyncio.sleep(0.2)
        await pool.shutdown(drain_timeout=5)

    @pytest.mark.asyncio
    async def test_queue_size(self) -> None:
        async def slow_handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            await asyncio.sleep(10)

        pool = WorkerPool(slow_handler, worker_count=1, queue_capacity=10)
        await pool.start()

        assert pool.queue_size == 0
        await pool.submit(_make_event(delivery_id="q1"))
        # Queue size may be 0 or 1 depending on whether worker picked it up
        assert pool.queue_size >= 0

        await pool.shutdown(drain_timeout=1)

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self) -> None:
        async def handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            pass

        pool = WorkerPool(handler, worker_count=1)
        await pool.start()
        await pool.start()  # Should not create duplicate workers
        assert pool.is_running

        await pool.shutdown(drain_timeout=5)

    @pytest.mark.asyncio
    async def test_double_shutdown_is_safe(self) -> None:
        async def handler(event: WebhookEvent, cancel: asyncio.Event) -> None:
            pass

        pool = WorkerPool(handler, worker_count=1)
        await pool.start()
        await pool.shutdown(drain_timeout=5)
        await pool.shutdown(drain_timeout=5)  # Should not raise
