"""Multi-agent review orchestrator.

Runs three specialized workers in parallel (security, quality, performance),
deduplicates their findings, then synthesizes a final cohesive review.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from reviewer.exceptions import AgentError
from reviewer.reviewer.agent import run_review_agent
from reviewer.reviewer.prompts import (
    SYNTHESIS_SYSTEM_PROMPT,
    WORKER_PROMPTS,
    WORKER_TOOLS,
    WorkerRole,
    build_synthesis_prompt,
    build_user_prompt,
)
from reviewer.reviewer.trace import AgentTrace

if TYPE_CHECKING:
    from openai import AsyncAzureOpenAI

    from reviewer.models import FileDiff, PullRequest, ReviewConfig
    from reviewer.reviewer.tools import ToolExecutor

logger = structlog.get_logger()

# Workers get fewer iterations than single-agent mode
WORKER_MAX_ITERATIONS = 5
LINE_PROXIMITY_THRESHOLD = 3


async def run_orchestrated_review(
    *,
    client: AsyncAzureOpenAI,
    model: str,
    pr: PullRequest,
    diffs: tuple[FileDiff, ...],
    config: ReviewConfig,
    tool_executor: ToolExecutor,
    cancel_event: asyncio.Event | None = None,
) -> tuple[dict[str, Any], AgentTrace]:
    """Run a multi-agent review with parallel workers and synthesis.

    Flow:
    1. Run security, quality, and performance workers in parallel
    2. Collect and deduplicate findings
    3. Run synthesis pass to produce final cohesive review
    """
    user_prompt = build_user_prompt(pr, diffs, config)

    # Run workers in parallel
    worker_results = await _run_workers(
        client=client,
        model=model,
        user_prompt=user_prompt,
        tool_executor=tool_executor,
        cancel_event=cancel_event,
    )

    # Collect all findings from workers
    all_findings = _collect_worker_findings(worker_results)

    # Aggregate token usage from workers
    combined_trace = AgentTrace(model=model)
    for _role, (_result, trace) in worker_results.items():
        combined_trace.total_prompt_tokens += trace.total_prompt_tokens
        combined_trace.total_completion_tokens += trace.total_completion_tokens
        for step in trace.steps:
            combined_trace.steps.append(step)

    # Deduplicate findings by line proximity
    deduped = _deduplicate_findings(all_findings)

    logger.info(
        "worker findings collected",
        total=len(all_findings),
        after_dedup=len(deduped),
    )

    # Synthesis pass — single call, no tool loop
    synthesis_prompt = build_synthesis_prompt(pr, diffs, deduped)

    try:
        synthesis_result, synthesis_trace = await run_review_agent(
            client=client,
            model=model,
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            user_prompt=synthesis_prompt,
            tool_executor=tool_executor,
            max_iterations=1,
            cancel_event=cancel_event,
        )
    except AgentError:
        logger.warning("synthesis failed, falling back to raw worker findings")
        synthesis_result = {
            "findings": deduped,
            "summary": f"Review found {len(deduped)} issues across specialized reviewers",
            "verdict": _compute_verdict(deduped),
        }
        synthesis_trace = AgentTrace(model=model)

    # Merge synthesis trace into combined
    combined_trace.total_prompt_tokens += synthesis_trace.total_prompt_tokens
    combined_trace.total_completion_tokens += synthesis_trace.total_completion_tokens
    combined_trace.finish()

    return synthesis_result, combined_trace


async def _run_workers(
    *,
    client: AsyncAzureOpenAI,
    model: str,
    user_prompt: str,
    tool_executor: ToolExecutor,
    cancel_event: asyncio.Event | None = None,
) -> dict[WorkerRole, tuple[dict[str, Any], AgentTrace]]:
    """Run all workers in parallel, return results per role."""
    results: dict[WorkerRole, tuple[dict[str, Any], AgentTrace]] = {}

    async def run_worker(role: WorkerRole) -> None:
        worker_prompt = WORKER_PROMPTS[role]
        allowed_tools = WORKER_TOOLS[role]

        # Filter tool executor to only allowed tools for this worker
        filtered_executor = _filter_tool_executor(tool_executor, allowed_tools)

        try:
            result, trace = await run_review_agent(
                client=client,
                model=model,
                system_prompt=worker_prompt,
                user_prompt=user_prompt,
                tool_executor=filtered_executor,
                max_iterations=WORKER_MAX_ITERATIONS,
                cancel_event=cancel_event,
            )
            results[role] = (result, trace)
            logger.info(
                "worker complete",
                role=role.value,
                findings=len(result.get("findings", [])),
            )
        except AgentError as exc:
            logger.warning("worker failed", role=role.value, error=str(exc))
            results[role] = ({"findings": [], "summary": f"Worker failed: {exc}"}, AgentTrace())

    tasks = [run_worker(role) for role in WorkerRole]
    await asyncio.gather(*tasks)

    return results


def _filter_tool_executor(
    executor: ToolExecutor,
    allowed_tools: tuple[str, ...],
) -> ToolExecutor:
    """Create a tool executor that only allows specific tools."""
    from reviewer.reviewer.tools import ToolExecutor as _ToolExecutor

    original_execute = executor.execute

    async def filtered_execute(tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name not in allowed_tools:
            return f"tool '{tool_name}' is not available for this reviewer"
        return await original_execute(tool_name, arguments)

    filtered = _ToolExecutor(get_file_fn=executor._get_file)
    filtered.execute = filtered_execute  # type: ignore[method-assign]
    return filtered


def _collect_worker_findings(
    results: dict[WorkerRole, tuple[dict[str, Any], AgentTrace]],
) -> list[dict[str, Any]]:
    """Flatten findings from all workers into a single list."""
    all_findings: list[dict[str, Any]] = []
    for role, (result, _trace) in results.items():
        for finding in result.get("findings", []):
            finding["_worker"] = role.value
            all_findings.append(finding)
    return all_findings


def _deduplicate_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate findings on the same file within ±N lines.

    When two findings overlap, the higher-severity one wins.
    """
    severity_rank = {"critical": 4, "warning": 3, "suggestion": 2, "praise": 1}

    deduped: list[dict[str, Any]] = []
    for finding in findings:
        path = finding.get("path", "")
        line = finding.get("line", 0)
        severity = finding.get("severity", "suggestion")

        is_duplicate = False
        for i, existing in enumerate(deduped):
            if (
                existing.get("path") == path
                and abs(existing.get("line", 0) - line) <= LINE_PROXIMITY_THRESHOLD
            ):
                # Keep the higher-severity finding
                existing_rank = severity_rank.get(existing.get("severity", ""), 0)
                new_rank = severity_rank.get(severity, 0)
                if new_rank > existing_rank:
                    deduped[i] = finding
                is_duplicate = True
                break

        if not is_duplicate:
            deduped.append(finding)

    return deduped


def _compute_verdict(findings: list[dict[str, Any]]) -> str:
    """Compute verdict from findings when synthesis fails."""
    severities = {f.get("severity") for f in findings}
    if "critical" in severities:
        return "request_changes"
    if "warning" in severities:
        return "comment"
    return "approve"
