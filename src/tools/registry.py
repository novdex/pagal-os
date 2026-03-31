"""PAGAL OS Tool Registry — plugin system for registering and executing tools."""

import importlib
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("pagal_os")

# Global tool registry: name -> {"function": callable, "schema": dict}
TOOLS: dict[str, dict[str, Any]] = {}


def register_tool(
    name: str,
    function: Callable,
    description: str,
    parameters: dict[str, Any],
) -> None:
    """Register a tool in the global registry.

    Args:
        name: Unique tool name (e.g. 'search_web').
        function: The callable that implements the tool.
        description: Human-readable description of what the tool does.
        parameters: JSON Schema dict describing the tool's parameters.
    """
    TOOLS[name] = {
        "function": function,
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        },
    }
    logger.debug("Registered tool: %s", name)


def get_tool(name: str) -> Callable | None:
    """Get a tool function by name.

    Args:
        name: The tool name.

    Returns:
        The tool callable, or None if not found.
    """
    entry = TOOLS.get(name)
    return entry["function"] if entry else None


def get_tool_schemas(tool_names: list[str]) -> list[dict]:
    """Get OpenAI function-calling schemas for the given tool names.

    Args:
        tool_names: List of tool names to get schemas for.

    Returns:
        List of tool schema dicts in OpenAI function-calling format.
    """
    schemas = []
    for name in tool_names:
        entry = TOOLS.get(name)
        if entry:
            schemas.append(entry["schema"])
        else:
            logger.warning("Tool '%s' not found in registry", name)
    return schemas


def list_tools() -> list[str]:
    """List all registered tool names.

    Returns:
        Sorted list of tool name strings.
    """
    return sorted(TOOLS.keys())


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a registered tool by name.

    Args:
        name: The tool name.
        args: Dict of arguments to pass to the tool function.

    Returns:
        Dict with 'ok' and 'result' or 'error' keys.
    """
    entry = TOOLS.get(name)
    if not entry:
        logger.error("Tool '%s' not found", name)
        return {"ok": False, "error": f"Tool '{name}' not found"}

    try:
        result = entry["function"](**args)
        return result if isinstance(result, dict) else {"ok": True, "result": result}
    except Exception as e:
        logger.error("Tool '%s' failed: %s", name, e, exc_info=True)
        return {"ok": False, "error": f"Tool '{name}' failed: {e}"}


def load_custom_tools(tools_dir: Path | None = None) -> int:
    """Load custom tool plugins from a directory.

    Each .py file in the directory is imported, which triggers its
    module-level register_tool() calls.

    Args:
        tools_dir: Path to the tools directory. Defaults to ~/.pagal-os/tools/.

    Returns:
        Number of plugin files loaded.
    """
    if tools_dir is None:
        tools_dir = Path.home() / ".pagal-os" / "tools"

    if not tools_dir.exists():
        return 0

    loaded = 0
    for py_file in tools_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"pagal_custom_tool_{py_file.stem}", py_file
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                loaded += 1
                logger.info("Loaded custom tool plugin: %s", py_file.name)
        except Exception as e:
            logger.warning("Failed to load custom tool %s: %s", py_file, e)

    return loaded
