"""Tests for FastAPI routes."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from reviewer.main import create_app
from reviewer.server.dependencies import get_settings


def _make_test_settings(**overrides: Any) -> Any:
    """Create mock settings for testing."""
    from reviewer.config import Settings

    defaults: dict[str, Any] = {
        "azure_openai_endpoint": "https://test.openai.azure.com",
    }
    return Settings(**(defaults | overrides))


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Any:
    """Clear the lru_cache on get_settings before each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com")
    get_settings.cache_clear()
    return create_app()


@pytest.fixture
def client(app: Any) -> TestClient:
    return TestClient(app)


class TestHealthEndpoints:
    """Test health check routes."""

    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_readyz(self, client: TestClient) -> None:
        response = client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "checks" in data

    def test_metrics(self, client: TestClient) -> None:
        response = client.get("/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0


class TestGitHubWebhookRoute:
    """Test the GitHub webhook endpoint."""

    def _sign_payload(self, payload: bytes, secret: str) -> str:
        digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_ignored_event(self, client: TestClient) -> None:
        response = client.post(
            "/webhook/github",
            json={"action": "created"},
            headers={
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "test-1",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_malformed_payload(self, client: TestClient) -> None:
        response = client.post(
            "/webhook/github",
            json={},
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-2",
            },
        )
        assert response.status_code == 400

    def test_valid_event_no_pool(self, app: Any) -> None:
        """Valid event but worker pool not initialized returns 503."""
        app.state.worker_pool = None
        client = TestClient(app)

        from tests.fixtures import load_github_fixture

        payload = load_github_fixture("pull_request_opened")

        response = client.post(
            "/webhook/github",
            json=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-3",
            },
        )
        assert response.status_code == 503

    def test_valid_event_queued(self, app: Any) -> None:
        """Valid event with active pool returns queued."""
        mock_pool = AsyncMock()
        mock_pool.submit = AsyncMock(return_value=True)
        app.state.worker_pool = mock_pool
        client = TestClient(app)

        from tests.fixtures import load_github_fixture

        payload = load_github_fixture("pull_request_opened")

        response = client.post(
            "/webhook/github",
            json=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-4",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

    def test_valid_event_rejected(self, app: Any) -> None:
        """Duplicate/full queue returns rejected."""
        mock_pool = AsyncMock()
        mock_pool.submit = AsyncMock(return_value=False)
        app.state.worker_pool = mock_pool
        client = TestClient(app)

        from tests.fixtures import load_github_fixture

        payload = load_github_fixture("pull_request_opened")

        response = client.post(
            "/webhook/github",
            json=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-5",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
