"""Provider protocol defining the interface all SCM providers must implement.

Uses typing.Protocol for structural subtyping — no inheritance required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from reviewer.models import FileDiff, PullRequest, Review, ReviewConfig


@runtime_checkable
class ProviderProtocol(Protocol):
    """Interface that all SCM providers must satisfy.

    Implementations: GitHubProvider, AzureDevOpsProvider.
    Uses structural subtyping — providers just need matching method signatures.
    """

    async def get_diff(self, pr: PullRequest) -> tuple[FileDiff, ...]:
        """Fetch the diff for a pull request.

        Returns a tuple of FileDiff objects, one per changed file.
        """
        ...

    async def get_file_content(self, pr: PullRequest, path: str, ref: str) -> str:
        """Fetch the content of a file at a specific ref (commit SHA or branch).

        Raises ProviderError if the file doesn't exist or the API call fails.
        """
        ...

    async def post_review(self, review: Review) -> None:
        """Post a completed review back to the SCM provider.

        Creates inline comments for each finding and a summary comment.
        """
        ...

    async def create_check_run(self, pr: PullRequest, name: str) -> str:
        """Create an in-progress check run. Returns the check run ID."""
        ...

    async def update_check_run(
        self,
        pr: PullRequest,
        check_run_id: str,
        *,
        status: str,
        conclusion: str | None = None,
        summary: str = "",
    ) -> None:
        """Update an existing check run with status and conclusion."""
        ...

    async def get_repo_config(self, pr: PullRequest) -> ReviewConfig:
        """Fetch and parse the .reviewer.yaml from the repository.

        Returns default ReviewConfig if the file doesn't exist.
        """
        ...
