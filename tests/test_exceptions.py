"""Tests for custom exception hierarchy."""

from __future__ import annotations

import pytest

from reviewer.exceptions import (
    AgentError,
    ConfigError,
    ProviderError,
    QueueError,
    ReviewerError,
    SignatureError,
    ToolError,
    WebhookError,
)


class TestExceptionHierarchy:
    """Verify exception inheritance chain."""

    @pytest.mark.parametrize(
        "exc_class",
        [
            ConfigError,
            ProviderError,
            WebhookError,
            SignatureError,
            AgentError,
            ToolError,
            QueueError,
        ],
    )
    def test_all_inherit_from_reviewer_error(self, exc_class: type[ReviewerError]) -> None:
        assert issubclass(exc_class, ReviewerError)

    def test_signature_error_inherits_webhook_error(self) -> None:
        assert issubclass(SignatureError, WebhookError)

    def test_tool_error_inherits_agent_error(self) -> None:
        assert issubclass(ToolError, AgentError)


class TestProviderError:
    """Test ProviderError attributes."""

    def test_attributes(self) -> None:
        err = ProviderError("api call failed", provider="github", status_code=404)
        assert str(err) == "api call failed"
        assert err.provider == "github"
        assert err.status_code == 404

    def test_optional_status_code(self) -> None:
        err = ProviderError("timeout", provider="azuredevops")
        assert err.status_code is None


class TestToolError:
    """Test ToolError attributes."""

    def test_attributes(self) -> None:
        err = ToolError("file not found", tool_name="get_file_content")
        assert str(err) == "file not found"
        assert err.tool_name == "get_file_content"
