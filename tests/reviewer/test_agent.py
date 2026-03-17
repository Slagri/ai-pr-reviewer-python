"""Tests for the AI review agent loop.

Uses mock Azure OpenAI responses to test the tool-use loop,
JSON parsing, and error handling without hitting a real API.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from reviewer.exceptions import AgentError
from reviewer.models import Provider, PullRequest, Severity
from reviewer.reviewer.agent import (
    _parse_findings,
    _parse_review_json,
    build_review_from_agent_result,
    run_review_agent,
)
from reviewer.reviewer.tools import ToolExecutor
from reviewer.reviewer.trace import AgentTrace
from tests.fixtures import load_openai_fixture


def _make_mock_response(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> MagicMock:
    """Build a mock ChatCompletion response."""
    mock = MagicMock()

    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message.content = content
    choice.message.tool_calls = None

    if tool_calls:
        choice.finish_reason = "tool_calls"
        mock_tool_calls = []
        for tc in tool_calls:
            mock_tc = MagicMock()
            mock_tc.id = tc["id"]
            mock_tc.function.name = tc["function"]["name"]
            mock_tc.function.arguments = tc["function"]["arguments"]
            mock_tool_calls.append(mock_tc)
        choice.message.tool_calls = mock_tool_calls

    mock.choices = [choice]
    mock.usage = MagicMock()
    mock.usage.prompt_tokens = prompt_tokens
    mock.usage.completion_tokens = completion_tokens

    return mock


class TestParseReviewJson:
    """Test JSON extraction from agent responses."""

    def test_bare_json(self) -> None:
        result = _parse_review_json('{"findings": [], "summary": "ok"}')
        assert result["findings"] == []
        assert result["summary"] == "ok"

    def test_json_in_code_block(self) -> None:
        content = '```json\n{"findings": [], "summary": "ok"}\n```'
        result = _parse_review_json(content)
        assert result["summary"] == "ok"

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_review_json("not json at all")

    def test_fixture_response_parses(self) -> None:
        """Verify our fixture matches what the parser expects."""
        fixture = load_openai_fixture("final_review_response")
        content = fixture["choices"][0]["message"]["content"]
        result = _parse_review_json(content)
        assert len(result["findings"]) == 3


class TestParseFindings:
    """Test finding extraction from parsed JSON."""

    def test_valid_findings(self) -> None:
        data = {
            "findings": [
                {
                    "path": "src/auth.py",
                    "line": 42,
                    "severity": "high",
                    "category": "security",
                    "message": "SQL injection",
                    "suggestion": "Use params",
                }
            ]
        }
        findings = _parse_findings(data)
        assert len(findings) == 1
        assert findings[0].severity == Severity.HIGH
        assert findings[0].path == "src/auth.py"

    def test_empty_findings(self) -> None:
        assert _parse_findings({"findings": []}) == ()
        assert _parse_findings({}) == ()

    def test_malformed_finding_skipped(self) -> None:
        data = {
            "findings": [
                {"path": "a.py", "severity": "invalid_severity", "category": "bug"},
                {
                    "path": "b.py",
                    "line": 1,
                    "severity": "low",
                    "category": "style",
                    "message": "valid",
                },
            ]
        }
        findings = _parse_findings(data)
        assert len(findings) == 1
        assert findings[0].path == "b.py"


class TestRunReviewAgent:
    """Test the agent's tool-use loop."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def mock_executor(self) -> ToolExecutor:
        async def get_file(path: str) -> str:
            return f"content of {path}"

        return ToolExecutor(get_file_fn=get_file)

    @pytest.mark.asyncio
    async def test_direct_response_no_tools(
        self, mock_client: AsyncMock, mock_executor: ToolExecutor
    ) -> None:
        """Agent returns review immediately without tool calls."""
        review_json = '```json\n{"findings": [], "summary": "Looks good!"}\n```'
        mock_client.chat.completions.create.return_value = _make_mock_response(content=review_json)

        result, trace = await run_review_agent(
            client=mock_client,
            model="gpt-5.4",
            system_prompt="You are a reviewer",
            user_prompt="Review this PR",
            tool_executor=mock_executor,
        )

        assert result["summary"] == "Looks good!"
        assert result["findings"] == []
        assert trace.model == "gpt-5.4"
        assert mock_client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_tool_call_then_response(
        self, mock_client: AsyncMock, mock_executor: ToolExecutor
    ) -> None:
        """Agent makes one tool call then returns final review."""
        # First call: tool call
        tool_response = _make_mock_response(
            tool_calls=[
                {
                    "id": "call_1",
                    "function": {
                        "name": "get_file_content",
                        "arguments": '{"path": "src/main.py"}',
                    },
                }
            ]
        )
        # Second call: final review
        review_content = (
            '```json\n{"findings": [{"path": "src/main.py", "line": 1,'
            ' "severity": "low", "category": "style", "message": "naming"}],'
            ' "summary": "Minor issue"}\n```'
        )
        final_response = _make_mock_response(content=review_content)
        mock_client.chat.completions.create.side_effect = [
            tool_response,
            final_response,
        ]

        result, trace = await run_review_agent(
            client=mock_client,
            model="gpt-5.4",
            system_prompt="Review",
            user_prompt="PR",
            tool_executor=mock_executor,
        )

        assert len(result["findings"]) == 1
        assert mock_client.chat.completions.create.call_count == 2
        assert len(trace.steps) >= 1

    @pytest.mark.asyncio
    async def test_max_iterations_exceeded(
        self, mock_client: AsyncMock, mock_executor: ToolExecutor
    ) -> None:
        """Agent should raise after exceeding max iterations."""
        # Always return tool calls
        mock_client.chat.completions.create.return_value = _make_mock_response(
            tool_calls=[
                {
                    "id": "call_loop",
                    "function": {
                        "name": "get_file_content",
                        "arguments": '{"path": "src/main.py"}',
                    },
                }
            ]
        )

        with pytest.raises(AgentError, match="max iterations"):
            await run_review_agent(
                client=mock_client,
                model="gpt-5.4",
                system_prompt="Review",
                user_prompt="PR",
                tool_executor=mock_executor,
                max_iterations=3,
            )

    @pytest.mark.asyncio
    async def test_api_error_raises(
        self, mock_client: AsyncMock, mock_executor: ToolExecutor
    ) -> None:
        """API failure should raise AgentError."""
        mock_client.chat.completions.create.side_effect = Exception("connection timeout")

        with pytest.raises(AgentError, match="API call failed"):
            await run_review_agent(
                client=mock_client,
                model="gpt-5.4",
                system_prompt="Review",
                user_prompt="PR",
                tool_executor=mock_executor,
            )

    @pytest.mark.asyncio
    async def test_invalid_json_response_raises(
        self, mock_client: AsyncMock, mock_executor: ToolExecutor
    ) -> None:
        """Non-JSON final response should raise AgentError."""
        mock_client.chat.completions.create.return_value = _make_mock_response(
            content="This is not JSON at all"
        )

        with pytest.raises(AgentError, match="parse review JSON"):
            await run_review_agent(
                client=mock_client,
                model="gpt-5.4",
                system_prompt="Review",
                user_prompt="PR",
                tool_executor=mock_executor,
            )

    @pytest.mark.asyncio
    async def test_invalid_tool_arguments(
        self, mock_client: AsyncMock, mock_executor: ToolExecutor
    ) -> None:
        """Invalid JSON in tool arguments should not crash the loop."""
        # First call: tool call with bad JSON args
        tool_response = _make_mock_response(
            tool_calls=[
                {
                    "id": "call_bad",
                    "function": {
                        "name": "get_file_content",
                        "arguments": "not valid json",
                    },
                }
            ]
        )
        # Second call: final review
        final_response = _make_mock_response(
            content='```json\n{"findings": [], "summary": "ok"}\n```'
        )
        mock_client.chat.completions.create.side_effect = [
            tool_response,
            final_response,
        ]

        result, trace = await run_review_agent(
            client=mock_client,
            model="gpt-5.4",
            system_prompt="Review",
            user_prompt="PR",
            tool_executor=mock_executor,
        )

        assert result["summary"] == "ok"
        # Should have logged the error but continued
        assert any(s.error for s in trace.steps)


class TestBuildReviewFromAgentResult:
    """Test Review model construction from agent output."""

    def test_builds_review(self) -> None:
        pr = PullRequest(
            provider=Provider.GITHUB,
            owner="org",
            repo="repo",
            number=1,
            title="Test",
            head_sha="abc",
            base_ref="main",
            head_ref="feat",
            author="dev",
        )
        data = {
            "findings": [
                {
                    "path": "a.py",
                    "line": 1,
                    "severity": "high",
                    "category": "security",
                    "message": "issue",
                }
            ],
            "summary": "Found 1 issue",
        }
        trace = AgentTrace(model="gpt-5.4")
        trace.total_prompt_tokens = 1000
        trace.total_completion_tokens = 200
        trace.finish()

        review = build_review_from_agent_result(data, trace, pr, "gpt-5.4")

        assert len(review.findings) == 1
        assert review.summary == "Found 1 issue"
        assert review.model == "gpt-5.4"
        assert review.token_usage.total_tokens == 1200
