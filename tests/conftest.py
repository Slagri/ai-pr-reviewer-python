"""Shared test fixtures."""

from __future__ import annotations

import tempfile

import pytest

from reviewer.models import (
    EventAction,
    FileDiff,
    Provider,
    PullRequest,
    WebhookEvent,
)


@pytest.fixture(autouse=True)
def _isolate_env_from_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """Prevent .env file from leaking into test settings.

    pydantic-settings reads .env automatically. Change cwd to a temp dir
    so no .env file is found, and clear any leaked env vars.
    """
    from reviewer.server.dependencies import get_settings

    monkeypatch.chdir(tempfile.gettempdir())

    for key in [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT",
        "REVIEW_MODEL",
        "GITHUB_APP_ID",
        "GITHUB_PRIVATE_KEY",
        "GITHUB_PRIVATE_KEY_PATH",
        "GITHUB_WEBHOOK_SECRET",
        "AZDO_ORGANIZATION",
        "AZDO_PAT",
        "AZDO_WEBHOOK_SECRET",
    ]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()


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
