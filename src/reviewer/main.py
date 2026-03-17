"""FastAPI application factory and lifecycle management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from reviewer.config import Settings
from reviewer.middleware.logging import RequestLoggingMiddleware
from reviewer.middleware.ratelimit import RateLimitMiddleware
from reviewer.middleware.signature import SignatureVerificationMiddleware
from reviewer.server.dependencies import get_settings
from reviewer.server.routes import health_router, webhook_router

logger = structlog.get_logger()


def _configure_structlog(settings: Settings) -> None:
    """Configure structlog for JSON output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.log_level.value == "debug"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(settings.log_level.value),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """App lifecycle: start worker pool on startup, drain on shutdown."""
    settings = get_settings()
    _configure_structlog(settings)

    logger.info(
        "starting AI PR reviewer",
        github_enabled=settings.github_enabled,
        azdo_enabled=settings.azdo_enabled,
        workers=settings.worker_count,
    )

    # Worker pool will be initialized when providers are ready
    app.state.worker_pool = None

    yield

    # Shutdown
    if app.state.worker_pool is not None:
        await app.state.worker_pool.shutdown(drain_timeout=settings.shutdown_timeout)

    logger.info("AI PR reviewer stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="AI PR Reviewer",
        description="AI-powered pull request review agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware (order matters: outermost first)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        max_requests=60,
        window_seconds=60,
    )
    app.add_middleware(
        SignatureVerificationMiddleware,
        github_secret=settings.github_webhook_secret,
        azdo_secret=settings.azdo_webhook_secret,
    )

    # Routes
    app.include_router(health_router)
    app.include_router(webhook_router)

    return app
