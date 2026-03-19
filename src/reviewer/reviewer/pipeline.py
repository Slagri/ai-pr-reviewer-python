"""Review pipeline: orchestrates the full review flow.

check run → fetch config → fetch diffs → run agent → post review → update check run
"""

from __future__ import annotations

import asyncio
import fnmatch
from typing import TYPE_CHECKING, Any

import structlog

from reviewer.exceptions import ProviderError
from reviewer.models import Review, WebhookEvent
from reviewer.reviewer.agent import build_review_from_agent_result, run_review_agent
from reviewer.reviewer.prompts import SYSTEM_PROMPT, build_user_prompt
from reviewer.reviewer.tools import ToolExecutor

if TYPE_CHECKING:
    from openai import AsyncAzureOpenAI

    from reviewer.models import PullRequest
    from reviewer.providers.github.review import GitHubReviewService

logger = structlog.get_logger()


async def run_review_pipeline(
    *,
    event: WebhookEvent,
    review_service: GitHubReviewService,
    openai_client: AsyncAzureOpenAI,
    model: str,
    max_iterations: int = 10,
    max_files: int = 50,
    cancel_event: asyncio.Event | None = None,
) -> Review:
    """Execute the full review pipeline for a webhook event.

    Steps:
    1. Create check run (in_progress)
    2. Fetch repo config (.reviewer.yaml)
    3. Fetch PR diffs
    4. Build prompts and tool executor
    5. Run AI agent loop
    6. Post review with findings
    7. Update check run (completed)
    """
    pr = event.pull_request
    installation_id = event.installation_id

    if installation_id is None:
        raise ProviderError(
            "missing installation_id for GitHub review",
            provider="github",
        )

    log = logger.bind(pr=pr.number, owner=pr.owner, repo=pr.repo)

    # Step 1: Create check run
    check_run_id: str | None = None
    try:
        check_run_id = await review_service.create_check_run(pr, "AI PR Review", installation_id)
        log.info("check run created", check_run_id=check_run_id)
    except ProviderError:
        log.warning("failed to create check run, continuing without it")

    try:
        review = await _execute_review(
            pr=pr,
            installation_id=installation_id,
            review_service=review_service,
            openai_client=openai_client,
            model=model,
            max_iterations=max_iterations,
            max_files=max_files,
            cancel_event=cancel_event,
            log=log,
        )

        # Step 6: Post review
        await review_service.post_review(review, installation_id)
        log.info(
            "review complete",
            findings=len(review.findings),
            duration=review.duration_seconds,
            iterations=review.iterations,
        )

        # Step 7: Update check run to success
        if check_run_id is not None:
            conclusion = "action_required" if review.findings else "success"
            await review_service.update_check_run(
                pr,
                check_run_id,
                installation_id,
                status="completed",
                conclusion=conclusion,
                summary=review.summary,
            )

        return review

    except Exception as exc:
        log.error("review pipeline failed", error=str(exc))

        # Update check run to failure
        if check_run_id is not None:
            try:
                await review_service.update_check_run(
                    pr,
                    check_run_id,
                    installation_id,
                    status="completed",
                    conclusion="failure",
                    summary=f"Review failed: {exc}",
                )
            except ProviderError:
                log.warning("failed to update check run on error")

        raise


async def _execute_review(
    *,
    pr: PullRequest,
    installation_id: int,
    review_service: GitHubReviewService,
    openai_client: AsyncAzureOpenAI,
    model: str,
    max_iterations: int,
    max_files: int,
    cancel_event: asyncio.Event | None = None,
    log: Any,
) -> Review:
    """Execute the review (steps 2-5), separated for clean error handling."""
    # Step 2: Fetch repo config
    config = await review_service.get_repo_config(pr, installation_id)
    if not config.enabled:
        log.info("review disabled by repo config")
        return Review(pull_request=pr, summary="Review disabled by .reviewer.yaml")

    # Step 3: Fetch diffs
    diffs = await review_service.get_diff(pr, installation_id)
    effective_max = min(max_files, config.max_files)

    if len(diffs) > effective_max:
        log.warning(
            "too many files, truncating",
            total=len(diffs),
            limit=effective_max,
        )
        diffs = diffs[:effective_max]

    # Filter ignored paths
    if config.ignore_paths:
        diffs = tuple(
            d for d in diffs if not any(fnmatch.fnmatch(d.path, p) for p in config.ignore_paths)
        )

    if not diffs:
        log.info("no reviewable files after filtering")
        return Review(pull_request=pr, summary="No reviewable files in this PR")

    # Step 4: Build prompts and executor
    user_prompt = build_user_prompt(pr, diffs, config)

    async def get_file(path: str) -> str:
        return await review_service.get_file_content(pr, path, pr.head_sha, installation_id)

    tool_executor = ToolExecutor(get_file_fn=get_file)

    # Step 5: Run agent
    review_data, trace = await run_review_agent(
        client=openai_client,
        model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tool_executor=tool_executor,
        max_iterations=max_iterations,
        cancel_event=cancel_event,
    )

    return build_review_from_agent_result(review_data, trace, pr, model)
