"""FastAPI dependency injection providers."""

from __future__ import annotations

from functools import lru_cache

import structlog

from reviewer.config import Settings

logger = structlog.get_logger()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings from environment variables. Cached after first call."""
    return Settings()
