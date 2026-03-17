"""Shared test fixtures."""

from __future__ import annotations

import pytest

from reviewer.models import (
    EventAction,
    FileDiff,
    Provider,
    PullRequest,
    WebhookEvent,
)


@pytest.fixture
def sample_pr() -> PullRequest:
    """A minimal pull request for testing."""
    return PullRequest(
        provider=Provider.GITHUB,
        owner="testorg",
        repo="testrepo",
        number=42,
        title="Add feature X",
        body="This PR adds feature X",
        head_sha="abc1234",
        base_ref="main",
        head_ref="feat/feature-x",
        author="testuser",
        url="https://github.com/testorg/testrepo/pull/42",
    )


@pytest.fixture
def sample_file_diff() -> FileDiff:
    """A minimal file diff for testing."""
    return FileDiff(
        path="src/main.py",
        status="modified",
        additions=10,
        deletions=3,
        patch="@@ -1,5 +1,12 @@\n+import os\n",
    )


@pytest.fixture
def sample_webhook_event(sample_pr: PullRequest) -> WebhookEvent:
    """A minimal webhook event for testing."""
    return WebhookEvent(
        provider=Provider.GITHUB,
        action=EventAction.OPENED,
        pull_request=sample_pr,
        installation_id=12345,
        delivery_id="test-delivery-123",
    )
