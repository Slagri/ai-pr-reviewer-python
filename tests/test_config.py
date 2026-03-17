"""Tests for application configuration."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from reviewer.config import LogLevel, Settings


class TestSettings:
    """Test Settings loading and validation."""

    def _make_settings(self, **overrides: object) -> Settings:
        """Create Settings with required defaults + overrides."""
        defaults: dict[str, object] = {
            "azure_openai_endpoint": "https://test.openai.azure.com",
        }
        return Settings(**(defaults | overrides))

    def test_minimal_valid_config(self) -> None:
        settings = self._make_settings()
        assert settings.azure_openai_endpoint == "https://test.openai.azure.com"
        assert settings.azure_openai_deployment == "gpt-5.4"
        assert settings.port == 8000
        assert settings.log_level == LogLevel.INFO

    def test_endpoint_strips_trailing_slash(self) -> None:
        settings = self._make_settings(azure_openai_endpoint="https://test.openai.azure.com/")
        assert settings.azure_openai_endpoint == "https://test.openai.azure.com"

    def test_endpoint_strips_whitespace(self) -> None:
        settings = self._make_settings(azure_openai_endpoint="  https://test.openai.azure.com  ")
        assert settings.azure_openai_endpoint == "https://test.openai.azure.com"

    def test_endpoint_rejects_http(self) -> None:
        with pytest.raises(ValidationError, match="must start with https://"):
            self._make_settings(azure_openai_endpoint="http://insecure.com")

    def test_endpoint_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            Settings()

    def test_api_key_is_secret(self) -> None:
        settings = self._make_settings(azure_openai_api_key="sk-test-key")
        assert isinstance(settings.azure_openai_api_key, SecretStr)
        assert "sk-test-key" not in repr(settings)
        assert settings.azure_openai_api_key.get_secret_value() == "sk-test-key"

    @pytest.mark.parametrize(
        ("port", "valid"),
        [
            (8000, True),
            (1, True),
            (65535, True),
            (0, False),
            (65536, False),
            (-1, False),
        ],
    )
    def test_port_validation(self, port: int, valid: bool) -> None:
        if valid:
            settings = self._make_settings(port=port)
            assert settings.port == port
        else:
            with pytest.raises(ValidationError):
                self._make_settings(port=port)

    @pytest.mark.parametrize(
        "level",
        [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR],
    )
    def test_log_levels(self, level: LogLevel) -> None:
        settings = self._make_settings(log_level=level)
        assert settings.log_level == level

    def test_worker_count_bounds(self) -> None:
        settings = self._make_settings(worker_count=10)
        assert settings.worker_count == 10

        with pytest.raises(ValidationError):
            self._make_settings(worker_count=0)

        with pytest.raises(ValidationError):
            self._make_settings(worker_count=51)

    def test_queue_capacity_bounds(self) -> None:
        settings = self._make_settings(queue_capacity=500)
        assert settings.queue_capacity == 500

        with pytest.raises(ValidationError):
            self._make_settings(queue_capacity=0)

    def test_max_agent_iterations_bounds(self) -> None:
        with pytest.raises(ValidationError):
            self._make_settings(max_agent_iterations=0)

        with pytest.raises(ValidationError):
            self._make_settings(max_agent_iterations=51)


class TestGitHubEnabled:
    """Test github_enabled property."""

    def _make_settings(self, **overrides: object) -> Settings:
        defaults: dict[str, object] = {
            "azure_openai_endpoint": "https://test.openai.azure.com",
        }
        return Settings(**(defaults | overrides))

    def test_disabled_by_default(self) -> None:
        settings = self._make_settings()
        assert settings.github_enabled is False

    def test_enabled_with_key(self) -> None:
        settings = self._make_settings(
            github_app_id="12345",
            github_private_key="-----BEGIN RSA PRIVATE KEY-----\ntest",
        )
        assert settings.github_enabled is True

    def test_enabled_with_key_path(self) -> None:
        settings = self._make_settings(
            github_app_id="12345",
            github_private_key_path="/path/to/key.pem",
        )
        assert settings.github_enabled is True

    def test_disabled_without_app_id(self) -> None:
        settings = self._make_settings(
            github_private_key="test-key",
        )
        assert settings.github_enabled is False


class TestAzdoEnabled:
    """Test azdo_enabled property."""

    def _make_settings(self, **overrides: object) -> Settings:
        defaults: dict[str, object] = {
            "azure_openai_endpoint": "https://test.openai.azure.com",
        }
        return Settings(**(defaults | overrides))

    def test_disabled_by_default(self) -> None:
        settings = self._make_settings()
        assert settings.azdo_enabled is False

    def test_enabled_with_full_config(self) -> None:
        settings = self._make_settings(
            azdo_organization="myorg",
            azdo_pat="test-pat-token",
        )
        assert settings.azdo_enabled is True

    def test_disabled_without_pat(self) -> None:
        settings = self._make_settings(azdo_organization="myorg")
        assert settings.azdo_enabled is False
