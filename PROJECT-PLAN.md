# AI PR Reviewer — Python + Azure OpenAI

## What This Is

An AI-powered pull request review agent built in Python with FastAPI. It receives webhooks from GitHub (and optionally Azure DevOps), runs an autonomous GPT-5.4-powered review loop with tool use, and posts inline comments with actionable findings. Deployed on Azure.

This is a public open-source project demonstrating: Python proficiency, agentic AI with Azure OpenAI tool-use loops, prompt engineering, fullstack development, Azure cloud deployment, CI/CD, security, and testing.

## Reference Implementation

A Go version of this project exists at `~/Desktop/Apps/reviewer/`. Use it as architectural reference — the Python version should match its capabilities but use idiomatic Python patterns, Azure OpenAI instead of Anthropic, and FastAPI instead of stdlib net/http. Read the Go version's CLAUDE.md and source code when you need to understand design decisions, but DO NOT copy Go patterns into Python — translate them idiomatically.

---

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.12+ | Job requirement |
| Web framework | FastAPI + uvicorn | Async, auto OpenAPI docs, dependency injection |
| AI | Azure OpenAI GPT-5.4 via `openai` SDK | Job requirement (Azure OpenAI) |
| HTTP client | httpx (async) | Modern async HTTP with streaming support |
| Data models | Pydantic v2 | Validation, serialization, settings management |
| Auth | PyJWT + cryptography | GitHub App JWT (RS256) |
| Rate limiting | Custom token bucket or aiolimiter | Per-IP rate limiting |
| Config | pydantic-settings | Environment variable loading with validation |
| YAML | pyyaml | Per-repo .reviewer.yaml parsing |
| Testing | pytest + pytest-asyncio + pytest-cov | Async test support, coverage |
| Linting | ruff | Fast, replaces flake8+isort+black |
| Type checking | mypy (strict) | Static type safety |
| CI/CD | GitHub Actions | Lint, type check, test, build |
| Containerization | Docker (multi-stage) | Alpine-based, non-root |
| Azure deploy | Azure Container Apps | Serverless containers, managed identity |

### External Dependencies (keep minimal)
- `fastapi` + `uvicorn` — web framework
- `openai` — Azure OpenAI SDK (handles streaming, retries, tool use)
- `httpx` — async HTTP client for GitHub/Azure DevOps APIs
- `pydantic` + `pydantic-settings` — models and config
- `pyjwt[crypto]` — GitHub App JWT signing
- `pyyaml` — repo config parsing
- `structlog` — structured JSON logging
- `azure-identity` — Azure AD auth for OpenAI (production)

---

## Architecture

```
ai-pr-reviewer/
├── src/
│   └── reviewer/
│       ├── __init__.py
│       ├── main.py                 # FastAPI app factory, startup/shutdown lifecycle
│       ├── config.py               # pydantic-settings: env var loading + validation
│       ├── models.py               # Shared Pydantic models (Event, PR, Finding, Review)
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── base.py             # Provider protocol (abstract base)
│       │   ├── github/
│       │   │   ├── __init__.py
│       │   │   ├── client.py       # GitHub App auth (JWT + installation tokens)
│       │   │   ├── webhook.py      # Parse + verify GitHub webhooks
│       │   │   └── review.py       # Post reviews, check runs, file operations
│       │   └── azuredevops/
│       │       ├── __init__.py
│       │       ├── client.py       # Azure DevOps PAT auth
│       │       ├── webhook.py      # Parse + verify Azure DevOps webhooks
│       │       └── review.py       # Post PR threads, file operations
│       ├── reviewer/
│       │   ├── __init__.py
│       │   ├── agent.py            # Core tool-use loop with Azure OpenAI GPT-5.4
│       │   ├── tools.py            # Tool definitions (get_file_content, search_codebase, etc.)
│       │   ├── prompts.py          # System + user prompt templates
│       │   ├── pipeline.py         # Orchestrates: check run → fetch diffs → review → post
│       │   └── trace.py            # Agent trace recording for observability
│       ├── queue/
│       │   ├── __init__.py
│       │   ├── worker.py           # asyncio worker pool with bounded queue
│       │   ├── dedup.py            # TTL-based webhook deduplication
│       │   └── cancel.py           # Context cancellation for superseded reviews
│       ├── middleware/
│       │   ├── __init__.py
│       │   ├── signature.py        # HMAC-SHA256 webhook verification
│       │   ├── ratelimit.py        # Token bucket per-IP rate limiting
│       │   └── logging.py          # Structured request logging
│       └── server/
│           ├── __init__.py
│           ├── routes.py           # Webhook routes, health, metrics
│           └── dependencies.py     # FastAPI dependency injection
├── tests/
│   ├── conftest.py                 # Shared fixtures, async setup
│   ├── test_config.py
│   ├── providers/
│   │   ├── test_github_webhook.py
│   │   ├── test_github_review.py
│   │   ├── test_azuredevops_webhook.py
│   │   └── test_azuredevops_review.py
│   ├── reviewer/
│   │   ├── test_agent.py
│   │   ├── test_tools.py
│   │   ├── test_pipeline.py
│   │   └── test_prompts.py
│   ├── queue/
│   │   ├── test_worker.py
│   │   ├── test_dedup.py
│   │   └── test_cancel.py
│   └── server/
│       ├── test_routes.py
│       └── test_middleware.py
├── .github/
│   └── workflows/
│       ├── ci.yml                  # Lint + type check + test + build
│       └── security.yml            # pip-audit + bandit
├── infra/                          # Azure deployment (Bicep or Terraform)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml                  # Single source of truth for deps, tools config
├── .env.example
├── .reviewer.yaml.example
├── LICENSE                         # MIT
├── README.md
└── docs/
    └── LOGBOOK.md                  # Development decision log
```

---

## Azure OpenAI Integration Details

### API Endpoint
```
POST https://{resource}.openai.azure.com/openai/v1/chat/completions
```

### Authentication
- **Development**: `api-key` header
- **Production**: Azure Managed Identity via `DefaultAzureCredential` + `get_bearer_token_provider`

### Model: GPT-5.4
- Model ID: `gpt-5.4`
- Context: 1,000,000 tokens
- Max output: 128,000 tokens
- Supports: tool use (function calling), streaming, vision

### Tool Use Format (OpenAI style)
```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_file_content",
        "description": "Retrieve full file content from the repository",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root"}
            },
            "required": ["path"]
        }
    }
}]
```

### Tool-Use Loop
1. Send messages + tools to GPT-5.4 with `stream=True`
2. If `finish_reason == "tool_calls"`: execute tools, append results as `role: "tool"` messages, loop
3. If `finish_reason == "stop"`: parse JSON review from response, return
4. Max 10 iterations (configurable)

### Streaming
- OpenAI SSE format: `data: {json}\n\n` chunks, terminated by `data: [DONE]`
- Tool call arguments streamed incrementally — concatenate `function.arguments` across chunks
- The `openai` Python SDK handles streaming natively with `stream=True`

---

## Implementation Phases

### Phase 1: Foundation
- Project setup (pyproject.toml, ruff, mypy, pytest)
- Config loading with pydantic-settings
- Shared Pydantic models (Event, PullRequest, FileDiff, Finding, Review)
- Provider protocol (abstract base class)

### Phase 2: GitHub Provider
- GitHub App auth (JWT generation, installation token exchange + caching)
- Webhook parsing (pull_request events, action filtering, draft skip)
- HMAC-SHA256 signature verification
- File operations (get diff, get content, search code)
- Review posting (inline comments + summary)
- Check run creation/update

### Phase 3: AI Agent Core
- Azure OpenAI client with streaming
- Tool definitions (get_file_content, search_codebase, analyze_dependency, list_directory)
- Tool executor with path sanitization
- Agentic tool-use loop (call → execute tools → loop → parse result)
- System prompt and initial prompt construction
- Agent trace recording
- Review pipeline orchestration

### Phase 4: Queue & Scalability
- asyncio worker pool with bounded queue
- TTL-based webhook deduplication
- Context cancellation for superseded reviews
- Graceful shutdown (drain queue, cancel in-flight)

### Phase 5: Server & Security
- FastAPI app with middleware chain
- Webhook routes (POST /webhook/{provider})
- Health endpoints (/healthz, /readyz, /metrics)
- Request body size limiting
- Per-IP rate limiting (token bucket)
- Structured JSON logging with structlog

### Phase 6: Azure DevOps Provider (Optional)
- PAT-based auth
- Service Hook webhook parsing
- PR Thread commenting (one thread per finding)
- File operations via iterations API

### Phase 7: CI/CD & Deployment
- GitHub Actions: ruff lint + mypy type check + pytest with 80% coverage gate
- Security scanning: pip-audit + bandit
- Dockerfile (multi-stage, non-root, Alpine)
- docker-compose.yml
- Azure Container Apps deployment config
- Dependabot for pip + GitHub Actions

### Phase 8: Documentation & Polish
- README with architecture, setup, deployment instructions
- .env.example with all config vars
- .reviewer.yaml.example with documentation
- Development decision logbook
- MIT LICENSE

---

## Key Design Decisions

1. **Async everywhere**: FastAPI + httpx + asyncio queue — non-blocking I/O throughout
2. **Pydantic for all data**: Type-safe models with validation, serialization, OpenAPI docs
3. **Provider protocol**: Python Protocol class (structural subtyping) — no ABC inheritance
4. **Dependency injection**: FastAPI's Depends() for config, providers, queue — testable
5. **Immutability**: Pydantic models are frozen by default, use `model_copy()` not mutation
6. **Error handling**: Custom exception hierarchy, FastAPI exception handlers
7. **Structured logging**: structlog with JSON output, request correlation IDs
8. **OpenAI SDK**: Use the official `openai` package with `AzureOpenAI` client — don't raw-dog HTTP
9. **Testing**: pytest-asyncio for async tests, httpx mock transport for API mocking
10. **Single pyproject.toml**: All tool config (ruff, mypy, pytest) in one file

---

## Configuration (Environment Variables)

### Required
- `AZURE_OPENAI_ENDPOINT` — e.g., `https://my-resource.openai.azure.com`
- `AZURE_OPENAI_API_KEY` — or use managed identity
- `AZURE_OPENAI_DEPLOYMENT` — deployment name for GPT-5.4

### GitHub Provider
- `GITHUB_APP_ID`
- `GITHUB_PRIVATE_KEY` or `GITHUB_PRIVATE_KEY_PATH`
- `GITHUB_WEBHOOK_SECRET`

### Azure DevOps Provider (optional)
- `AZDO_ORGANIZATION`
- `AZDO_PAT`
- `AZDO_WEBHOOK_SECRET`

### Optional
- `PORT` (default: 8000)
- `LOG_LEVEL` (default: info)
- `WORKER_COUNT` (default: 5)
- `QUEUE_CAPACITY` (default: 100)
- `MAX_AGENT_ITERATIONS` (default: 10)
- `MAX_FILES_PER_REVIEW` (default: 50)
- `REVIEW_MODEL` (default: gpt-5.4)
- `SHUTDOWN_TIMEOUT` (default: 30)

---

## Testing Requirements

- **Minimum 80% coverage** enforced in CI
- **Unit tests**: All pure functions, Pydantic model validation, config loading
- **Integration tests**: Webhook parsing with real fixture payloads, API mocking with httpx
- **Agent tests**: Mock Azure OpenAI responses, verify tool-use loop behavior
- **Fixtures**: Real webhook payloads in `tests/fixtures/` (sanitized)
- **Async tests**: Use `pytest-asyncio` for all async code
- **Table-driven tests**: Use `@pytest.mark.parametrize` for pure functions

---

## Security Checklist

- [ ] All secrets via environment variables (pydantic-settings, never hardcoded)
- [ ] HMAC-SHA256 webhook signature verification with `hmac.compare_digest()`
- [ ] Constant-time secret comparison for Azure DevOps
- [ ] File path sanitization (reject absolute paths and `..` traversal)
- [ ] Response body size limits on all HTTP clients
- [ ] Request body size limits (10MB)
- [ ] Timeouts on all HTTP clients (30s default, 120s for Azure OpenAI)
- [ ] Per-IP rate limiting
- [ ] No secrets in log output
- [ ] Non-root Docker user
- [ ] GitHub Actions pinned to commit SHAs
- [ ] pip-audit for vulnerability scanning
- [ ] bandit for static security analysis

---

## Git Workflow

- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `ci:`, `docs:`, `chore:`
- NO co-authored-by lines in any commit
- Feature branches for phases, squash merge to main
- Each commit must pass: `ruff check`, `mypy`, `pytest`
- Meaningful commit messages that explain WHY, not WHAT
