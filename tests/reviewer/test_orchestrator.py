"""Tests for multi-agent orchestrator."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from reviewer.models import FileDiff, Provider, PullRequest, ReviewConfig
from reviewer.reviewer.orchestrator import (
    _collect_worker_findings,
    _compute_verdict,
    _deduplicate_findings,
    run_orchestrated_review,
)
from reviewer.reviewer.prompts import WorkerRole
from reviewer.reviewer.tools import ToolExecutor
from reviewer.reviewer.trace import AgentTrace


def _make_pr() -> PullRequest:
    return PullRequest(
        provider=Provider.GITHUB,
        owner="org",
        repo="repo",
        number=42,
        title="Add feature",
        head_sha="abc123",
        base_ref="main",
        head_ref="feat/test",
        author="dev",
    )


def _make_finding(
    path: str = "src/main.py",
    line: int = 10,
    severity: str = "warning",
    category: str = "bugs",
    worker: str = "quality",
) -> dict[str, Any]:
    return {
        "path": path,
        "line": line,
        "severity": severity,
        "category": category,
        "title": f"{severity} issue at {path}:{line}",
        "message": "description",
        "_worker": worker,
    }


class TestDeduplicateFindings:
    """Test line-proximity deduplication."""

    def test_no_duplicates(self) -> None:
        findings = [
            _make_finding(path="a.py", line=10),
            _make_finding(path="b.py", line=20),
        ]
        result = _deduplicate_findings(findings)
        assert len(result) == 2

    def test_same_file_same_line_deduplicates(self) -> None:
        findings = [
            _make_finding(path="a.py", line=10, severity="warning", worker="quality"),
            _make_finding(path="a.py", line=10, severity="critical", worker="security"),
        ]
        result = _deduplicate_findings(findings)
        assert len(result) == 1
        assert result[0]["severity"] == "critical"  # Higher severity wins

    def test_same_file_nearby_lines_deduplicates(self) -> None:
        findings = [
            _make_finding(path="a.py", line=10, severity="suggestion"),
            _make_finding(path="a.py", line=12, severity="warning"),
        ]
        result = _deduplicate_findings(findings)
        assert len(result) == 1
        assert result[0]["severity"] == "warning"

    def test_same_file_distant_lines_kept(self) -> None:
        findings = [
            _make_finding(path="a.py", line=10),
            _make_finding(path="a.py", line=100),
        ]
        result = _deduplicate_findings(findings)
        assert len(result) == 2

    def test_different_files_not_deduped(self) -> None:
        findings = [
            _make_finding(path="a.py", line=10),
            _make_finding(path="b.py", line=10),
        ]
        result = _deduplicate_findings(findings)
        assert len(result) == 2

    def test_lower_severity_kept_when_first(self) -> None:
        findings = [
            _make_finding(severity="critical"),
            _make_finding(severity="suggestion"),
        ]
        result = _deduplicate_findings(findings)
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    def test_empty_findings(self) -> None:
        assert _deduplicate_findings([]) == []


class TestComputeVerdict:
    """Test verdict computation from findings."""

    def test_critical_returns_request_changes(self) -> None:
        findings = [_make_finding(severity="critical")]
        assert _compute_verdict(findings) == "request_changes"

    def test_warning_returns_comment(self) -> None:
        findings = [_make_finding(severity="warning")]
        assert _compute_verdict(findings) == "comment"

    def test_suggestion_returns_approve(self) -> None:
        findings = [_make_finding(severity="suggestion")]
        assert _compute_verdict(findings) == "approve"

    def test_praise_returns_approve(self) -> None:
        findings = [_make_finding(severity="praise")]
        assert _compute_verdict(findings) == "approve"

    def test_empty_returns_approve(self) -> None:
        assert _compute_verdict([]) == "approve"

    def test_mixed_highest_wins(self) -> None:
        findings = [
            _make_finding(severity="praise"),
            _make_finding(severity="warning", path="b.py"),
            _make_finding(severity="critical", path="c.py"),
        ]
        assert _compute_verdict(findings) == "request_changes"


class TestCollectWorkerFindings:
    """Test finding collection from worker results."""

    def test_collects_from_all_workers(self) -> None:
        results = {
            WorkerRole.SECURITY: (
                {"findings": [{"path": "a.py", "severity": "critical"}]},
                AgentTrace(),
            ),
            WorkerRole.QUALITY: (
                {"findings": [{"path": "b.py", "severity": "warning"}]},
                AgentTrace(),
            ),
            WorkerRole.PERFORMANCE: (
                {"findings": []},
                AgentTrace(),
            ),
        }
        findings = _collect_worker_findings(results)
        assert len(findings) == 2
        assert findings[0]["_worker"] == "security"
        assert findings[1]["_worker"] == "quality"

    def test_empty_results(self) -> None:
        results = {role: ({"findings": []}, AgentTrace()) for role in WorkerRole}
        assert _collect_worker_findings(results) == []


class TestRunOrchestratedReview:
    """Test full orchestrated review flow."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def mock_executor(self) -> ToolExecutor:
        async def get_file(path: str) -> str:
            return f"content of {path}"

        return ToolExecutor(get_file_fn=get_file)

    def _make_response(self, findings: list[dict[str, Any]], summary: str = "test") -> MagicMock:
        content = json.dumps(
            {
                "findings": findings,
                "summary": summary,
                "verdict": "comment",
            }
        )
        mock = MagicMock()
        choice = MagicMock()
        choice.finish_reason = "stop"
        choice.message.content = f"```json\n{content}\n```"
        choice.message.tool_calls = None
        mock.choices = [choice]
        mock.usage = MagicMock()
        mock.usage.prompt_tokens = 100
        mock.usage.completion_tokens = 50
        return mock

    @pytest.mark.asyncio
    async def test_full_orchestration(
        self, mock_client: AsyncMock, mock_executor: ToolExecutor
    ) -> None:
        """Workers run in parallel, synthesis produces final review."""
        # 3 worker calls + 1 synthesis call = 4 total
        mock_client.chat.completions.create.side_effect = [
            self._make_response(
                [{"path": "a.py", "line": 1, "severity": "critical", "category": "security"}],
                "security issue",
            ),
            self._make_response(
                [{"path": "a.py", "line": 1, "severity": "warning", "category": "bugs"}],
                "quality issue",
            ),
            self._make_response([], "no perf issues"),
            # Synthesis
            self._make_response(
                [{"path": "a.py", "line": 1, "severity": "critical", "category": "security"}],
                "Found 1 critical security issue",
            ),
        ]

        pr = _make_pr()
        diffs = (FileDiff(path="a.py", status="modified", additions=5, deletions=2, patch="diff"),)

        result, _trace = await run_orchestrated_review(
            client=mock_client,
            model="gpt-4o",
            pr=pr,
            diffs=diffs,
            config=ReviewConfig(),
            tool_executor=mock_executor,
        )

        assert len(result.get("findings", [])) >= 1
        assert _trace.total_tokens > 0
        # 4 API calls: 3 workers + 1 synthesis
        assert mock_client.chat.completions.create.call_count == 4

    @pytest.mark.asyncio
    async def test_synthesis_failure_falls_back(
        self, mock_client: AsyncMock, mock_executor: ToolExecutor
    ) -> None:
        """If synthesis fails, raw worker findings are returned."""
        worker_response = self._make_response(
            [{"path": "a.py", "line": 1, "severity": "warning", "category": "bugs"}],
        )
        # 3 workers succeed, synthesis fails
        mock_client.chat.completions.create.side_effect = [
            worker_response,
            worker_response,
            self._make_response([]),
            MagicMock(
                choices=[
                    MagicMock(
                        finish_reason="stop",
                        message=MagicMock(content="not json", tool_calls=None),
                    )
                ],
                usage=MagicMock(prompt_tokens=0, completion_tokens=0),
            ),
        ]

        pr = _make_pr()
        diffs = (FileDiff(path="a.py", status="modified"),)

        result, _trace = await run_orchestrated_review(
            client=mock_client,
            model="gpt-4o",
            pr=pr,
            diffs=diffs,
            config=ReviewConfig(),
            tool_executor=mock_executor,
        )

        # Fallback should still produce findings
        assert "findings" in result

    @pytest.mark.asyncio
    async def test_cancellation_stops_workers(
        self, mock_client: AsyncMock, mock_executor: ToolExecutor
    ) -> None:
        """Cancelled event aborts before worker API calls."""
        cancel = asyncio.Event()
        cancel.set()

        pr = _make_pr()
        diffs = (FileDiff(path="a.py", status="modified"),)

        # Workers should all fail with cancellation, synthesis should get empty findings
        # The agent loop raises AgentError on cancel, which the worker catches
        result, _trace = await run_orchestrated_review(
            client=mock_client,
            model="gpt-4o",
            pr=pr,
            diffs=diffs,
            config=ReviewConfig(),
            tool_executor=mock_executor,
            cancel_event=cancel,
        )

        # All workers failed, synthesis gets empty findings
        # Synthesis also cancelled, falls back to empty
        assert result.get("findings") == [] or "cancelled" in result.get("summary", "").lower()
