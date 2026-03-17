"""Tests for the provider protocol definition."""

from __future__ import annotations

from reviewer.models import FileDiff, PullRequest, Review, ReviewConfig
from reviewer.providers.base import ProviderProtocol


class FakeProvider:
    """A minimal fake that satisfies ProviderProtocol for testing."""

    async def get_diff(self, pr: PullRequest) -> tuple[FileDiff, ...]:
        return ()

    async def get_file_content(self, pr: PullRequest, path: str, ref: str) -> str:
        return ""

    async def post_review(self, review: Review) -> None:
        pass

    async def create_check_run(self, pr: PullRequest, name: str) -> str:
        return "check-123"

    async def update_check_run(
        self,
        pr: PullRequest,
        check_run_id: str,
        *,
        status: str,
        conclusion: str | None = None,
        summary: str = "",
    ) -> None:
        pass

    async def get_repo_config(self, pr: PullRequest) -> ReviewConfig:
        return ReviewConfig()


class TestProviderProtocol:
    """Test that the protocol is correctly defined."""

    def test_fake_satisfies_protocol(self) -> None:
        provider = FakeProvider()
        assert isinstance(provider, ProviderProtocol)

    def test_object_does_not_satisfy_protocol(self) -> None:
        assert not isinstance(object(), ProviderProtocol)
