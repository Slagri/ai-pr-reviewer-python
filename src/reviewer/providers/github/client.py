"""GitHub App authentication: JWT generation and installation token management."""

from __future__ import annotations

import time
from datetime import datetime

import httpx
import jwt
import structlog

from reviewer.exceptions import ProviderError

logger = structlog.get_logger()

GITHUB_API_BASE = "https://api.github.com"
JWT_ALGORITHM = "RS256"
JWT_EXPIRY_SECONDS = 600  # 10 minutes max
JWT_CLOCK_DRIFT_SECONDS = 60
TOKEN_REFRESH_BUFFER_SECONDS = 300  # refresh 5 min before expiry


class GitHubAuth:
    """Handles GitHub App JWT generation and installation token caching.

    JWT flow:
    1. Generate RS256-signed JWT with app_id as issuer
    2. Exchange JWT for installation access token (1-hour TTL)
    3. Cache token per installation, refresh before expiry
    """

    def __init__(
        self,
        app_id: str,
        private_key: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._http_client = http_client
        self._token_cache: dict[int, tuple[str, float]] = {}

    def _generate_jwt(self) -> str:
        """Generate a short-lived JWT for GitHub App authentication."""
        now = int(time.time())
        payload = {
            "iss": self._app_id,
            "iat": now - JWT_CLOCK_DRIFT_SECONDS,
            "exp": now + JWT_EXPIRY_SECONDS,
        }
        return jwt.encode(payload, self._private_key, algorithm=JWT_ALGORITHM)

    async def get_installation_token(self, installation_id: int) -> str:
        """Get a cached or fresh installation access token.

        Tokens are cached per installation and refreshed 5 minutes before expiry.
        """
        cached = self._token_cache.get(installation_id)
        if cached is not None:
            token, expires_at = cached
            if time.time() < expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
                return token

        token = await self._exchange_jwt_for_token(installation_id)
        return token

    async def _exchange_jwt_for_token(self, installation_id: int) -> str:
        """Exchange JWT for an installation access token via GitHub API."""
        app_jwt = self._generate_jwt()

        try:
            response = await self._http_client.post(
                f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"failed to get installation token: {exc.response.status_code}",
                provider="github",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"failed to get installation token: {exc}",
                provider="github",
            ) from exc

        data = response.json()
        token: str | None = data.get("token")
        expires_at_str: str | None = data.get("expires_at")
        if not token or not expires_at_str:
            raise ProviderError(
                "unexpected response from installation token endpoint",
                provider="github",
            )

        # Parse ISO 8601 expiry and cache
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00")).timestamp()
        self._token_cache[installation_id] = (token, expires_at)

        logger.info(
            "installation token obtained",
            installation_id=installation_id,
        )
        return token

    def invalidate_token(self, installation_id: int) -> None:
        """Remove a cached token, forcing refresh on next request."""
        self._token_cache.pop(installation_id, None)


def build_github_auth(
    app_id: str,
    private_key: str | None = None,
    private_key_path: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> GitHubAuth:
    """Factory to create GitHubAuth from either key content or file path."""
    if private_key is not None:
        key = private_key
    elif private_key_path is not None:
        from pathlib import Path

        key_path = Path(private_key_path)
        if not key_path.exists():
            raise ProviderError(
                f"private key file not found: {private_key_path}",
                provider="github",
            )
        key = key_path.read_text()
    else:
        raise ProviderError(
            "either private_key or private_key_path is required",
            provider="github",
        )

    client = http_client or httpx.AsyncClient(timeout=30.0)
    return GitHubAuth(app_id=app_id, private_key=key, http_client=client)
