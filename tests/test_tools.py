"""Tests for PAGAL OS tool registry and built-in tools."""

import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tools.registry import (
    TOOLS,
    execute_tool,
    get_tool,
    get_tool_schemas,
    list_tools,
    register_tool,
)


class TestToolRegistry:
    """Test the tool registry system."""

    def test_register_and_get_tool(self) -> None:
        """Should register a tool and retrieve it."""
        def dummy_tool(x: str) -> dict:
            """A dummy tool."""
            return {"ok": True, "result": x}

        register_tool(
            name="test_dummy",
            function=dummy_tool,
            description="A test tool",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
        )

        assert "test_dummy" in TOOLS
        assert get_tool("test_dummy") is dummy_tool

        # Clean up
        del TOOLS["test_dummy"]

    def test_get_nonexistent_tool(self) -> None:
        """Should return None for unknown tool."""
        assert get_tool("nonexistent_tool_xyz") is None

    def test_list_tools(self) -> None:
        """Should list registered tool names."""
        # Import tools to register them
        import src.tools  # noqa: F401

        tools = list_tools()
        assert isinstance(tools, list)
        assert "search_web" in tools
        assert "read_file" in tools
        assert "write_file" in tools
        assert "run_shell" in tools
        assert "browse_url" in tools

    def test_get_tool_schemas(self) -> None:
        """Should return OpenAI-format schemas for given tools."""
        import src.tools  # noqa: F401

        schemas = get_tool_schemas(["search_web", "read_file"])
        assert len(schemas) == 2
        assert schemas[0]["type"] == "function"
        assert "name" in schemas[0]["function"]
        assert "description" in schemas[0]["function"]
        assert "parameters" in schemas[0]["function"]

    def test_execute_tool_success(self) -> None:
        """Should execute a registered tool successfully."""
        def adder(a: int, b: int) -> dict:
            """Add two numbers."""
            return {"ok": True, "result": a + b}

        register_tool(
            name="test_adder",
            function=adder,
            description="Add numbers",
            parameters={"type": "object", "properties": {}},
        )

        result = execute_tool("test_adder", {"a": 2, "b": 3})
        assert result["ok"] is True
        assert result["result"] == 5

        # Clean up
        del TOOLS["test_adder"]

    def test_execute_unknown_tool(self) -> None:
        """Should return error for unknown tool."""
        result = execute_tool("totally_unknown_tool", {})
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_execute_tool_with_exception(self) -> None:
        """Should catch exceptions from tools."""
        def bad_tool() -> dict:
            """A tool that crashes."""
            raise ValueError("intentional error")

        register_tool(
            name="test_bad",
            function=bad_tool,
            description="Bad tool",
            parameters={"type": "object", "properties": {}},
        )

        result = execute_tool("test_bad", {})
        assert result["ok"] is False
        assert "intentional error" in result["error"]

        # Clean up
        del TOOLS["test_bad"]


class TestFileTools:
    """Test the file read/write tools."""

    def test_read_file(self, tmp_path: Path) -> None:
        """Should read file contents."""
        import src.tools  # noqa: F401

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        result = execute_tool("read_file", {"path": str(test_file)})
        assert result["ok"] is True
        assert result["result"] == "hello world"

    def test_read_nonexistent_file(self) -> None:
        """Should return error for missing file."""
        import src.tools  # noqa: F401

        result = execute_tool("read_file", {"path": "/nonexistent/file.txt"})
        assert result["ok"] is False

    def test_write_file(self, tmp_path: Path) -> None:
        """Should write content to a file."""
        import src.tools  # noqa: F401

        test_file = tmp_path / "output.txt"
        result = execute_tool("write_file", {"path": str(test_file), "content": "test content"})
        assert result["ok"] is True
        assert test_file.read_text() == "test content"


class TestShellTool:
    """Test the shell command tool."""

    def test_run_shell_echo(self) -> None:
        """Should execute a simple echo command."""
        import src.tools  # noqa: F401

        result = execute_tool("run_shell", {"command": "echo hello"})
        assert result["ok"] is True
        assert "hello" in result["result"]

    def test_run_shell_timeout(self) -> None:
        """Should timeout long-running commands."""
        import src.tools  # noqa: F401

        # Use a command that takes too long
        result = execute_tool("run_shell", {"command": "ping -n 100 127.0.0.1", "timeout": 1})
        assert result["ok"] is False
        assert "timed out" in result.get("error", "").lower()
