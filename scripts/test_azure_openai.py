"""Standalone Azure OpenAI connectivity and agent test.

Tests the AI agent loop with a real Azure OpenAI call — no GitHub needed.
Verifies: client creation, tool-use loop, JSON response parsing.

Usage:
    python scripts/test_azure_openai.py

Requires .env with AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and optionally
AZURE_OPENAI_DEPLOYMENT (defaults to review_model from config).
"""

from __future__ import annotations

import asyncio
import sys

from reviewer.config import Settings
from reviewer.reviewer.agent import run_review_agent
from reviewer.reviewer.prompts import SYSTEM_PROMPT
from reviewer.reviewer.tools import ToolExecutor


async def main() -> None:
    print("=== Azure OpenAI Agent E2E Test ===\n")

    # Load config
    try:
        settings = Settings()
    except Exception as e:
        print(f"FAIL: config error — {e}")
        print("Make sure .env is configured (copy from .env.example)")
        sys.exit(1)

    print(f"Endpoint: {settings.azure_openai_endpoint}")
    print(f"Model:    {settings.review_model}")

    # Build OpenAI client
    from openai import AsyncAzureOpenAI

    kwargs: dict[str, object] = {
        "azure_endpoint": settings.azure_openai_endpoint,
        "api_version": settings.azure_openai_api_version,
    }
    if settings.azure_openai_api_key is not None:
        kwargs["api_key"] = settings.azure_openai_api_key.get_secret_value()

    client = AsyncAzureOpenAI(**kwargs)  # type: ignore[arg-type]

    # Simple connectivity test
    print("\n--- Step 1: Connectivity ---")
    try:
        resp = await client.chat.completions.create(
            model=settings.review_model,
            messages=[{"role": "user", "content": "Respond with just: OK"}],
            max_tokens=5,
        )
        content = resp.choices[0].message.content
        print(f"Response: {content}")
        print(f"Tokens:   {resp.usage.total_tokens if resp.usage else 'unknown'}")
        print("PASS: Azure OpenAI reachable\n")
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)

    # Agent loop test with a fake diff
    print("--- Step 2: Agent Loop ---")

    fake_files: dict[str, str] = {
        "src/auth.py": (
            "import os\n"
            "DB_PASSWORD = os.environ['DB_PASSWORD']\n"
            "def login(username, password):\n"
            "    query = f'SELECT * FROM users WHERE name={username}'\n"
            "    return query\n"
        ),
    }

    async def get_file(path: str) -> str:
        if path in fake_files:
            return fake_files[path]
        return f"error: file not found: {path}"

    tool_executor = ToolExecutor(get_file_fn=get_file)

    user_prompt = """## Pull Request #1: Add login function
**Author:** testdev
**Branch:** feat/login → main

### ~ src/auth.py (+5/-0)
```diff
@@ -0,0 +1,5 @@
+import os
+DB_PASSWORD = os.environ['DB_PASSWORD']
+def login(username, password):
+    query = f'SELECT * FROM users WHERE name={username}'
+    return query
```

Review the changes above. Use tools to fetch full file content when needed."""

    try:
        result, trace = await run_review_agent(
            client=client,
            model=settings.review_model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tool_executor=tool_executor,
            max_iterations=5,
        )

        print(f"Iterations: {len(trace.steps)}")
        print(f"Tokens:     {trace.total_tokens}")
        print(f"Duration:   {trace.duration_seconds:.1f}s")
        print(f"Findings:   {len(result.get('findings', []))}")
        print(f"Summary:    {result.get('summary', 'none')[:200]}")

        # Check for expected findings (SQL injection is obvious)
        findings = result.get("findings", [])
        if findings:
            print("\nFindings:")
            for f in findings:
                print(f"  [{f.get('severity', '?')}] {f.get('path', '?')}:{f.get('line', '?')} — {f.get('message', '?')[:100]}")

        # Trace
        print("\nAgent trace:")
        for step in trace.steps:
            if step.tool_name:
                print(f"  Step {step.step_number}: {step.tool_name}({step.tool_arguments}) → {len(step.tool_result)} chars")
            elif step.error:
                print(f"  Step {step.step_number}: error — {step.error}")
            else:
                print(f"  Step {step.step_number}: final response")

        print("\nPASS: Agent loop completed successfully")

    except Exception as e:
        print(f"FAIL: agent error — {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
