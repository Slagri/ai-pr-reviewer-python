# Claude Code Bootstrap Instructions

Read this entire document before doing anything. This is your setup guide and operating manual.

---

## Step 1: Set Up Claude Code Environment

### 1.1 Create CLAUDE.md

Create `CLAUDE.md` in the project root with the contents from the PROJECT-PLAN.md architecture section, plus these operational rules:

```markdown
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
```

### 1.2 Create .claude/settings.json

```json
{
  "permissions": {
    "allow": [
      "Bash(make *)",
      "Bash(git *)",
      "Bash(pytest *)",
      "Bash(ruff *)",
      "Bash(mypy *)",
      "Bash(pip *)",
      "Bash(python *)",
      "Bash(uv *)",
      "Bash(docker *)",
      "Bash(gh *)",
      "Bash(cat *)",
      "Bash(ls *)",
      "Bash(cd *)",
      "Bash(mkdir *)",
      "Read",
      "Edit",
      "Write",
      "Glob",
      "Grep"
    ],
    "deny": [
      "Bash(rm -rf *)",
      "Read(.env)"
    ]
  },
  "attribution": {
    "commit": "",
    "pr": ""
  }
}
```

### 1.3 Create .claude/agents/ for Subagents

Create agent definitions for heavy-lifting work:

**`.claude/agents/test-runner.md`**:
```yaml
---
name: test-runner
description: Run tests and report results. Use after writing code.
tools: Bash, Read, Grep, Glob
model: sonnet
---

Run the test suite and report results concisely.
1. Run: pytest --tb=short -q
2. If failures, read the failing test and source files
3. Report: which tests failed, why, and suggested fix
Do NOT fix code — just report findings.
```

**`.claude/agents/code-reviewer.md`**:
```yaml
---
name: code-reviewer
description: Review code for quality, security, and patterns. Use after writing code.
tools: Read, Grep, Glob, Bash
disallowedTools: Write, Edit
model: sonnet
---

Review the recently changed code. Run git diff to see changes.
Check for:
- Security issues (hardcoded secrets, injection, missing validation)
- Error handling gaps
- Type safety issues
- Missing tests for new code
- Python anti-patterns
- Pydantic model correctness
Report findings as: CRITICAL, WARNING, SUGGESTION.
```

**`.claude/agents/doc-writer.md`**:
```yaml
---
name: doc-writer
description: Write documentation, README, docstrings. Use for documentation tasks.
tools: Read, Write, Edit, Glob, Grep, Bash
model: sonnet
---

Write clear, accurate documentation. Verify all claims against actual code.
- README sections must match real commands and config
- Docstrings follow Google style
- Keep docs concise and actionable
```

### 1.4 Create .gitignore

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.eggs/
*.egg

# Virtual environment
.venv/
venv/

# Test
.coverage
htmlcov/
.pytest_cache/
coverage.xml

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
Thumbs.db

# Environment
.env
.env.local
*.pem
*.key

# Claude Code
.claude/settings.local.json

# Private docs
docs/private/
```

---

## Step 2: Initialize Git Repository

```bash
git init
git add .gitignore
git commit -m "chore: initialize repository"
```

Create the GitHub repo immediately:
```bash
gh repo create ai-pr-reviewer --public --description "AI-powered PR review agent built in Python with FastAPI and Azure OpenAI GPT-5.4. Agentic tool-use loop, webhook-driven, production-grade." --source=. --push
```

Set up branch protection after first push.

---

## Step 3: Development Workflow

### For Each Phase:

1. **Create feature branch**: `git checkout -b feat/<phase-name>`
2. **Write tests FIRST** (TDD): Define expected behavior
3. **Implement**: Write code to pass tests
4. **Run checks**: `make check` (lint + typecheck + test)
5. **Use code-reviewer agent**: Review your own code
6. **Commit**: Conventional commit message, no co-authored-by
7. **Push + PR**: `git push -u origin feat/<phase-name>`, create PR
8. **Merge to main**: Squash merge after CI passes

### Context Management:

- **Between phases**: Run `/clear` to reset context. Start fresh with "Implement Phase N" prompt.
- **Large phases**: Use `/compact` with a focus note halfway through.
- **Heavy research**: Delegate to Explore subagent, don't fill main context.
- **Testing**: Delegate to test-runner agent after implementation.
- **Review**: Delegate to code-reviewer agent after tests pass.

### Commit Discipline:

- Commit after each logical unit of work (not every file)
- Every commit must compile and pass tests
- Group related changes (model + test + fixture = 1 commit)
- NEVER use `--no-verify` or skip hooks
- NEVER add co-authored-by signatures

---

## Step 4: Browse Documentation When Needed

You MUST browse live documentation for accuracy. Don't rely on training data for API specifics.

### When implementing Azure OpenAI integration:
- Browse: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/function-calling
- Browse: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/streaming
- Browse: https://github.com/openai/openai-python (SDK examples)

### When implementing GitHub webhook handling:
- Browse: https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request
- Browse: https://docs.github.com/en/rest/pulls/reviews
- Browse: https://docs.github.com/en/rest/checks/runs

### When implementing Azure DevOps:
- Browse: https://learn.microsoft.com/en-us/azure/devops/service-hooks/events
- Browse: https://learn.microsoft.com/en-us/rest/api/azure/devops/git/pull-request-threads

### For Python libraries:
- Browse PyPI / official docs for latest API of any library you use

---

## Step 5: Quality Gates

Before marking any phase complete:

1. `ruff check src/ tests/` — zero warnings
2. `ruff format --check src/ tests/` — properly formatted
3. `mypy --strict src/` — zero type errors
4. `pytest --cov=src/reviewer --cov-fail-under=80` — tests pass, 80%+ coverage
5. Code review via code-reviewer agent
6. Commit with meaningful message

Before final publish:

1. All phases complete
2. README accurate (verified against code)
3. No hardcoded secrets anywhere
4. No personal references
5. .env.example has all vars with placeholder values
6. LICENSE file present (MIT)
7. Docker build succeeds
8. Git history is clean (squash if needed)

---

## Step 6: Implementation Order

Execute phases in order. Each phase builds on the previous.

1. **Phase 1: Foundation** — pyproject.toml, config, shared models, Makefile
2. **Phase 2: GitHub Provider** — auth, webhooks, review posting, signature verification
3. **Phase 3: AI Agent Core** — Azure OpenAI tool-use loop, prompts, pipeline
4. **Phase 4: Queue & Scalability** — async workers, dedup, cancellation
5. **Phase 5: Server & Security** — FastAPI app, middleware, routes, health
6. **Phase 6: CI/CD** — GitHub Actions, Docker, security scanning
7. **Phase 7: Documentation** — README, logbook, examples
8. **Phase 8: Publish** — Clean history, verify, push to GitHub

---

## Critical Reminders

- **NEVER commit co-authored-by lines** — attribution is disabled in settings
- **ALWAYS write tests first** (TDD) — red → green → refactor
- **ALWAYS browse docs** for API specifics — don't guess
- **Use agents** for test running and code review — preserve main context
- **Commit frequently** — after each logical unit, not at end of phase
- **Run `make check`** before every commit
- **Update docs/LOGBOOK.md** after significant design decisions
- **Keep CLAUDE.md under 200 lines** — prune ruthlessly
- **Use `/compact` between tasks** to manage context
- **Reference Go version** for architecture, but write idiomatic Python
