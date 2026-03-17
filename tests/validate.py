"""Phase milestone validation script.

Run: python -m tests.validate [phase]

Each phase validator checks that the components built in that phase
actually work together — not just that unit tests pass in isolation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class ValidationResult:
    """Collects pass/fail results for a validation phase."""

    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.checks: list[tuple[str, bool, str]] = []

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, passed, detail))
        status = "PASS" if passed else "FAIL"
        msg = f"  [{status}] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def summary(self) -> str:
        total = len(self.checks)
        passed = sum(1 for _, ok, _ in self.checks if ok)
        failed = total - passed
        return f"Phase {self.phase}: {passed}/{total} passed, {failed} failed"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def validate_phase_1() -> ValidationResult:
    """Phase 1: Foundation — config, models, provider protocol, fixtures."""
    result = ValidationResult("1")
    print("\n=== Phase 1: Foundation Validation ===\n")

    # 1. Config loads with env vars
    try:
        from reviewer.config import Settings

        settings = Settings(azure_openai_endpoint="https://test.openai.azure.com")
        result.check(
            "Config loads with minimal env",
            settings.azure_openai_endpoint == "https://test.openai.azure.com",
        )
    except Exception as e:
        result.check("Config loads with minimal env", False, str(e))

    # 2. Config rejects invalid endpoint
    try:
        from pydantic import ValidationError

        try:
            Settings(azure_openai_endpoint="http://insecure.com")  # type: ignore[call-arg]
            result.check("Config rejects http endpoint", False, "should have raised")
        except ValidationError:
            result.check("Config rejects http endpoint", True)
    except Exception as e:
        result.check("Config rejects http endpoint", False, str(e))

    # 3. Models are frozen (immutable)
    try:
        from reviewer.models import Provider, PullRequest

        pr = PullRequest(
            provider=Provider.GITHUB,
            owner="org",
            repo="repo",
            number=1,
            title="Test",
            head_sha="abc",
            base_ref="main",
            head_ref="feat",
            author="user",
        )
        try:
            pr.title = "mutated"  # type: ignore[misc]
            result.check("PullRequest is frozen", False, "mutation was allowed")
        except Exception:
            result.check("PullRequest is frozen", True)
    except Exception as e:
        result.check("PullRequest is frozen", False, str(e))

    # 4. Model copy creates new instance (not mutation)
    try:
        updated = pr.model_copy(update={"title": "Updated"})
        result.check(
            "model_copy returns new instance",
            updated.title == "Updated" and pr.title == "Test",
        )
    except Exception as e:
        result.check("model_copy returns new instance", False, str(e))

    # 5. Provider protocol structural check
    try:
        from reviewer.providers.base import ProviderProtocol

        result.check(
            "ProviderProtocol is runtime checkable",
            hasattr(ProviderProtocol, "__protocol_attrs__"),
        )
        result.check(
            "object() does not satisfy protocol",
            not isinstance(object(), ProviderProtocol),
        )
    except Exception as e:
        result.check("ProviderProtocol is runtime checkable", False, str(e))

    # 6. Exception hierarchy
    try:
        from reviewer.exceptions import (
            ProviderError,
            ReviewerError,
            SignatureError,
            ToolError,
            WebhookError,
        )

        result.check(
            "SignatureError chain",
            issubclass(SignatureError, WebhookError) and issubclass(WebhookError, ReviewerError),
        )
        err = ProviderError("test", provider="github", status_code=404)
        result.check(
            "ProviderError carries metadata",
            err.provider == "github" and err.status_code == 404,
        )
        tool_err = ToolError("fail", tool_name="get_file_content")
        result.check(
            "ToolError carries tool_name",
            tool_err.tool_name == "get_file_content",
        )
    except Exception as e:
        result.check("Exception hierarchy", False, str(e))

    # 7. Fixtures load correctly
    try:
        pr_fixture = _load_json(FIXTURES_DIR / "github" / "pull_request_opened.json")
        result.check(
            "GitHub PR fixture loads",
            pr_fixture["action"] == "opened" and pr_fixture["number"] == 42,
        )

        tool_call = _load_json(FIXTURES_DIR / "openai" / "tool_call_response.json")
        result.check(
            "OpenAI tool call fixture loads",
            tool_call["choices"][0]["finish_reason"] == "tool_calls"
            and len(tool_call["choices"][0]["message"]["tool_calls"]) == 1,
        )

        stream = _load_json(FIXTURES_DIR / "openai" / "streaming_tool_call_chunks.json")
        chunks = stream["chunks"]
        result.check(
            "Streaming chunks fixture loads",
            len(chunks) == 5 and chunks[-1]["choices"][0]["finish_reason"] == "tool_calls",
        )

        # Verify streaming tool call arguments can be reassembled
        args_parts = []
        for chunk in chunks:
            delta = chunk["choices"][0]["delta"]
            if "tool_calls" in delta:
                tc = delta["tool_calls"][0]
                if "function" in tc and "arguments" in tc["function"]:
                    args_parts.append(tc["function"]["arguments"])
        full_args = "".join(args_parts)
        parsed = json.loads(full_args)
        result.check(
            "Streaming tool call args reassemble to valid JSON",
            parsed.get("path") == "src/auth/register.py",
            f"got: {full_args}",
        )
    except Exception as e:
        result.check("Fixtures load correctly", False, str(e))

    # 8. Fixture loader utility works
    try:
        from tests.fixtures import (
            load_github_fixture,
            load_openai_fixture,
            load_streaming_chunks,
        )

        gh = load_github_fixture("pull_request_opened")
        result.check("load_github_fixture works", gh["action"] == "opened")

        oa = load_openai_fixture("final_review_response")
        result.check(
            "load_openai_fixture works",
            oa["choices"][0]["finish_reason"] == "stop",
        )

        chunks = load_streaming_chunks("streaming_tool_call_chunks")
        result.check("load_streaming_chunks works", len(chunks) == 5)
    except Exception as e:
        result.check("Fixture loader utility", False, str(e))

    return result


def validate_phase_2() -> ValidationResult:
    """Phase 2: GitHub Provider — auth, webhooks, review posting.

    Placeholder — will be implemented when Phase 2 is built.
    """
    result = ValidationResult("2")
    print("\n=== Phase 2: GitHub Provider Validation ===\n")
    result.check("Phase 2 not yet implemented", False, "build Phase 2 first")
    return result


def validate_phase_3() -> ValidationResult:
    """Phase 3: AI Agent Core — tool-use loop, prompts, pipeline.

    Placeholder — will be implemented when Phase 3 is built.
    """
    result = ValidationResult("3")
    print("\n=== Phase 3: AI Agent Core Validation ===\n")
    result.check("Phase 3 not yet implemented", False, "build Phase 3 first")
    return result


VALIDATORS = {
    "1": validate_phase_1,
    "2": validate_phase_2,
    "3": validate_phase_3,
}


def main() -> None:
    """Run validation for specified phase or all completed phases."""
    if len(sys.argv) > 1:
        phase = sys.argv[1]
        if phase not in VALIDATORS:
            print(f"Unknown phase: {phase}. Available: {', '.join(VALIDATORS)}")
            sys.exit(1)
        results = [VALIDATORS[phase]()]
    else:
        # Run all phases that have been implemented
        results = []
        for _phase_num, validator in VALIDATORS.items():
            r = validator()
            results.append(r)
            if not r.passed:
                break  # Stop at first failing phase

    print("\n=== Validation Summary ===\n")
    all_passed = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.summary()}")
        if not r.passed:
            all_passed = False

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
