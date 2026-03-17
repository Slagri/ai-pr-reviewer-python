# ai-pr-reviewer — AI-Powered PR Review Agent (Python + Azure OpenAI)

## Quick Reference
- Language: Python 3.12+
- Framework: FastAPI + uvicorn
- AI: Azure OpenAI GPT-5.4 via `openai` SDK
- Test: pytest + pytest-asyncio, 80% coverage minimum
- Lint: ruff (format + lint)
- Type check: mypy --strict
- Build: docker build

## Development Commands
make install     # Install dependencies
make test        # Run tests with coverage
make lint        # Run ruff check + ruff format --check
make typecheck   # Run mypy --strict
make check       # Run all: lint + typecheck + test
make validate PHASE=N  # Run milestone validation for phase N
make validate-all      # Run all phase validations sequentially
make run         # Start server (uvicorn)
make run-debug   # Start with LOG_LEVEL=debug

## Code Conventions
- Python 3.12+ features: type hints everywhere, match statements, f-strings
- Pydantic v2 for all data models (use model_copy(), not mutation)
- Async/await everywhere (FastAPI, httpx, queue)
- Immutable by default (frozen=True on Pydantic models)
- Error messages: lowercase, no trailing punctuation
- Wrap errors with context in custom exceptions
- No bare except, always catch specific exceptions
- Use structlog for all logging (structured JSON, explicit fields)
- Prefer composition over inheritance
- Provider protocol via typing.Protocol (structural subtyping)

## File Organization
- Source in src/reviewer/
- Tests mirror source: tests/test_config.py, tests/reviewer/test_agent.py
- Fixtures in tests/fixtures/ (real payloads, sanitized)
- Keep files under 400 lines, extract when growing

## Testing Conventions
- pytest + pytest-asyncio for async
- @pytest.mark.parametrize for table-driven tests
- httpx mock transport for API mocking
- Fixtures in conftest.py (shared) or test file (local)
- 80% coverage enforced in CI
- Realistic fixtures in tests/fixtures/ (actual API response shapes)
- Integration tests in tests/integration/ validate cross-component behavior
- Phase validation (make validate PHASE=N) must pass before marking phase complete

## Git Conventions
- Conventional commits: feat:, fix:, refactor:, test:, ci:, docs:, chore:
- NO co-authored-by lines in any commit ever
- Each commit must pass: ruff check, mypy, pytest
- Meaningful messages explaining WHY

## Security Rules
- All secrets via environment variables
- HMAC-SHA256 webhook signature with hmac.compare_digest()
- Sanitize file paths (reject absolute and .. traversal)
- Timeouts on ALL HTTP clients
- No secrets in logs
- Max request body 10MB

## Logging
import structlog
logger = structlog.get_logger()
logger.info("review complete", pr=pr.number, duration=elapsed, findings=len(findings))

## Reference Implementation
The Go version at ~/Desktop/Apps/reviewer/ is the architectural reference.
Read its source when you need design context, but write idiomatic Python.
