"""Shared Pydantic models for the PR review agent.

These models are provider-agnostic and used throughout the pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Provider(StrEnum):
    """Supported SCM providers."""

    GITHUB = "github"
    AZURE_DEVOPS = "azuredevops"


class EventAction(StrEnum):
    """PR event actions we handle."""

    OPENED = "opened"
    SYNCHRONIZE = "synchronize"
    REOPENED = "reopened"


class Severity(StrEnum):
    """Finding severity levels, ordered from most to least severe."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Category(StrEnum):
    """Finding categories for classification."""

    SECURITY = "security"
    BUG = "bug"
    PERFORMANCE = "performance"
    STYLE = "style"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    MAINTAINABILITY = "maintainability"


class PullRequest(BaseModel, frozen=True):
    """Provider-agnostic pull request representation."""

    provider: Provider
    owner: str
    repo: str
    number: int
    title: str
    body: str = ""
    head_sha: str
    base_ref: str
    head_ref: str
    author: str
    draft: bool = False
    url: str = ""


class FileDiff(BaseModel, frozen=True):
    """A single file's diff within a pull request."""

    path: str
    status: str = Field(description="added, modified, removed, renamed")
    additions: int = 0
    deletions: int = 0
    patch: str = ""
    previous_path: str | None = None


class Finding(BaseModel, frozen=True):
    """A single review finding for a specific location in the code."""

    path: str
    line: int
    severity: Severity
    category: Category
    message: str
    suggestion: str = ""


class Review(BaseModel, frozen=True):
    """Complete review result from the AI agent."""

    pull_request: PullRequest
    findings: tuple[Finding, ...] = ()
    summary: str = ""
    model: str = ""
    duration_seconds: float = 0.0
    iterations: int = 0
    token_usage: TokenUsage = Field(default_factory=lambda: TokenUsage())


class TokenUsage(BaseModel, frozen=True):
    """Token usage tracking for a review."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class WebhookEvent(BaseModel, frozen=True):
    """Parsed webhook event, provider-agnostic."""

    provider: Provider
    action: EventAction
    pull_request: PullRequest
    installation_id: int | None = None
    delivery_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] = Field(default_factory=dict)


class ReviewConfig(BaseModel, frozen=True):
    """Per-repository review configuration from .reviewer.yaml."""

    enabled: bool = True
    ignore_paths: tuple[str, ...] = ()
    ignore_authors: tuple[str, ...] = ()
    max_files: int = 50
    severity_threshold: Severity = Severity.LOW
    extra_instructions: str = ""
