"""Tests for shared Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reviewer.models import (
    Category,
    EventAction,
    FileDiff,
    Finding,
    Provider,
    PullRequest,
    Review,
    ReviewConfig,
    Severity,
    TokenUsage,
    WebhookEvent,
)


class TestPullRequest:
    """Test PullRequest model."""

    def test_create_minimal(self, sample_pr: PullRequest) -> None:
        assert sample_pr.provider == Provider.GITHUB
        assert sample_pr.number == 42
        assert sample_pr.title == "Add feature X"

    def test_immutable(self, sample_pr: PullRequest) -> None:
        with pytest.raises(ValidationError):
            sample_pr.title = "Changed"  # type: ignore[misc]

    def test_model_copy(self, sample_pr: PullRequest) -> None:
        updated = sample_pr.model_copy(update={"title": "Updated title"})
        assert updated.title == "Updated title"
        assert sample_pr.title == "Add feature X"

    def test_defaults(self) -> None:
        pr = PullRequest(
            provider=Provider.GITHUB,
            owner="org",
            repo="repo",
            number=1,
            title="Test",
            head_sha="abc",
            base_ref="main",
            head_ref="feat",
            author="user",
        )
        assert pr.body == ""
        assert pr.draft is False
        assert pr.url == ""


class TestFileDiff:
    """Test FileDiff model."""

    def test_create(self, sample_file_diff: FileDiff) -> None:
        assert sample_file_diff.path == "src/main.py"
        assert sample_file_diff.status == "modified"
        assert sample_file_diff.additions == 10

    def test_immutable(self, sample_file_diff: FileDiff) -> None:
        with pytest.raises(ValidationError):
            sample_file_diff.path = "other.py"  # type: ignore[misc]

    def test_renamed_file(self) -> None:
        diff = FileDiff(
            path="new_name.py",
            status="renamed",
            previous_path="old_name.py",
        )
        assert diff.previous_path == "old_name.py"

    def test_defaults(self) -> None:
        diff = FileDiff(path="test.py", status="added")
        assert diff.additions == 0
        assert diff.deletions == 0
        assert diff.patch == ""
        assert diff.previous_path is None


class TestFinding:
    """Test Finding model."""

    def test_create(self) -> None:
        finding = Finding(
            path="src/auth.py",
            line=42,
            severity=Severity.CRITICAL,
            category=Category.SECURITY,
            message="hardcoded secret detected",
        )
        assert finding.severity == Severity.CRITICAL
        assert finding.category == Category.SECURITY
        assert finding.suggestion == ""

    def test_with_suggestion(self) -> None:
        finding = Finding(
            path="src/auth.py",
            line=42,
            severity=Severity.HIGH,
            category=Category.SECURITY,
            message="SQL injection risk",
            suggestion="Use parameterized queries",
        )
        assert finding.suggestion == "Use parameterized queries"

    def test_immutable(self) -> None:
        finding = Finding(
            path="test.py",
            line=1,
            severity=Severity.LOW,
            category=Category.STYLE,
            message="test",
        )
        with pytest.raises(ValidationError):
            finding.message = "changed"  # type: ignore[misc]


class TestReview:
    """Test Review model."""

    def test_create_empty_review(self, sample_pr: PullRequest) -> None:
        review = Review(pull_request=sample_pr)
        assert review.findings == ()
        assert review.summary == ""
        assert review.iterations == 0

    def test_create_with_findings(self, sample_pr: PullRequest) -> None:
        findings = (
            Finding(
                path="a.py",
                line=1,
                severity=Severity.HIGH,
                category=Category.BUG,
                message="null pointer",
            ),
            Finding(
                path="b.py",
                line=10,
                severity=Severity.LOW,
                category=Category.STYLE,
                message="naming convention",
            ),
        )
        review = Review(
            pull_request=sample_pr,
            findings=findings,
            summary="Found 2 issues",
            model="gpt-5.4",
            duration_seconds=12.5,
            iterations=3,
        )
        assert len(review.findings) == 2
        assert review.model == "gpt-5.4"

    def test_token_usage(self) -> None:
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert usage.total_tokens == 150


class TestWebhookEvent:
    """Test WebhookEvent model."""

    def test_create(self, sample_webhook_event: WebhookEvent) -> None:
        assert sample_webhook_event.provider == Provider.GITHUB
        assert sample_webhook_event.action == EventAction.OPENED
        assert sample_webhook_event.installation_id == 12345

    def test_delivery_id(self, sample_webhook_event: WebhookEvent) -> None:
        assert sample_webhook_event.delivery_id == "test-delivery-123"


class TestReviewConfig:
    """Test ReviewConfig model."""

    def test_defaults(self) -> None:
        config = ReviewConfig()
        assert config.enabled is True
        assert config.ignore_paths == ()
        assert config.ignore_authors == ()
        assert config.max_files == 50
        assert config.severity_threshold == Severity.LOW
        assert config.extra_instructions == ""

    def test_custom_config(self) -> None:
        config = ReviewConfig(
            enabled=True,
            ignore_paths=("vendor/", "generated/"),
            ignore_authors=("dependabot[bot]",),
            max_files=25,
            severity_threshold=Severity.MEDIUM,
            extra_instructions="Focus on security",
        )
        assert len(config.ignore_paths) == 2
        assert config.max_files == 25


class TestEnums:
    """Test enum values are correct."""

    def test_providers(self) -> None:
        assert Provider.GITHUB == "github"
        assert Provider.AZURE_DEVOPS == "azuredevops"

    def test_event_actions(self) -> None:
        assert EventAction.OPENED == "opened"
        assert EventAction.SYNCHRONIZE == "synchronize"
        assert EventAction.REOPENED == "reopened"

    @pytest.mark.parametrize(
        ("severity", "value"),
        [
            (Severity.CRITICAL, "critical"),
            (Severity.HIGH, "high"),
            (Severity.MEDIUM, "medium"),
            (Severity.LOW, "low"),
            (Severity.INFO, "info"),
        ],
    )
    def test_severity_values(self, severity: Severity, value: str) -> None:
        assert severity == value

    @pytest.mark.parametrize(
        "category",
        list(Category),
    )
    def test_all_categories_are_strings(self, category: Category) -> None:
        assert isinstance(category, str)
