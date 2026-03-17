# Development Logbook

Design decisions and rationale for the AI PR Reviewer.

## Architecture Decisions

### Python Protocol over ABC inheritance
Used `typing.Protocol` for the provider interface instead of abstract base classes. This enables structural subtyping — providers just need matching method signatures, no inheritance required. Makes testing easier (any object with the right methods satisfies the protocol) and avoids tight coupling.

### Pydantic frozen models everywhere
All shared data models use `frozen=True`. This prevents accidental mutation, makes models hashable, and forces the `model_copy(update={...})` pattern for creating modified versions. Aligns with the project's immutability-first approach.

### asyncio worker pool over Celery/Redis
Chose an in-process asyncio queue over external task queues. The webhook volume doesn't justify Celery/Redis complexity for a single-instance deployment. The bounded queue provides backpressure, and the cancellation registry handles superseded reviews. Can migrate to a distributed queue later if needed.

### Token bucket rate limiting
Per-IP token bucket algorithm instead of sliding window. Token buckets are simpler to implement, handle bursts naturally, and don't require external storage. The periodic cleanup prevents memory growth from abandoned client entries.

### structlog over stdlib logging
structlog provides structured JSON output by default, context variable binding for request correlation IDs, and zero-config integration with asyncio. The bound logger pattern (`logger.bind(pr=42)`) propagates context through the call chain without passing loggers around.

### Azure OpenAI SDK over raw HTTP
Used the official `openai` Python SDK with `AsyncAzureOpenAI` instead of raw `httpx` calls. The SDK handles streaming, retries, tool call parsing, and authentication (including managed identity via `DefaultAzureCredential`). No point reimplementing what the SDK already does well.

### Dynamic test RSA key generation
Initially committed a static test RSA private key, which triggered GitGuardian alerts. Switched to generating the key dynamically at test import time via `cryptography`. The key never touches disk or git — eliminates false positive alerts while keeping tests deterministic within a single run.

### Path sanitization in tool executor
All file paths from the AI agent are validated before use: absolute paths and `..` traversal are rejected. This prevents the LLM from being tricked (via prompt injection in PR content) into reading files outside the repository scope.

## Phase History

| Phase | Scope | Tests | Coverage |
|-------|-------|-------|----------|
| 1 | Config, models, provider protocol | 84 | 99% |
| 2 | GitHub provider (auth, webhooks, reviews) | 130 | 91% |
| 3 | AI agent (tool loop, prompts, pipeline) | 182 | 82% |
| 4 | Queue (workers, dedup, cancellation) | 210 | 85% |
| 5 | Server (FastAPI, middleware, routes) | 223 | 85% |
| 6 | CI/CD (Actions, Docker, security) | 223 | 85% |
