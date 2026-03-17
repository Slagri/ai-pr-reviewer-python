"""Tests for tool definitions and executor."""

from __future__ import annotations

import pytest

from reviewer.exceptions import ToolError
from reviewer.reviewer.tools import (
    TOOL_DEFINITIONS,
    ToolExecutor,
    validate_path,
)


class TestValidatePath:
    """Test file path sanitization."""

    @pytest.mark.parametrize(
        "path",
        [
            "src/main.py",
            "README.md",
            "nested/deep/file.txt",
            ".",
        ],
    )
    def test_valid_paths(self, path: str) -> None:
        assert validate_path(path) == path.replace("\\", "/")

    @pytest.mark.parametrize(
        ("path", "error_match"),
        [
            ("", "empty path"),
            ("/etc/passwd", "absolute"),
            ("\\windows\\system32", "absolute"),
            ("src/../../../etc/passwd", "traversal"),
            ("../secret", "traversal"),
        ],
    )
    def test_invalid_paths(self, path: str, error_match: str) -> None:
        with pytest.raises(ToolError, match=error_match):
            validate_path(path)

    def test_normalizes_backslashes(self) -> None:
        assert validate_path("src\\main.py") == "src/main.py"


class TestToolDefinitions:
    """Test tool definition structure."""

    def test_all_tools_have_required_fields(self) -> None:
        for tool in TOOL_DEFINITIONS:
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_tool_names(self) -> None:
        names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
        assert "get_file_content" in names
        assert "search_codebase" in names
        assert "list_directory" in names


class TestToolExecutor:
    """Test tool execution."""

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        async def mock_get_file(path: str) -> str:
            if path == "src/main.py":
                return "print('hello')"
            raise FileNotFoundError(f"not found: {path}")

        async def mock_search(query: str, pattern: str | None = None) -> list[str]:
            return ["src/main.py", "src/utils.py"]

        async def mock_list_dir(path: str) -> list[str]:
            return ["src/", "tests/", "README.md"]

        return ToolExecutor(
            get_file_fn=mock_get_file,
            search_fn=mock_search,
            list_dir_fn=mock_list_dir,
        )

    @pytest.mark.asyncio
    async def test_get_file_content(self, executor: ToolExecutor) -> None:
        result = await executor.execute("get_file_content", {"path": "src/main.py"})
        assert result == "print('hello')"

    @pytest.mark.asyncio
    async def test_get_file_not_found(self, executor: ToolExecutor) -> None:
        with pytest.raises(ToolError, match="failed to read"):
            await executor.execute("get_file_content", {"path": "nonexistent.py"})

    @pytest.mark.asyncio
    async def test_get_file_path_traversal(self, executor: ToolExecutor) -> None:
        with pytest.raises(ToolError, match="traversal"):
            await executor.execute("get_file_content", {"path": "../../../etc/passwd"})

    @pytest.mark.asyncio
    async def test_search_codebase(self, executor: ToolExecutor) -> None:
        result = await executor.execute("search_codebase", {"query": "main"})
        assert "src/main.py" in result
        assert "src/utils.py" in result

    @pytest.mark.asyncio
    async def test_search_empty_query(self, executor: ToolExecutor) -> None:
        with pytest.raises(ToolError, match="empty search"):
            await executor.execute("search_codebase", {"query": ""})

    @pytest.mark.asyncio
    async def test_list_directory(self, executor: ToolExecutor) -> None:
        result = await executor.execute("list_directory", {"path": "."})
        assert "src/" in result
        assert "tests/" in result

    @pytest.mark.asyncio
    async def test_unknown_tool(self, executor: ToolExecutor) -> None:
        with pytest.raises(ToolError, match="unknown tool"):
            await executor.execute("nonexistent_tool", {})

    @pytest.mark.asyncio
    async def test_search_unavailable(self) -> None:
        executor = ToolExecutor(get_file_fn=lambda p: "")
        result = await executor.execute("search_codebase", {"query": "test"})
        assert "not available" in result

    @pytest.mark.asyncio
    async def test_list_dir_unavailable(self) -> None:
        executor = ToolExecutor(get_file_fn=lambda p: "")
        result = await executor.execute("list_directory", {"path": "."})
        assert "not available" in result

    @pytest.mark.asyncio
    async def test_large_file_truncated(self) -> None:
        large_content = "x" * 200_000

        async def get_large_file(path: str) -> str:
            return large_content

        executor = ToolExecutor(get_file_fn=get_large_file)
        result = await executor.execute("get_file_content", {"path": "big.txt"})
        assert "truncated" in result
        assert len(result) < len(large_content)
