"""Tests for prompt construction."""

from __future__ import annotations

from reviewer.models import (
    FileDiff,
    Provider,
    PullRequest,
    ReviewConfig,
)
from reviewer.reviewer.prompts import SYSTEM_PROMPT, build_user_prompt


class TestSystemPrompt:
    """Test system prompt content."""

    def test_contains_json_format(self) -> None:
        assert "```json" in SYSTEM_PROMPT

    def test_contains_severity_levels(self) -> None:
        assert "critical" in SYSTEM_PROMPT
        assert "high" in SYSTEM_PROMPT

    def test_contains_categories(self) -> None:
        assert "security" in SYSTEM_PROMPT
        assert "bug" in SYSTEM_PROMPT


class TestBuildUserPrompt:
    """Test user prompt construction."""

    def _make_pr(self, **overrides: object) -> PullRequest:
        defaults = {
            "provider": Provider.GITHUB,
            "owner": "org",
            "repo": "repo",
            "number": 42,
            "title": "Add validation",
            "body": "This PR adds input validation",
            "head_sha": "abc123",
            "base_ref": "main",
            "head_ref": "feat/validation",
            "author": "dev",
        }
        return PullRequest(**(defaults | overrides))  # type: ignore[arg-type]

    def test_includes_pr_metadata(self) -> None:
        pr = self._make_pr()
        diffs = (FileDiff(path="src/main.py", status="modified", additions=5, deletions=2),)
        prompt = build_user_prompt(pr, diffs, ReviewConfig())

        assert "#42" in prompt
        assert "Add validation" in prompt
        assert "dev" in prompt
        assert "feat/validation" in prompt
        assert "main" in prompt

    def test_includes_diff_content(self) -> None:
        pr = self._make_pr()
        diffs = (
            FileDiff(
                path="src/main.py",
                status="modified",
                additions=5,
                deletions=2,
                patch="@@ -1,5 +1,8 @@\n+import os\n",
            ),
        )
        prompt = build_user_prompt(pr, diffs, ReviewConfig())

        assert "src/main.py" in prompt
        assert "+import os" in prompt
        assert "+5/-2" in prompt

    def test_includes_extra_instructions(self) -> None:
        pr = self._make_pr()
        config = ReviewConfig(extra_instructions="Focus on SQL injection")
        prompt = build_user_prompt(pr, (), config)

        assert "Focus on SQL injection" in prompt

    def test_handles_empty_body(self) -> None:
        pr = self._make_pr(body="")
        prompt = build_user_prompt(pr, (), ReviewConfig())
        assert "Description" not in prompt

    def test_renamed_file_shows_previous_path(self) -> None:
        pr = self._make_pr()
        diffs = (
            FileDiff(
                path="new_name.py",
                status="renamed",
                previous_path="old_name.py",
            ),
        )
        prompt = build_user_prompt(pr, diffs, ReviewConfig())
        assert "old_name.py" in prompt

    def test_file_count_shown(self) -> None:
        pr = self._make_pr()
        diffs = (
            FileDiff(path="a.py", status="added"),
            FileDiff(path="b.py", status="modified"),
        )
        prompt = build_user_prompt(pr, diffs, ReviewConfig())
        assert "2 files" in prompt
