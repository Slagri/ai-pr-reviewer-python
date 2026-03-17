"""Tests for GitHub webhook parsing and signature verification."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from reviewer.exceptions import SignatureError, WebhookError
from reviewer.models import EventAction, Provider
from reviewer.providers.github.webhook import (
    parse_webhook,
    verify_signature,
)
from tests.fixtures import load_github_fixture


class TestVerifySignature:
    """Test HMAC-SHA256 webhook signature verification."""

    def _sign(self, payload: bytes, secret: str) -> str:
        digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature(self) -> None:
        payload = b'{"action": "opened"}'
        secret = "test-secret"
        signature = self._sign(payload, secret)
        verify_signature(payload, signature, secret)

    def test_invalid_signature_raises(self) -> None:
        payload = b'{"action": "opened"}'
        with pytest.raises(SignatureError, match="verification failed"):
            verify_signature(payload, "sha256=deadbeef", "test-secret")

    def test_missing_signature_raises(self) -> None:
        with pytest.raises(SignatureError, match="missing"):
            verify_signature(b"body", "", "secret")

    def test_wrong_algorithm_prefix_raises(self) -> None:
        with pytest.raises(SignatureError, match="sha256"):
            verify_signature(b"body", "sha1=abc123", "secret")

    def test_constant_time_comparison(self) -> None:
        """Verify we use hmac.compare_digest (constant-time)."""
        # The implementation uses hmac.compare_digest — check source
        import inspect

        import reviewer.providers.github.webhook as mod

        source = inspect.getsource(mod.verify_signature)
        assert "compare_digest" in source

    def test_payload_with_unicode(self) -> None:
        payload = '{"title": "Fix für Ünïcödë"}'.encode()
        secret = "unicode-secret"
        signature = self._sign(payload, secret)
        verify_signature(payload, signature, secret)


class TestParseWebhook:
    """Test GitHub webhook payload parsing."""

    def test_parse_opened_event(self) -> None:
        raw = load_github_fixture("pull_request_opened")
        event = parse_webhook(raw, "pull_request", "delivery-123")

        assert event is not None
        assert event.provider == Provider.GITHUB
        assert event.action == EventAction.OPENED
        assert event.pull_request.number == 42
        assert event.pull_request.owner == "acme-corp"
        assert event.pull_request.repo == "backend-api"
        assert event.pull_request.author == "jsmith"
        assert event.pull_request.head_ref == "feat/input-validation"
        assert event.pull_request.base_ref == "main"
        assert event.delivery_id == "delivery-123"
        assert event.installation_id == 98765

    def test_parse_synchronize_event(self) -> None:
        raw = load_github_fixture("pull_request_synchronize")
        event = parse_webhook(raw, "pull_request", "delivery-456")

        assert event is not None
        assert event.action == EventAction.SYNCHRONIZE
        assert event.pull_request.head_sha == "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3"

    def test_ignores_non_pull_request_events(self) -> None:
        result = parse_webhook({"action": "created"}, "issues", "d-1")
        assert result is None

    def test_ignores_unsupported_actions(self) -> None:
        raw = load_github_fixture("pull_request_opened")
        raw_copy = {**raw, "action": "labeled"}
        result = parse_webhook(raw_copy, "pull_request", "d-2")
        assert result is None

    def test_skips_draft_prs(self) -> None:
        raw = load_github_fixture("pull_request_opened")
        raw["pull_request"]["draft"] = True
        result = parse_webhook(raw, "pull_request", "d-3")
        assert result is None

    def test_missing_action_raises(self) -> None:
        with pytest.raises(WebhookError, match="missing action"):
            parse_webhook({}, "pull_request", "d-4")

    def test_missing_pull_request_raises(self) -> None:
        with pytest.raises(WebhookError, match="missing pull_request"):
            parse_webhook({"action": "opened"}, "pull_request", "d-5")

    def test_malformed_pull_request_raises(self) -> None:
        with pytest.raises(WebhookError, match="malformed"):
            parse_webhook(
                {"action": "opened", "pull_request": {"number": 1}},
                "pull_request",
                "d-6",
            )

    def test_null_body_handled(self) -> None:
        """GitHub sends null body when PR has no description."""
        raw = load_github_fixture("pull_request_opened")
        raw["pull_request"]["body"] = None
        event = parse_webhook(raw, "pull_request", "d-7")

        assert event is not None
        assert event.pull_request.body == ""

    def test_no_installation_returns_none_id(self) -> None:
        raw = load_github_fixture("pull_request_opened")
        del raw["installation"]
        event = parse_webhook(raw, "pull_request", "d-8")

        assert event is not None
        assert event.installation_id is None

    @pytest.mark.parametrize("action", ["opened", "synchronize", "reopened"])
    def test_all_supported_actions(self, action: str) -> None:
        raw = load_github_fixture("pull_request_opened")
        raw["action"] = action
        event = parse_webhook(raw, "pull_request", "d-9")
        assert event is not None
        assert event.action == EventAction(action)
