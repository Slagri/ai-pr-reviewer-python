"""Custom exception hierarchy for the PR review agent."""

from __future__ import annotations


class ReviewerError(Exception):
    """Base exception for all reviewer errors."""


class ConfigError(ReviewerError):
    """Configuration is invalid or missing."""


class ProviderError(ReviewerError):
    """Error communicating with an SCM provider (GitHub, Azure DevOps)."""

    def __init__(self, message: str, provider: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class WebhookError(ReviewerError):
    """Webhook validation or parsing failed."""


class SignatureError(WebhookError):
    """Webhook signature verification failed."""


class AgentError(ReviewerError):
    """Error during AI agent execution."""


class ToolError(AgentError):
    """A tool invocation failed."""

    def __init__(self, message: str, tool_name: str) -> None:
        super().__init__(message)
        self.tool_name = tool_name


class QueueError(ReviewerError):
    """Queue operation failed (full, shutdown, etc.)."""
