"""FastAPI application factory and lifecycle management."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from openai import AsyncAzureOpenAI

from reviewer.config import Settings
from reviewer.middleware.logging import RequestLoggingMiddleware
from reviewer.middleware.ratelimit import RateLimitMiddleware
from reviewer.middleware.signature import SignatureVerificationMiddleware
from reviewer.models import WebhookEvent
from reviewer.providers.github.client import build_github_auth
from reviewer.providers.github.review import GitHubReviewService
from reviewer.queue.worker import WorkerPool
from reviewer.reviewer.pipeline import run_review_pipeline
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

    # Build providers and worker pool
    review_service, openai_client = _build_providers(settings)

    async def handle_review(event: WebhookEvent, cancel_event: asyncio.Event) -> None:
        if review_service is None or openai_client is None:
            logger.error("review handler called but providers not configured")
            return
        await run_review_pipeline(
            event=event,
            review_service=review_service,
            openai_client=openai_client,
            model=settings.review_model,
            max_iterations=settings.max_agent_iterations,
            max_files=settings.max_files_per_review,
            cancel_event=cancel_event,
        )

    pool = WorkerPool(
        handle_review,
        worker_count=settings.worker_count,
        queue_capacity=settings.queue_capacity,
    )
    await pool.start()
    app.state.worker_pool = pool

    yield

    # Shutdown
    await pool.shutdown(drain_timeout=settings.shutdown_timeout)
    logger.info("AI PR reviewer stopped")


def _build_providers(
    settings: Settings,
) -> tuple[GitHubReviewService | None, AsyncAzureOpenAI | None]:
    """Build provider clients from settings. Returns (None, None) if not configured."""
    import httpx

    if not settings.github_enabled:
        logger.warning("GitHub provider not configured, reviews will be skipped")
        return None, None

    github_auth = build_github_auth(
        app_id=settings.github_app_id or "",
        private_key=(
            settings.github_private_key.get_secret_value() if settings.github_private_key else None
        ),
        private_key_path=settings.github_private_key_path,
    )

    http_client = httpx.AsyncClient(timeout=30.0)
    review_service = GitHubReviewService(auth=github_auth, http_client=http_client)

    openai_kwargs: dict[str, Any] = {
        "azure_endpoint": settings.azure_openai_endpoint,
        "api_version": settings.azure_openai_api_version,
    }
    if settings.azure_openai_api_key is not None:
        openai_kwargs["api_key"] = settings.azure_openai_api_key.get_secret_value()
    else:
        from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

        credential = DefaultAzureCredential()
        openai_kwargs["azure_ad_token_provider"] = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )

    openai_client = AsyncAzureOpenAI(**openai_kwargs)

    return review_service, openai_client


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
