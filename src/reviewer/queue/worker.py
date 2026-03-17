"""Asyncio worker pool with bounded queue.

Processes webhook events concurrently with configurable parallelism.
Supports graceful shutdown: drains the queue and waits for in-flight work.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import structlog

from reviewer.exceptions import QueueError
from reviewer.models import WebhookEvent
from reviewer.queue.cancel import CancellationRegistry
from reviewer.queue.dedup import Deduplicator

logger = structlog.get_logger()

ReviewHandler = Callable[[WebhookEvent, asyncio.Event], Awaitable[None]]


class WorkerPool:
    """Bounded async worker pool for processing webhook events.

    Features:
    - Bounded queue to apply backpressure
    - Configurable worker count
    - Webhook deduplication
    - Cancellation of superseded reviews
    - Graceful shutdown with drain timeout
    """

    def __init__(
        self,
        handler: ReviewHandler,
        *,
        worker_count: int = 5,
        queue_capacity: int = 100,
        dedup_ttl: int = 300,
    ) -> None:
        self._handler = handler
        self._worker_count = worker_count
        self._queue: asyncio.Queue[WebhookEvent] = asyncio.Queue(maxsize=queue_capacity)
        self._dedup = Deduplicator(ttl_seconds=dedup_ttl)
        self._cancellation = CancellationRegistry()
        self._workers: list[asyncio.Task[None]] = []
        self._running = False
        self._shutdown_event = asyncio.Event()

    @property
    def dedup(self) -> Deduplicator:
        return self._dedup

    @property
    def cancellation(self) -> CancellationRegistry:
        return self._cancellation

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the worker pool."""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()

        for i in range(self._worker_count):
            task = asyncio.create_task(self._worker_loop(i), name=f"review-worker-{i}")
            self._workers.append(task)

        logger.info("worker pool started", workers=self._worker_count)

    async def submit(self, event: WebhookEvent) -> bool:
        """Submit a webhook event for processing.

        Returns True if accepted, False if rejected (duplicate or full).
        Raises QueueError if the pool is not running.
        """
        if not self._running:
            raise QueueError("worker pool is not running")

        if self._dedup.is_duplicate(event.delivery_id):
            logger.debug("duplicate webhook skipped", delivery_id=event.delivery_id)
            return False

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("queue full, rejecting event", delivery_id=event.delivery_id)
            return False

        logger.info(
            "event queued",
            delivery_id=event.delivery_id,
            pr=event.pull_request.number,
            queue_size=self._queue.qsize(),
        )
        return True

    async def shutdown(self, drain_timeout: int = 30) -> None:
        """Gracefully shut down the worker pool.

        Waits for queued items to drain, then cancels workers.
        """
        if not self._running:
            return

        logger.info("shutting down worker pool", drain_timeout=drain_timeout)
        self._running = False
        self._shutdown_event.set()

        # Cancel all in-flight reviews
        cancelled = self._cancellation.cancel_all()
        if cancelled:
            logger.info("cancelled in-flight reviews", count=cancelled)

        # Wait for queue to drain (with timeout)
        try:
            async with asyncio.timeout(drain_timeout):
                await self._queue.join()
        except TimeoutError:
            logger.warning("shutdown timeout, cancelling workers")

        # Cancel worker tasks
        for task in self._workers:
            task.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        logger.info("worker pool stopped")

    async def _worker_loop(self, worker_id: int) -> None:
        """Main loop for a single worker."""
        logger.debug("worker started", worker_id=worker_id)

        while self._running or not self._queue.empty():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            pr = event.pull_request
            cancel_event = self._cancellation.register(pr.owner, pr.repo, pr.number)

            try:
                await self._handler(event, cancel_event)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "review failed",
                    pr=pr.number,
                    delivery_id=event.delivery_id,
                )
            finally:
                self._cancellation.complete(pr.owner, pr.repo, pr.number)
                self._queue.task_done()

        logger.debug("worker stopped", worker_id=worker_id)
