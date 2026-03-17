"""Application configuration via environment variables with pydantic-settings."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(StrEnum):
    """Supported log levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All secrets use SecretStr to prevent accidental logging.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Azure OpenAI
    azure_openai_endpoint: str = Field(
        description="Azure OpenAI resource endpoint URL",
    )
    azure_openai_api_key: SecretStr | None = Field(
        default=None,
        description="Azure OpenAI API key (omit for managed identity)",
    )
    azure_openai_deployment: str = Field(
        default="gpt-5.4",
        description="Azure OpenAI deployment name",
    )
    azure_openai_api_version: str = Field(
        default="2024-12-01-preview",
        description="Azure OpenAI API version",
    )

    # GitHub provider
    github_app_id: str | None = Field(
        default=None,
        description="GitHub App ID",
    )
    github_private_key: SecretStr | None = Field(
        default=None,
        description="GitHub App private key (PEM content)",
    )
    github_private_key_path: str | None = Field(
        default=None,
        description="Path to GitHub App private key file",
    )
    github_webhook_secret: SecretStr | None = Field(
        default=None,
        description="GitHub webhook HMAC secret",
    )

    # Azure DevOps provider (optional)
    azdo_organization: str | None = Field(
        default=None,
        description="Azure DevOps organization name",
    )
    azdo_pat: SecretStr | None = Field(
        default=None,
        description="Azure DevOps personal access token",
    )
    azdo_webhook_secret: SecretStr | None = Field(
        default=None,
        description="Azure DevOps webhook secret",
    )

    # Server
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: LogLevel = Field(default=LogLevel.INFO)

    # Worker pool
    worker_count: int = Field(default=5, ge=1, le=50)
    queue_capacity: int = Field(default=100, ge=1, le=10000)

    # Agent
    max_agent_iterations: int = Field(default=10, ge=1, le=50)
    max_files_per_review: int = Field(default=50, ge=1, le=500)
    review_model: str = Field(default="gpt-5.4")

    # Lifecycle
    shutdown_timeout: int = Field(default=30, ge=1, le=300)

    @field_validator("azure_openai_endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        stripped = v.strip().rstrip("/")
        if not stripped.startswith("https://"):
            raise ValueError("azure_openai_endpoint must start with https://")
        return stripped

    @property
    def github_enabled(self) -> bool:
        """Check if GitHub provider is configured."""
        return self.github_app_id is not None and (
            self.github_private_key is not None or self.github_private_key_path is not None
        )

    @property
    def azdo_enabled(self) -> bool:
        """Check if Azure DevOps provider is configured."""
        return self.azdo_organization is not None and self.azdo_pat is not None
