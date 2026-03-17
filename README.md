# AI PR Reviewer

AI-powered pull request review agent built with Python, FastAPI, and Azure OpenAI GPT-5.4.

Receives GitHub webhooks, runs an autonomous tool-use review loop, and posts inline comments with actionable findings.

## How It Works

```
GitHub Webhook → FastAPI → Worker Pool → AI Agent Loop → Post Review
                   │                         │
                   ├─ Signature verify        ├─ get_file_content
                   ├─ Rate limiting           ├─ search_codebase
                   └─ Dedup                   └─ list_directory
```

1. **Webhook arrives** — GitHub sends a `pull_request` event (opened, synchronize, reopened)
2. **Signature verified** — HMAC-SHA256 with constant-time comparison
3. **Deduplicated** — TTL-based check prevents processing the same delivery twice
4. **Queued** — Bounded asyncio queue with configurable concurrency
5. **AI reviews** — GPT-5.4 examines the diff, uses tools to fetch files, produces structured findings
6. **Results posted** — Inline comments on the PR with severity-based review event (REQUEST_CHANGES for critical/high)

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12+ |
| Web framework | FastAPI + uvicorn |
| AI | Azure OpenAI GPT-5.4 (tool use) |
| HTTP client | httpx (async) |
| Data models | Pydantic v2 (frozen) |
| Auth | PyJWT (RS256 GitHub App JWTs) |
| Config | pydantic-settings |
| Logging | structlog (JSON) |
| Testing | pytest + pytest-asyncio |
| Linting | ruff |
| Type checking | mypy (strict) |
| CI/CD | GitHub Actions |
| Container | Docker (multi-stage, non-root) |

## Quick Start

### Prerequisites

- Python 3.12+
- Azure OpenAI resource with GPT-5.4 deployment
- GitHub App with webhook configured

### Setup

```bash
git clone https://github.com/Slagri/ai-pr-reviewer-python.git
cd ai-pr-reviewer-python

python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env with your Azure OpenAI and GitHub App credentials
```

### Development

```bash
make check       # Run lint + typecheck + test
make run-debug   # Start server with hot reload
make validate PHASE=1  # Run phase milestone validation
```

### Docker

```bash
docker build -t ai-pr-reviewer .
docker run -p 8000:8000 --env-file .env ai-pr-reviewer

# Or with docker-compose:
docker-compose up
```

## Configuration

All configuration via environment variables. See [.env.example](.env.example) for the full list.

### Required

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource URL (`https://your-resource.openai.azure.com`) |
| `AZURE_OPENAI_API_KEY` | API key (omit for managed identity) |

### GitHub Provider

| Variable | Description |
|----------|-------------|
| `GITHUB_APP_ID` | GitHub App ID |
| `GITHUB_PRIVATE_KEY` | PEM content (or use `GITHUB_PRIVATE_KEY_PATH`) |
| `GITHUB_WEBHOOK_SECRET` | Webhook HMAC secret |

### Per-Repository Config

Drop a `.reviewer.yaml` in your repository root. See [.reviewer.yaml.example](.reviewer.yaml.example).

## Architecture

```
src/reviewer/
├── main.py                  # FastAPI app factory, lifecycle
├── config.py                # pydantic-settings env loading
├── models.py                # Shared Pydantic models (frozen)
├── exceptions.py            # Custom exception hierarchy
├── providers/
│   ├── base.py              # Provider protocol (typing.Protocol)
│   └── github/
│       ├── client.py        # JWT auth, installation tokens
│       ├── webhook.py       # Parse + verify webhooks
│       └── review.py        # Post reviews, check runs, file ops
├── reviewer/
│   ├── agent.py             # Tool-use loop with Azure OpenAI
│   ├── tools.py             # Tool definitions + executor
│   ├── prompts.py           # System + user prompt templates
│   ├── pipeline.py          # Orchestration: check → diff → review → post
│   └── trace.py             # Agent trace recording
├── queue/
│   ├── worker.py            # Async worker pool
│   ├── dedup.py             # TTL-based deduplication
│   └── cancel.py            # Superseded review cancellation
├── middleware/
│   ├── signature.py         # HMAC-SHA256 verification
│   ├── ratelimit.py         # Token bucket per-IP
│   └── logging.py           # Structured request logging
└── server/
    ├── routes.py            # Webhook + health endpoints
    └── dependencies.py      # FastAPI DI providers
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/webhook/github` | Receive GitHub webhook events |
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe with config checks |
| GET | `/metrics` | Uptime metrics |

## Testing

```bash
make test                    # Run with coverage (80% minimum)
make validate PHASE=N        # Phase milestone validation
pytest -k "test_agent"       # Run specific test group
pytest --tb=long -v          # Verbose output
```

223 tests covering config validation, webhook parsing, JWT auth, tool execution, agent loop behavior, rate limiting, and route handling.

## CI/CD

- **CI** — ruff lint, mypy strict, pytest with coverage gate, Docker build
- **Security** — pip-audit + bandit (on push + weekly schedule)
- **Dependabot** — automated updates for pip + GitHub Actions

## License

[MIT](LICENSE)
