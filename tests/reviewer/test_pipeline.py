"""Integration tests for the review pipeline.

Tests the full orchestration: config fetch, diff fetch, agent loop,
review posting, check run updates — with mocked HTTP and OpenAI.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from reviewer.exceptions import AgentError, ProviderError
from reviewer.models import (
    EventAction,
    FileDiff,
    Provider,
    PullRequest,
    ReviewConfig,
    WebhookEvent,
)
from reviewer.reviewer.pipeline import run_review_pipeline


def _make_event(number: int = 42, installation_id: int = 98765) -> WebhookEvent:
    return WebhookEvent(
        provider=Provider.GITHUB,
        action=EventAction.OPENED,
        pull_request=PullRequest(
            provider=Provider.GITHUB,
            owner="acme",
            repo="api",
            number=number,
            title="Add validation",
            body="Adds input validation",
            head_sha="abc123",
            base_ref="main",
            head_ref="feat/validation",
            author="dev",
        ),
        installation_id=installation_id,
        delivery_id="d-1",
    )


def _make_mock_openai_response(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
) -> MagicMock:
    mock = MagicMock()
    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message.content = content
    choice.message.tool_calls = None

    if tool_calls:
        choice.finish_reason = "tool_calls"
        mock_tcs = []
        for tc in tool_calls:
            mock_tc = MagicMock()
            mock_tc.id = tc["id"]
            mock_tc.function.name = tc["function"]["name"]
            mock_tc.function.arguments = tc["function"]["arguments"]
            mock_tcs.append(mock_tc)
        choice.message.tool_calls = mock_tcs

    mock.choices = [choice]
    mock.usage = MagicMock()
    mock.usage.prompt_tokens = 100
    mock.usage.completion_tokens = 50
    return mock


@pytest.fixture
def mock_review_service() -> AsyncMock:
    service = AsyncMock()
    service.get_repo_config.return_value = ReviewConfig()
    service.get_diff.return_value = (
        FileDiff(
            path="src/main.py",
            status="modified",
            additions=10,
            deletions=2,
            patch="@@ -1,5 +1,13 @@\n+import os\n",
        ),
    )
    service.get_file_content.return_value = "print('hello')"
    service.create_check_run.return_value = "check-123"
    service.post_review.return_value = None
    service.update_check_run.return_value = None
    return service


@pytest.fixture
def mock_openai_client() -> AsyncMock:
    client = AsyncMock()
    review_json = json.dumps(
        {
            "findings": [
                {
                    "path": "src/main.py",
                    "line": 1,
                    "severity": "low",
                    "category": "style",
                    "message": "consider using pathlib",
                }
            ],
            "summary": "Minor style issue found",
        }
    )
    client.chat.completions.create.return_value = _make_mock_openai_response(
        content=f"```json\n{review_json}\n```"
    )
    return client


class TestRunReviewPipeline:
    """Test full pipeline orchestration."""

    @pytest.mark.asyncio
    async def test_full_pipeline_happy_path(
        self, mock_review_service: AsyncMock, mock_openai_client: AsyncMock
    ) -> None:
        event = _make_event()
        review = await run_review_pipeline(
            event=event,
            review_service=mock_review_service,
            openai_client=mock_openai_client,
            model="gpt-5.4",
        )

        assert len(review.findings) == 1
        assert review.findings[0].path == "src/main.py"
        assert review.summary == "Minor style issue found"
        assert review.model == "gpt-5.4"

        # Verify the full call chain
        mock_review_service.create_check_run.assert_called_once()
        mock_review_service.get_repo_config.assert_called_once()
        mock_review_service.get_diff.assert_called_once()
        mock_review_service.post_review.assert_called_once()
        mock_review_service.update_check_run.assert_called()

    @pytest.mark.asyncio
    async def test_pipeline_with_tool_call(
        self, mock_review_service: AsyncMock, mock_openai_client: AsyncMock
    ) -> None:
        """Agent uses a tool before producing final review."""
        review_json = json.dumps(
            {
                "findings": [],
                "summary": "Looks good after checking the file",
            }
        )

        mock_openai_client.chat.completions.create.side_effect = [
            _make_mock_openai_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "function": {
                            "name": "get_file_content",
                            "arguments": '{"path": "src/main.py"}',
                        },
                    }
                ]
            ),
            _make_mock_openai_response(content=f"```json\n{review_json}\n```"),
        ]

        event = _make_event()
        review = await run_review_pipeline(
            event=event,
            review_service=mock_review_service,
            openai_client=mock_openai_client,
            model="gpt-5.4",
        )

        assert review.findings == ()
        assert "Looks good" in review.summary
        # Agent should have fetched the file
        mock_review_service.get_file_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_missing_installation_id(
        self, mock_review_service: AsyncMock, mock_openai_client: AsyncMock
    ) -> None:
        event = _make_event()
        event = event.model_copy(update={"installation_id": None})

        with pytest.raises(ProviderError, match="missing installation_id"):
            await run_review_pipeline(
                event=event,
                review_service=mock_review_service,
                openai_client=mock_openai_client,
                model="gpt-5.4",
            )

    @pytest.mark.asyncio
    async def test_pipeline_review_disabled(
        self, mock_review_service: AsyncMock, mock_openai_client: AsyncMock
    ) -> None:
        mock_review_service.get_repo_config.return_value = ReviewConfig(enabled=False)

        event = _make_event()
        review = await run_review_pipeline(
            event=event,
            review_service=mock_review_service,
            openai_client=mock_openai_client,
            model="gpt-5.4",
        )

        assert "disabled" in review.summary.lower()
        mock_openai_client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_pipeline_no_reviewable_files(
        self, mock_review_service: AsyncMock, mock_openai_client: AsyncMock
    ) -> None:
        mock_review_service.get_diff.return_value = ()

        event = _make_event()
        review = await run_review_pipeline(
            event=event,
            review_service=mock_review_service,
            openai_client=mock_openai_client,
            model="gpt-5.4",
        )

        assert "no reviewable" in review.summary.lower()

    @pytest.mark.asyncio
    async def test_pipeline_ignored_paths_filtered(
        self, mock_review_service: AsyncMock, mock_openai_client: AsyncMock
    ) -> None:
        mock_review_service.get_repo_config.return_value = ReviewConfig(ignore_paths=("src/**",))

        event = _make_event()
        review = await run_review_pipeline(
            event=event,
            review_service=mock_review_service,
            openai_client=mock_openai_client,
            model="gpt-5.4",
        )

        assert "no reviewable" in review.summary.lower()

    @pytest.mark.asyncio
    async def test_pipeline_check_run_failure_continues(
        self, mock_review_service: AsyncMock, mock_openai_client: AsyncMock
    ) -> None:
        """Check run creation failure should not block the review."""
        mock_review_service.create_check_run.side_effect = ProviderError(
            "forbidden", provider="github", status_code=403
        )

        event = _make_event()
        review = await run_review_pipeline(
            event=event,
            review_service=mock_review_service,
            openai_client=mock_openai_client,
            model="gpt-5.4",
        )

        assert len(review.findings) == 1  # Review still ran

    @pytest.mark.asyncio
    async def test_pipeline_agent_failure_updates_check_run(
        self, mock_review_service: AsyncMock, mock_openai_client: AsyncMock
    ) -> None:
        """If the agent fails, check run should be updated to failure."""
        mock_openai_client.chat.completions.create.side_effect = Exception("API down")

        event = _make_event()
        with pytest.raises(AgentError):
            await run_review_pipeline(
                event=event,
                review_service=mock_review_service,
                openai_client=mock_openai_client,
                model="gpt-5.4",
            )

        # Check run should be updated to failure
        update_calls = mock_review_service.update_check_run.call_args_list
        assert any(call.kwargs.get("conclusion") == "failure" for call in update_calls)

    @pytest.mark.asyncio
    async def test_pipeline_cancellation(
        self, mock_review_service: AsyncMock, mock_openai_client: AsyncMock
    ) -> None:
        """Cancelled review should raise AgentError."""
        cancel = asyncio.Event()
        cancel.set()  # Already cancelled

        event = _make_event()
        with pytest.raises(AgentError, match="cancelled"):
            await run_review_pipeline(
                event=event,
                review_service=mock_review_service,
                openai_client=mock_openai_client,
                model="gpt-5.4",
                cancel_event=cancel,
            )
