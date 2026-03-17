"""Per-IP token bucket rate limiting middleware."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = structlog.get_logger()

DEFAULT_RATE = 60  # requests per window
DEFAULT_WINDOW = 60  # seconds


class TokenBucket:
    """Simple token bucket for a single client."""

    __slots__ = ("_last_refill", "_max_tokens", "_refill_rate", "_tokens")

    def __init__(self, max_tokens: int, refill_rate: float) -> None:
        self._tokens = float(max_tokens)
        self._max_tokens = max_tokens
        self._refill_rate = refill_rate
        self._last_refill = time.monotonic()

    def consume(self) -> bool:
        """Try to consume one token. Returns True if allowed."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting using token bucket algorithm."""

    def __init__(
        self,
        app: object,
        *,
        max_requests: int = DEFAULT_RATE,
        window_seconds: int = DEFAULT_WINDOW,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._max_requests = max_requests
        self._refill_rate = max_requests / window_seconds
        self._buckets: dict[str, TokenBucket] = {}
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = max(window_seconds * 2, 120)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        client_ip = self._get_client_ip(request)
        bucket = self._get_or_create_bucket(client_ip)

        if not bucket.consume():
            logger.warning("rate limited", client_ip=client_ip, path=request.url.path)
            return JSONResponse(
                {"error": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(DEFAULT_WINDOW)},
            )

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = request.client
        if client is not None:
            return client.host
        return "unknown"

    def _get_or_create_bucket(self, client_ip: str) -> TokenBucket:
        self._maybe_cleanup()
        bucket = self._buckets.get(client_ip)
        if bucket is None:
            bucket = TokenBucket(self._max_requests, self._refill_rate)
            self._buckets[client_ip] = bucket
        return bucket

    def _maybe_cleanup(self) -> None:
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._buckets.clear()
        self._last_cleanup = now
