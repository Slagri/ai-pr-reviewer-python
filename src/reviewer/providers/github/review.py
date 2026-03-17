"""GitHub review posting, check runs, and file operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import structlog

from reviewer.exceptions import ProviderError
from reviewer.models import (
    FileDiff,
    Finding,
    PullRequest,
    Review,
    ReviewConfig,
    Severity,
)

if TYPE_CHECKING:
    from reviewer.providers.github.client import GitHubAuth

logger = structlog.get_logger()

GITHUB_API_BASE = "https://api.github.com"


class GitHubReviewService:
    """Handles GitHub API operations: diffs, file content, reviews, check runs."""

    def __init__(
        self,
        auth: GitHubAuth,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._auth = auth
        self._http_client = http_client

    async def _headers(self, installation_id: int) -> dict[str, str]:
        """Build authenticated headers for GitHub API requests."""
        token = await self._auth.get_installation_token(installation_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        installation_id: int,
        *,
        json_data: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        """Make an authenticated GitHub API request."""
        headers = await self._headers(installation_id)
        if accept is not None:
            headers["Accept"] = accept

        url = f"{GITHUB_API_BASE}{path}"
        try:
            response = await self._http_client.request(
                method,
                url,
                headers=headers,
                json=json_data,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"github API error: {exc.response.status_code} on {method} {path}",
                provider="github",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"github API request failed: {exc}",
                provider="github",
            ) from exc

        return response

    async def get_diff(
        self,
        pr: PullRequest,
        installation_id: int,
    ) -> tuple[FileDiff, ...]:
        """Fetch the list of changed files for a pull request."""
        files: list[FileDiff] = []
        page = 1

        while True:
            response = await self._request(
                "GET",
                f"/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}/files?per_page=100&page={page}",
                installation_id,
            )
            data = response.json()
            if not data:
                break

            for f in data:
                files.append(
                    FileDiff(
                        path=f["filename"],
                        status=f["status"],
                        additions=f.get("additions", 0),
                        deletions=f.get("deletions", 0),
                        patch=f.get("patch", ""),
                        previous_path=f.get("previous_filename"),
                    )
                )

            if len(data) < 100:
                break
            page += 1

        return tuple(files)

    async def get_file_content(
        self,
        pr: PullRequest,
        path: str,
        ref: str,
        installation_id: int,
    ) -> str:
        """Fetch raw file content at a specific ref."""
        response = await self._request(
            "GET",
            f"/repos/{pr.owner}/{pr.repo}/contents/{path}?ref={ref}",
            installation_id,
            accept="application/vnd.github.raw+json",
        )
        return response.text

    async def post_review(
        self,
        review: Review,
        installation_id: int,
    ) -> None:
        """Post a review with inline comments and summary."""
        pr = review.pull_request
        comments = _build_review_comments(review.findings)

        # Determine review event based on severity
        event = _determine_review_event(review.findings)

        body: dict[str, Any] = {
            "body": review.summary,
            "event": event,
            "commit_id": pr.head_sha,
        }
        if comments:
            body["comments"] = comments

        await self._request(
            "POST",
            f"/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}/reviews",
            installation_id,
            json_data=body,
        )

        logger.info(
            "review posted",
            pr=pr.number,
            findings=len(review.findings),
            review_event=event,
        )

    async def create_check_run(
        self,
        pr: PullRequest,
        name: str,
        installation_id: int,
    ) -> str:
        """Create an in-progress check run. Returns the check run ID."""
        response = await self._request(
            "POST",
            f"/repos/{pr.owner}/{pr.repo}/check-runs",
            installation_id,
            json_data={
                "name": name,
                "head_sha": pr.head_sha,
                "status": "in_progress",
            },
        )
        data = response.json()
        check_id: int = data["id"]
        return str(check_id)

    async def update_check_run(
        self,
        pr: PullRequest,
        check_run_id: str,
        installation_id: int,
        *,
        status: str,
        conclusion: str | None = None,
        summary: str = "",
    ) -> None:
        """Update an existing check run with status and conclusion."""
        body: dict[str, Any] = {"status": status}
        if conclusion is not None:
            body["conclusion"] = conclusion
        if summary:
            body["output"] = {
                "title": "AI PR Review",
                "summary": summary,
            }

        await self._request(
            "PATCH",
            f"/repos/{pr.owner}/{pr.repo}/check-runs/{check_run_id}",
            installation_id,
            json_data=body,
        )

    async def get_repo_config(
        self,
        pr: PullRequest,
        installation_id: int,
    ) -> ReviewConfig:
        """Fetch .reviewer.yaml from the repo. Returns defaults if not found."""
        import yaml

        try:
            content = await self.get_file_content(
                pr, ".reviewer.yaml", pr.base_ref, installation_id
            )
        except ProviderError as exc:
            if exc.status_code == 404:
                return ReviewConfig()
            raise

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            logger.warning("invalid .reviewer.yaml, using defaults", pr=pr.number)
            return ReviewConfig()

        if not isinstance(data, dict):
            return ReviewConfig()

        return ReviewConfig(
            enabled=data.get("enabled", True),
            ignore_paths=tuple(data.get("ignore_paths", [])),
            ignore_authors=tuple(data.get("ignore_authors", [])),
            max_files=data.get("max_files", 50),
            severity_threshold=data.get("severity_threshold", "low"),
            extra_instructions=data.get("extra_instructions", ""),
        )


def _build_review_comments(findings: tuple[Finding, ...]) -> list[dict[str, Any]]:
    """Convert findings to GitHub review comment format."""
    comments: list[dict[str, Any]] = []
    for finding in findings:
        body = f"**{finding.severity.upper()}** ({finding.category}): {finding.message}"
        if finding.suggestion:
            body += f"\n\n**Suggestion:** {finding.suggestion}"

        comments.append(
            {
                "path": finding.path,
                "line": finding.line,
                "body": body,
                "side": "RIGHT",
            }
        )
    return comments


def _determine_review_event(findings: tuple[Finding, ...]) -> str:
    """Determine the review event (COMMENT vs REQUEST_CHANGES) based on severity."""
    if not findings:
        return "COMMENT"

    has_critical = any(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in findings)
    return "REQUEST_CHANGES" if has_critical else "COMMENT"
