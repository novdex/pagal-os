"""PAGAL OS Search Tool — web search via DuckDuckGo."""

import logging
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


def search_web(query: str, num_results: int = 5) -> dict[str, Any]:
    """Search the web using DuckDuckGo.

    Args:
        query: The search query string.
        num_results: Maximum number of results to return.

    Returns:
        Dict with 'ok' and 'result' (list of {title, url, snippet}) keys.
    """
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })

        logger.info("Search '%s' returned %d results", query, len(results))
        return {"ok": True, "result": results}

    except ImportError:
        logger.error("duckduckgo-search package not installed")
        return {"ok": False, "error": "duckduckgo-search package not installed"}
    except Exception as e:
        logger.error("Search failed for '%s': %s", query, e)
        return {"ok": False, "error": f"Search failed: {e}"}


# Auto-register on import
register_tool(
    name="search_web",
    function=search_web,
    description="Search the web using DuckDuckGo and return results with titles, URLs, and snippets.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "num_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
)
