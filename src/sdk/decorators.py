"""SDK decorators — mark methods as agent tools."""

from typing import Any, Callable


def tool(description: str) -> Callable[..., Any]:
    """Decorator that registers an agent method as a callable tool.

    Usage::

        class MyAgent(Agent):
            @tool("Search the web for information")
            def search(self, query: str) -> str:
                ...

    Args:
        description: Human-readable description of what the tool does.

    Returns:
        The original method, annotated with ``_tool_meta``.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func._tool_meta = {  # type: ignore[attr-defined]
            "name": func.__name__,
            "description": description,
        }
        return func

    return decorator
