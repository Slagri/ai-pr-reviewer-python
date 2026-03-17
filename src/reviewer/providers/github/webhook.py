"""GitHub webhook parsing and signature verification."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import structlog

from reviewer.exceptions import SignatureError, WebhookError
from reviewer.models import EventAction, Provider, PullRequest, WebhookEvent

logger = structlog.get_logger()

SUPPORTED_ACTIONS = frozenset(
    {
        EventAction.OPENED,
        EventAction.SYNCHRONIZE,
        EventAction.REOPENED,
    }
)


def verify_signature(payload: bytes, signature_header: str, secret: str) -> None:
    """Verify GitHub webhook HMAC-SHA256 signature.

    The signature header format is: sha256=<hex_digest>
    Uses hmac.compare_digest for constant-time comparison.

    Raises SignatureError if verification fails.
    """
    if not signature_header:
        raise SignatureError("missing signature header")

    if not signature_header.startswith("sha256="):
        raise SignatureError("signature must use sha256 algorithm")

    expected_signature = signature_header.removeprefix("sha256=")
    computed = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed, expected_signature):
        raise SignatureError("signature verification failed")


def parse_webhook(
    payload: dict[str, Any],
    event_type: str,
    delivery_id: str,
) -> WebhookEvent | None:
    """Parse a GitHub webhook payload into a WebhookEvent.

    Returns None for events we don't handle (wrong type, unsupported action, draft PRs).
    Raises WebhookError for malformed payloads.
    """
    if event_type != "pull_request":
        logger.debug("ignoring non-pull-request event", event_type=event_type)
        return None

    action_str = payload.get("action")
    if action_str is None:
        raise WebhookError("missing action field in webhook payload")

    try:
        action = EventAction(action_str)
    except ValueError:
        logger.debug("ignoring unsupported action", action=action_str)
        return None

    if action not in SUPPORTED_ACTIONS:
        logger.debug("ignoring unsupported action", action=action_str)
        return None

    pr_data = payload.get("pull_request")
    if pr_data is None:
        raise WebhookError("missing pull_request field in webhook payload")

    # Skip draft PRs
    if pr_data.get("draft", False):
        logger.info("skipping draft PR", number=pr_data.get("number"))
        return None

    try:
        pr = _parse_pull_request(pr_data, payload)
    except (KeyError, TypeError) as exc:
        raise WebhookError(f"malformed pull_request payload: {exc}") from exc

    installation_id = _extract_installation_id(payload)

    return WebhookEvent(
        provider=Provider.GITHUB,
        action=action,
        pull_request=pr,
        installation_id=installation_id,
        delivery_id=delivery_id,
        raw=payload,
    )


def _parse_pull_request(
    pr_data: dict[str, Any],
    payload: dict[str, Any],
) -> PullRequest:
    """Extract PullRequest from the nested webhook payload."""
    repo_data = payload.get("repository", {})
    owner = repo_data.get("owner", {}).get("login", "")
    repo_name = repo_data.get("name", "")

    return PullRequest(
        provider=Provider.GITHUB,
        owner=owner,
        repo=repo_name,
        number=pr_data["number"],
        title=pr_data.get("title", ""),
        body=pr_data.get("body", "") or "",
        head_sha=pr_data["head"]["sha"],
        base_ref=pr_data["base"]["ref"],
        head_ref=pr_data["head"]["ref"],
        author=pr_data["user"]["login"],
        draft=pr_data.get("draft", False),
        url=pr_data.get("html_url", ""),
    )


def _extract_installation_id(payload: dict[str, Any]) -> int | None:
    """Extract installation ID from webhook payload."""
    installation = payload.get("installation")
    if installation is None:
        return None
    return installation.get("id")  # type: ignore[no-any-return]
