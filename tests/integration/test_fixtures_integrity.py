"""Integration tests that verify fixtures match expected model shapes.

These catch drift between our Pydantic models and the fixture data
that simulates real API responses. If a fixture no longer matches
what the code expects, these tests fail BEFORE the unit tests do,
making the root cause obvious.
"""

from __future__ import annotations

import json

import pytest

from reviewer.models import (
    Category,
    EventAction,
    Finding,
    Provider,
    PullRequest,
    Severity,
)
from tests.fixtures import (
    load_github_fixture,
    load_openai_fixture,
    load_streaming_chunks,
)


class TestGitHubFixtureIntegrity:
    """Verify GitHub fixtures can produce valid PullRequest models."""

    @pytest.mark.parametrize(
        "fixture_name",
        ["pull_request_opened", "pull_request_synchronize"],
    )
    def test_fixture_to_pull_request(self, fixture_name: str) -> None:
        """Each GitHub fixture must map to a valid PullRequest."""
        raw = load_github_fixture(fixture_name)
        pr_data = raw["pull_request"]

        pr = PullRequest(
            provider=Provider.GITHUB,
            owner=raw["repository"]["owner"]["login"],
            repo=raw["repository"]["name"],
            number=pr_data["number"],
            title=pr_data["title"],
            body=pr_data["body"],
            head_sha=pr_data["head"]["sha"],
            base_ref=pr_data["base"]["ref"],
            head_ref=pr_data["head"]["ref"],
            author=pr_data["user"]["login"],
            draft=pr_data["draft"],
            url=pr_data["html_url"],
        )
        assert pr.number == 42
        assert pr.provider == Provider.GITHUB
        assert pr.owner == "acme-corp"

    @pytest.mark.parametrize(
        ("fixture_name", "expected_action"),
        [
            ("pull_request_opened", "opened"),
            ("pull_request_synchronize", "synchronize"),
        ],
    )
    def test_fixture_action_maps_to_event_action(
        self, fixture_name: str, expected_action: str
    ) -> None:
        raw = load_github_fixture(fixture_name)
        action = EventAction(raw["action"])
        assert action == expected_action

    def test_fixture_has_installation_id(self) -> None:
        raw = load_github_fixture("pull_request_opened")
        assert raw["installation"]["id"] == 98765


class TestOpenAIFixtureIntegrity:
    """Verify OpenAI fixtures match the shapes our agent code expects."""

    def test_tool_call_response_shape(self) -> None:
        """Tool call response must have the fields the agent loop reads."""
        raw = load_openai_fixture("tool_call_response")
        choice = raw["choices"][0]

        assert choice["finish_reason"] == "tool_calls"
        assert choice["message"]["content"] is None

        tool_calls = choice["message"]["tool_calls"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["type"] == "function"
        assert tool_calls[0]["function"]["name"] == "get_file_content"

        args = json.loads(tool_calls[0]["function"]["arguments"])
        assert "path" in args

    def test_multi_tool_call_response_shape(self) -> None:
        """Multiple tool calls in a single response."""
        raw = load_openai_fixture("multi_tool_call_response")
        tool_calls = raw["choices"][0]["message"]["tool_calls"]
        assert len(tool_calls) == 2

        names = {tc["function"]["name"] for tc in tool_calls}
        assert names == {"get_file_content", "search_codebase"}

    def test_final_review_response_parses_to_findings(self) -> None:
        """Final review response JSON must parse into Finding models."""
        raw = load_openai_fixture("final_review_response")
        content = raw["choices"][0]["message"]["content"]
        assert raw["choices"][0]["finish_reason"] == "stop"

        # Extract JSON from markdown code block
        json_str = content.strip().removeprefix("```json\n").removesuffix("\n```")
        review_data = json.loads(json_str)

        assert "findings" in review_data
        assert "summary" in review_data
        assert len(review_data["findings"]) == 3

        # Each finding must be valid
        for f_data in review_data["findings"]:
            finding = Finding(
                path=f_data["path"],
                line=f_data["line"],
                severity=Severity(f_data["severity"]),
                category=Category(f_data["category"]),
                message=f_data["message"],
                suggestion=f_data.get("suggestion", ""),
            )
            assert finding.path.startswith("src/")
            assert finding.line > 0

    def test_streaming_tool_call_reassembly(self) -> None:
        """Streaming chunks must reassemble into a complete tool call.

        This is the critical AI integration test — the agent receives
        tool call arguments in fragments across multiple SSE chunks.
        If reassembly is broken, the agent loop fails silently.
        """
        chunks = load_streaming_chunks("streaming_tool_call_chunks")

        # Simulate what the agent loop does: concatenate arguments
        tool_call_id: str | None = None
        function_name: str | None = None
        arguments_buffer: list[str] = []

        for chunk in chunks:
            delta = chunk["choices"][0]["delta"]

            if "tool_calls" in delta:
                tc = delta["tool_calls"][0]

                if "id" in tc:
                    tool_call_id = tc["id"]
                if "function" in tc:
                    if "name" in tc["function"]:
                        function_name = tc["function"]["name"]
                    if "arguments" in tc["function"]:
                        arguments_buffer.append(tc["function"]["arguments"])

            finish_reason = chunk["choices"][0].get("finish_reason")

        assert tool_call_id == "call_stream_abc"
        assert function_name == "get_file_content"
        assert finish_reason == "tool_calls"

        full_args = "".join(arguments_buffer)
        parsed = json.loads(full_args)
        assert parsed == {"path": "src/auth/register.py"}

    def test_streaming_final_review_reassembly(self) -> None:
        """Streaming final review must reassemble into parseable JSON."""
        chunks = load_streaming_chunks("streaming_final_review_chunks")

        content_parts: list[str] = []
        for chunk in chunks:
            delta = chunk["choices"][0]["delta"]
            if delta.get("content"):
                content_parts.append(delta["content"])

        full_content = "".join(content_parts)
        json_str = full_content.strip().removeprefix("```json\n").removesuffix("\n```")
        review_data = json.loads(json_str)

        assert "findings" in review_data
        assert len(review_data["findings"]) == 1
        assert review_data["findings"][0]["severity"] == "high"

    def test_error_fixtures_have_expected_shape(self) -> None:
        """Error fixtures must have status_code and error body."""
        rate_limit = load_openai_fixture("error_rate_limit")
        assert rate_limit["status_code"] == 429
        assert "error" in rate_limit["body"]
        assert rate_limit["body"]["error"]["code"] == "rate_limit_exceeded"

        content_filter = load_openai_fixture("error_content_filter")
        assert content_filter["status_code"] == 400
        assert content_filter["body"]["error"]["code"] == "content_filter"

    def test_usage_tracking_fields_present(self) -> None:
        """All non-streaming fixtures must include usage data."""
        for name in ["tool_call_response", "multi_tool_call_response", "final_review_response"]:
            raw = load_openai_fixture(name)
            usage = raw["usage"]
            assert usage["prompt_tokens"] > 0
            assert usage["completion_tokens"] > 0
            assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
