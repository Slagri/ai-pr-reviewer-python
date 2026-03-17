"""Tests for GitHub App JWT auth and installation token management."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import httpx
import jwt as pyjwt
import pytest

from reviewer.exceptions import ProviderError
from reviewer.providers.github.client import (
    JWT_ALGORITHM,
    JWT_CLOCK_DRIFT_SECONDS,
    JWT_EXPIRY_SECONDS,
    GitHubAuth,
    build_github_auth,
)
from tests.fixtures.test_rsa_key import TEST_PRIVATE_KEY


class TestGitHubAuth:
    """Test JWT generation and token caching."""

    def _make_auth(
        self,
        http_client: httpx.AsyncClient | None = None,
    ) -> GitHubAuth:
        client = http_client or httpx.AsyncClient()
        return GitHubAuth(
            app_id="12345",
            private_key=TEST_PRIVATE_KEY,
            http_client=client,
        )

    def test_generate_jwt_structure(self) -> None:
        auth = self._make_auth()
        token = auth._generate_jwt()

        decoded = pyjwt.decode(
            token,
            algorithms=[JWT_ALGORITHM],
            options={"verify_signature": False, "verify_exp": False},
        )
        assert decoded["iss"] == "12345"
        assert "iat" in decoded
        assert "exp" in decoded

    def test_jwt_timing(self) -> None:
        auth = self._make_auth()
        now = int(time.time())
        token = auth._generate_jwt()

        decoded = pyjwt.decode(
            token,
            algorithms=[JWT_ALGORITHM],
            options={"verify_signature": False, "verify_exp": False},
        )
        assert decoded["iat"] <= now - JWT_CLOCK_DRIFT_SECONDS + 1
        assert decoded["exp"] >= now + JWT_EXPIRY_SECONDS - 1

    @pytest.mark.asyncio
    async def test_token_caching(self) -> None:
        """Second call should return cached token, not hit API again."""
        auth = self._make_auth()
        expires_at = time.time() + 3600  # 1 hour from now
        auth._token_cache[99] = ("cached-token", expires_at)

        token = await auth.get_installation_token(99)
        assert token == "cached-token"

    @pytest.mark.asyncio
    async def test_expired_token_refreshes(self) -> None:
        """Token near expiry should trigger a refresh."""
        auth = self._make_auth()
        # Token expiring in 2 minutes (within 5-min buffer)
        expires_at = time.time() + 120
        auth._token_cache[99] = ("old-token", expires_at)

        # Mock the exchange call
        auth._exchange_jwt_for_token = AsyncMock(return_value="new-token")
        token = await auth.get_installation_token(99)
        assert token == "new-token"
        auth._exchange_jwt_for_token.assert_called_once_with(99)

    def test_invalidate_token(self) -> None:
        auth = self._make_auth()
        auth._token_cache[99] = ("token", time.time() + 3600)
        auth.invalidate_token(99)
        assert 99 not in auth._token_cache

    def test_invalidate_nonexistent_token(self) -> None:
        auth = self._make_auth()
        auth.invalidate_token(999)  # Should not raise


class TestBuildGitHubAuth:
    """Test the factory function."""

    def test_build_with_key_content(self) -> None:
        auth = build_github_auth(
            app_id="123",
            private_key=TEST_PRIVATE_KEY,
        )
        assert auth._app_id == "123"

    def test_build_with_key_path(self, tmp_path: Any) -> None:
        key_file = tmp_path / "key.pem"
        key_file.write_text(TEST_PRIVATE_KEY)

        auth = build_github_auth(
            app_id="123",
            private_key_path=str(key_file),
        )
        assert auth._app_id == "123"

    def test_build_missing_key_raises(self) -> None:
        with pytest.raises(ProviderError, match="required"):
            build_github_auth(app_id="123")

    def test_build_missing_key_file_raises(self) -> None:
        with pytest.raises(ProviderError, match="not found"):
            build_github_auth(
                app_id="123",
                private_key_path="/nonexistent/key.pem",
            )
