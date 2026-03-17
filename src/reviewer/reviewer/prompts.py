"""System and user prompt templates for the AI review agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reviewer.models import FileDiff, PullRequest, ReviewConfig

SYSTEM_PROMPT = """\
You are an expert code reviewer. You review pull requests for bugs, \
security issues, performance problems, and maintainability concerns.

## Rules
1. Only comment on issues you are confident about — avoid false positives
2. Focus on the CHANGED code (the diff), not pre-existing issues
3. Use the provided tools to fetch file content when you need more context
4. Be specific: reference exact file paths and line numbers
5. Provide actionable suggestions, not vague complaints
6. Categorize findings by severity: critical, high, medium, low, info
7. Categorize findings by type: security, bug, performance, style, \
documentation, testing, maintainability

## Output Format
When you have completed your review, respond with a JSON object in a markdown code block:

```json
{
  "findings": [
    {
      "path": "src/example.py",
      "line": 42,
      "severity": "high",
      "category": "security",
      "message": "Clear description of the issue",
      "suggestion": "How to fix it"
    }
  ],
  "summary": "Brief overall assessment of the PR"
}
```

If the PR looks good with no issues, return an empty findings array with a positive summary."""


def build_user_prompt(
    pr: PullRequest,
    diffs: tuple[FileDiff, ...],
    config: ReviewConfig,
) -> str:
    """Build the initial user message for the review agent."""
    parts: list[str] = [
        f"## Pull Request #{pr.number}: {pr.title}",
        f"**Author:** {pr.author}",
        f"**Branch:** {pr.head_ref} → {pr.base_ref}",
    ]

    if pr.body:
        parts.append(f"\n**Description:**\n{pr.body}")

    if config.extra_instructions:
        parts.append(f"\n**Additional Review Instructions:**\n{config.extra_instructions}")

    parts.append(f"\n## Changed Files ({len(diffs)} files)\n")

    for diff in diffs:
        status_icon = {
            "added": "+",
            "modified": "~",
            "removed": "-",
            "renamed": "→",
        }.get(diff.status, "?")

        header = f"### {status_icon} {diff.path}"
        if diff.previous_path:
            header += f" (from {diff.previous_path})"
        header += f" (+{diff.additions}/-{diff.deletions})"
        parts.append(header)

        if diff.patch:
            parts.append(f"```diff\n{diff.patch}\n```")

    parts.append(
        "\nReview the changes above. Use tools to fetch full file content "
        "when you need more context. Focus on the diff, not pre-existing code."
    )

    return "\n".join(parts)
