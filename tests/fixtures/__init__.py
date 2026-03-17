"""Test fixture loading utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent


def load_json_fixture(relative_path: str) -> dict[str, Any]:
    """Load a JSON fixture file relative to the fixtures directory.

    Raises FileNotFoundError if the fixture doesn't exist.
    """
    path = FIXTURES_DIR / relative_path
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def load_github_fixture(name: str) -> dict[str, Any]:
    """Load a GitHub webhook fixture by name (without .json extension)."""
    return load_json_fixture(f"github/{name}.json")


def load_openai_fixture(name: str) -> dict[str, Any]:
    """Load an Azure OpenAI response fixture by name (without .json extension)."""
    return load_json_fixture(f"openai/{name}.json")


def load_streaming_chunks(name: str) -> list[dict[str, Any]]:
    """Load streaming SSE chunks from a fixture.

    Returns the 'chunks' array from the fixture file.
    These simulate the incremental data: lines in an SSE stream.
    """
    fixture = load_openai_fixture(name)
    chunks: list[dict[str, Any]] = fixture["chunks"]
    return chunks
