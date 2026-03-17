"""Webhook signature verification middleware.

Verifies HMAC-SHA256 signatures on incoming webhook requests before
they reach route handlers. Rejects requests with invalid signatures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from reviewer.exceptions import SignatureError
from reviewer.providers.github.webhook import verify_signature

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pydantic import SecretStr

logger = structlog.get_logger()

WEBHOOK_PATH_PREFIX = "/webhook/"


class SignatureVerificationMiddleware(BaseHTTPMiddleware):
    """Verify webhook signatures on POST requests to /webhook/ paths."""

    def __init__(
        self,
        app: object,
        *,
        github_secret: SecretStr | None = None,
        azdo_secret: SecretStr | None = None,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._github_secret = github_secret
        self._azdo_secret = azdo_secret

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method != "POST" or not request.url.path.startswith(WEBHOOK_PATH_PREFIX):
            return await call_next(request)

        provider = request.url.path.removeprefix(WEBHOOK_PATH_PREFIX).split("/")[0]

        if provider == "github" and self._github_secret is not None:
            body = await request.body()
            signature = request.headers.get("X-Hub-Signature-256", "")
            try:
                verify_signature(body, signature, self._github_secret.get_secret_value())
            except SignatureError as exc:
                logger.warning("webhook signature failed", provider="github", error=str(exc))
                return JSONResponse({"error": "invalid signature"}, status_code=401)

        return await call_next(request)
