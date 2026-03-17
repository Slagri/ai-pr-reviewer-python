"""Tests for GitHub review posting, check runs, and file operations."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from reviewer.models import (
    Category,
    Finding,
    Provider,
    PullRequest,
    Review,
    Severity,
)
from reviewer.providers.github.client import GitHubAuth
from reviewer.providers.github.review import (
    GitHubReviewService,
    _build_review_comments,
    _determine_review_event,
)
from tests.fixtures.test_rsa_key import TEST_PRIVATE_KEY


@pytest.fixture
def github_pr() -> PullRequest:
    return PullRequest(
        provider=Provider.GITHUB,
        owner="acme-corp",
        repo="backend-api",
        number=42,
        title="Add feature",
        head_sha="abc123",
        base_ref="main",
        head_ref="feat/test",
        author="jsmith",
    )


@pytest.fixture
def github_service() -> GitHubReviewService:
    client = httpx.AsyncClient()
    auth = GitHubAuth(
        app_id="12345",
        private_key=TEST_PRIVATE_KEY,
        http_client=client,
    )
    # Pre-cache a token so tests don't need to mock token exchange
    import time

    auth._token_cache[98765] = ("test-token", time.time() + 3600)
    return GitHubReviewService(auth=auth, http_client=client)


class TestBuildReviewComments:
    """Test finding-to-comment conversion."""

    def test_single_finding(self) -> None:
        findings = (
            Finding(
                path="src/auth.py",
                line=42,
                severity=Severity.HIGH,
                category=Category.SECURITY,
                message="SQL injection risk",
                suggestion="Use parameterized queries",
            ),
        )
        comments = _build_review_comments(findings)
        assert len(comments) == 1
        assert comments[0]["path"] == "src/auth.py"
        assert comments[0]["line"] == 42
        assert "HIGH" in comments[0]["body"]
        assert "SQL injection" in comments[0]["body"]
        assert "parameterized queries" in comments[0]["body"]
        assert comments[0]["side"] == "RIGHT"

    def test_finding_without_suggestion(self) -> None:
        findings = (
            Finding(
                path="src/main.py",
                line=1,
                severity=Severity.LOW,
                category=Category.STYLE,
                message="naming convention",
            ),
        )
        comments = _build_review_comments(findings)
        assert "Suggestion" not in comments[0]["body"]

    def test_empty_findings(self) -> None:
        assert _build_review_comments(()) == []


class TestDetermineReviewEvent:
    """Test review event determination based on severity."""

    def test_no_findings_returns_comment(self) -> None:
        assert _determine_review_event(()) == "COMMENT"

    def test_critical_returns_request_changes(self) -> None:
        findings = (
            Finding(
                path="a.py",
                line=1,
                severity=Severity.CRITICAL,
                category=Category.SECURITY,
                message="critical issue",
            ),
        )
        assert _determine_review_event(findings) == "REQUEST_CHANGES"

    def test_high_returns_request_changes(self) -> None:
        findings = (
            Finding(
                path="a.py",
                line=1,
                severity=Severity.HIGH,
                category=Category.BUG,
                message="high issue",
            ),
        )
        assert _determine_review_event(findings) == "REQUEST_CHANGES"

    def test_medium_returns_comment(self) -> None:
        findings = (
            Finding(
                path="a.py",
                line=1,
                severity=Severity.MEDIUM,
                category=Category.BUG,
                message="medium issue",
            ),
        )
        assert _determine_review_event(findings) == "COMMENT"

    def test_mixed_severity_high_wins(self) -> None:
        findings = (
            Finding(
                path="a.py",
                line=1,
                severity=Severity.LOW,
                category=Category.STYLE,
                message="low",
            ),
            Finding(
                path="b.py",
                line=2,
                severity=Severity.HIGH,
                category=Category.SECURITY,
                message="high",
            ),
        )
        assert _determine_review_event(findings) == "REQUEST_CHANGES"


class TestGitHubReviewServiceGetDiff:
    """Test diff fetching with mocked HTTP."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_diff_single_page(
        self, github_pr: PullRequest, github_service: GitHubReviewService
    ) -> None:
        respx.get(
            "https://api.github.com/repos/acme-corp/backend-api/pulls/42/files",
        ).respond(
            json=[
                {
                    "filename": "src/main.py",
                    "status": "modified",
                    "additions": 10,
                    "deletions": 3,
                    "patch": "@@ -1,5 +1,12 @@",
                },
                {
                    "filename": "src/new.py",
                    "status": "added",
                    "additions": 50,
                    "deletions": 0,
                    "patch": "@@ -0,0 +1,50 @@",
                },
            ]
        )

        diffs = await github_service.get_diff(github_pr, 98765)
        assert len(diffs) == 2
        assert diffs[0].path == "src/main.py"
        assert diffs[0].status == "modified"
        assert diffs[1].path == "src/new.py"
        assert diffs[1].status == "added"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_diff_empty(
        self, github_pr: PullRequest, github_service: GitHubReviewService
    ) -> None:
        respx.get(
            "https://api.github.com/repos/acme-corp/backend-api/pulls/42/files",
        ).respond(json=[])

        diffs = await github_service.get_diff(github_pr, 98765)
        assert diffs == ()


class TestGitHubReviewServiceGetFileContent:
    """Test file content fetching."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_file_content(
        self, github_pr: PullRequest, github_service: GitHubReviewService
    ) -> None:
        respx.get(
            "https://api.github.com/repos/acme-corp/backend-api/contents/src/main.py",
        ).respond(text="print('hello')")

        content = await github_service.get_file_content(github_pr, "src/main.py", "abc123", 98765)
        assert content == "print('hello')"


class TestGitHubReviewServiceCheckRuns:
    """Test check run creation and updates."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_check_run(
        self, github_pr: PullRequest, github_service: GitHubReviewService
    ) -> None:
        respx.post(
            "https://api.github.com/repos/acme-corp/backend-api/check-runs",
        ).respond(json={"id": 12345})

        check_id = await github_service.create_check_run(github_pr, "AI Review", 98765)
        assert check_id == "12345"

    @pytest.mark.asyncio
    @respx.mock
    async def test_update_check_run(
        self, github_pr: PullRequest, github_service: GitHubReviewService
    ) -> None:
        respx.patch(
            "https://api.github.com/repos/acme-corp/backend-api/check-runs/12345",
        ).respond(json={"id": 12345})

        await github_service.update_check_run(
            github_pr,
            "12345",
            98765,
            status="completed",
            conclusion="success",
            summary="All good!",
        )


class TestGitHubReviewServicePostReview:
    """Test review posting."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_review_with_findings(
        self, github_pr: PullRequest, github_service: GitHubReviewService
    ) -> None:
        route = respx.post(
            "https://api.github.com/repos/acme-corp/backend-api/pulls/42/reviews",
        ).respond(json={"id": 1})

        findings = (
            Finding(
                path="src/auth.py",
                line=42,
                severity=Severity.HIGH,
                category=Category.SECURITY,
                message="SQL injection",
                suggestion="Use parameterized queries",
            ),
        )
        review = Review(
            pull_request=github_pr,
            findings=findings,
            summary="Found 1 issue",
        )

        await github_service.post_review(review, 98765)

        assert route.called
        request_body = json.loads(route.calls[0].request.content)
        assert request_body["event"] == "REQUEST_CHANGES"
        assert len(request_body["comments"]) == 1
        assert request_body["comments"][0]["path"] == "src/auth.py"

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_review_no_findings(
        self, github_pr: PullRequest, github_service: GitHubReviewService
    ) -> None:
        route = respx.post(
            "https://api.github.com/repos/acme-corp/backend-api/pulls/42/reviews",
        ).respond(json={"id": 1})

        review = Review(
            pull_request=github_pr,
            summary="Looks good!",
        )

        await github_service.post_review(review, 98765)

        request_body = json.loads(route.calls[0].request.content)
        assert request_body["event"] == "COMMENT"
        assert "comments" not in request_body


class TestGitHubReviewServiceGetRepoConfig:
    """Test repo config fetching."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_config_found(
        self, github_pr: PullRequest, github_service: GitHubReviewService
    ) -> None:
        yaml_content = """
enabled: true
ignore_paths:
  - vendor/
  - generated/
max_files: 25
severity_threshold: medium
"""
        respx.get(
            "https://api.github.com/repos/acme-corp/backend-api/contents/.reviewer.yaml",
        ).respond(text=yaml_content)

        config = await github_service.get_repo_config(github_pr, 98765)
        assert config.enabled is True
        assert config.ignore_paths == ("vendor/", "generated/")
        assert config.max_files == 25

    @pytest.mark.asyncio
    @respx.mock
    async def test_config_not_found_returns_defaults(
        self, github_pr: PullRequest, github_service: GitHubReviewService
    ) -> None:
        respx.get(
            "https://api.github.com/repos/acme-corp/backend-api/contents/.reviewer.yaml",
        ).respond(status_code=404)

        config = await github_service.get_repo_config(github_pr, 98765)
        assert config.enabled is True
        assert config.max_files == 50
