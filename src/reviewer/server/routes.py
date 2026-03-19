"""FastAPI routes: webhook endpoints, health checks, metrics."""

from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from reviewer.config import Settings
from reviewer.exceptions import WebhookError
from reviewer.providers.github.webhook import parse_webhook
from reviewer.server.dependencies import get_settings

logger = structlog.get_logger()

health_router = APIRouter(tags=["health"])
webhook_router = APIRouter(prefix="/webhook", tags=["webhooks"])

_start_time = time.monotonic()


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — is the process running?"""
    return {"status": "ok"}


@health_router.get("/readyz")
async def readyz(settings: Settings = Depends(get_settings)) -> Response:
    """Readiness probe — is the app configured and ready to serve?"""
    checks: dict[str, bool] = {
        "config_loaded": True,
        "github_configured": settings.github_enabled,
        "azdo_configured": settings.azdo_enabled,
    }
    all_ok = checks["config_loaded"]
    status_code = 200 if all_ok else 503
    return JSONResponse(
        content={"status": "ready" if all_ok else "not ready", "checks": checks},
        status_code=status_code,
    )


@health_router.get("/metrics")
async def metrics() -> dict[str, Any]:
    """Basic operational metrics."""
    uptime = time.monotonic() - _start_time
    return {
        "uptime_seconds": round(uptime, 1),
    }


@webhook_router.post("/github")
async def github_webhook(request: Request) -> Response:
    """Receive GitHub webhook events.

    Signature verification is handled by middleware.
    This route parses the event and submits it to the worker pool.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    event_type = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")

    try:
        event = parse_webhook(body, event_type, delivery_id)
    except WebhookError as exc:
        logger.warning("webhook parse error", error=str(exc))
        return JSONResponse({"error": str(exc)}, status_code=400)

    if event is None:
        return JSONResponse({"status": "ignored"})

    # Submit to worker pool (injected via app state in main.py)
    pool = request.app.state.worker_pool
    if pool is None:
        logger.error("worker pool not initialized")
        return JSONResponse({"error": "service unavailable"}, status_code=503)

    accepted = await pool.submit(event)
    if not accepted:
        return JSONResponse({"status": "rejected", "reason": "duplicate or queue full"})

    return JSONResponse({"status": "queued", "delivery_id": delivery_id})
