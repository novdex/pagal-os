"""PAGAL OS tools — registry and built-in tools.

Importing this package auto-registers all built-in tools.
"""

from src.tools.registry import register_tool, get_tool, get_tool_schemas, list_tools, execute_tool  # noqa: F401
from src.tools import search, files, shell, browser  # noqa: F401
