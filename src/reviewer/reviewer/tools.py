"""Tool definitions and executor for the AI review agent.

Tools let GPT-5.4 inspect the repository during review.
Each tool has a JSON Schema definition and an async executor.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from reviewer.exceptions import ToolError

logger = structlog.get_logger()

# Maximum file content size to return (prevent context blowup)
MAX_FILE_CONTENT_BYTES = 100_000
MAX_SEARCH_RESULTS = 20
MAX_DIRECTORY_ENTRIES = 200


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_file_content",
            "description": (
                "Retrieve the full content of a file from the repository at the PR's head ref. "
                "Use this to read source files referenced in the diff."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to repository root",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_codebase",
            "description": (
                "Search the repository for files matching a pattern. "
                "Use this to find related files, tests, or usages of a function/class."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term (filename pattern or text)",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Glob pattern to filter files (e.g. '*.py')",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List files and subdirectories in a directory. "
                "Use this to understand project structure."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to repo root ('.' for root)",
                    },
                },
                "required": ["path"],
            },
        },
    },
]


def validate_path(path: str) -> str:
    """Sanitize and validate a file path.

    Rejects absolute paths and path traversal attempts.
    Returns the normalized path.

    Raises ToolError for invalid paths.
    """
    if not path:
        raise ToolError("empty path", tool_name="validate_path")

    # Reject absolute paths
    if path.startswith("/") or path.startswith("\\"):
        raise ToolError("absolute paths are not allowed", tool_name="validate_path")

    # Reject path traversal
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if ".." in parts:
        raise ToolError("path traversal (..) is not allowed", tool_name="validate_path")

    return normalized


class ToolExecutor:
    """Executes tool calls from the AI agent.

    Uses a provider to interact with the repository via the SCM API.
    All file paths are sanitized before use.
    """

    def __init__(
        self,
        get_file_fn: Callable[[str], Awaitable[str]],
        search_fn: Callable[[str, str | None], Awaitable[list[str]]] | None = None,
        list_dir_fn: Callable[[str], Awaitable[list[str]]] | None = None,
    ) -> None:
        self._get_file = get_file_fn
        self._search = search_fn
        self._list_dir = list_dir_fn

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool call and return the result as a string.

        Raises ToolError for unknown tools or execution failures.
        """
        logger.debug("executing tool", tool=tool_name, arguments=arguments)

        match tool_name:
            case "get_file_content":
                return await self._execute_get_file(arguments)
            case "search_codebase":
                return await self._execute_search(arguments)
            case "list_directory":
                return await self._execute_list_directory(arguments)
            case _:
                raise ToolError(f"unknown tool: {tool_name}", tool_name=tool_name)

    async def _execute_get_file(self, arguments: dict[str, Any]) -> str:
        """Fetch file content with path validation and size limiting."""
        path = validate_path(arguments.get("path", ""))

        try:
            content: str = await self._get_file(path)
        except Exception as exc:
            raise ToolError(
                f"failed to read file {path}: {exc}",
                tool_name="get_file_content",
            ) from exc

        if len(content.encode()) > MAX_FILE_CONTENT_BYTES:
            return content[: MAX_FILE_CONTENT_BYTES // 2] + "\n\n... [truncated] ..."

        return content

    async def _execute_search(self, arguments: dict[str, Any]) -> str:
        """Search codebase with result limiting."""
        query = arguments.get("query", "")
        if not query:
            raise ToolError("empty search query", tool_name="search_codebase")

        if self._search is None:
            return "search_codebase tool is not available for this provider"

        try:
            results: list[str] = await self._search(query, arguments.get("file_pattern"))
        except Exception as exc:
            raise ToolError(
                f"search failed: {exc}",
                tool_name="search_codebase",
            ) from exc

        truncated = results[:MAX_SEARCH_RESULTS]
        if len(results) > MAX_SEARCH_RESULTS:
            truncated.append(f"... and {len(results) - MAX_SEARCH_RESULTS} more results")

        return "\n".join(truncated)

    async def _execute_list_directory(self, arguments: dict[str, Any]) -> str:
        """List directory contents with entry limiting."""
        path = validate_path(arguments.get("path", "."))

        if self._list_dir is None:
            return "list_directory tool is not available for this provider"

        try:
            entries: list[str] = await self._list_dir(path)
        except Exception as exc:
            raise ToolError(
                f"failed to list directory {path}: {exc}",
                tool_name="list_directory",
            ) from exc

        truncated = entries[:MAX_DIRECTORY_ENTRIES]
        if len(entries) > MAX_DIRECTORY_ENTRIES:
            truncated.append(f"... and {len(entries) - MAX_DIRECTORY_ENTRIES} more entries")

        return "\n".join(truncated)
