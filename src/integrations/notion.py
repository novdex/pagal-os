"""Notion Integration — search pages and create new pages in Notion.

Requires NOTION_API_KEY environment variable for authentication.
Both functions auto-register as tools on import.
"""

import logging
import os
from typing import Any

import httpx

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")

_NOTION_API = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


def _notion_headers() -> dict[str, str]:
    """Build Notion API headers with authentication.

    Returns:
        Dict of HTTP headers for Notion API requests.

    Raises:
        ValueError: If NOTION_API_KEY is not set.
    """
    token = os.environ.get("NOTION_API_KEY", "")
    if not token:
        raise ValueError("NOTION_API_KEY not set. Cannot access Notion without authentication.")

    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def search_notion(query: str, page_size: int = 10) -> dict[str, Any]:
    """Search Notion pages by title or content.

    Uses the Notion Search API to find pages matching the query.
    Requires NOTION_API_KEY environment variable.

    Args:
        query: Search query string.
        page_size: Maximum number of results (default 10).

    Returns:
        Dict with 'ok' and 'pages' list. Each page has 'id', 'title',
        'url', 'last_edited', and 'type'.
    """
    try:
        headers = _notion_headers()

        payload = {
            "query": query,
            "page_size": page_size,
            "sort": {
                "direction": "descending",
                "timestamp": "last_edited_time",
            },
        }

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{_NOTION_API}/search",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        pages = []
        for item in data.get("results", []):
            # Extract title from properties
            title = ""
            obj_type = item.get("object", "")
            if obj_type == "page":
                props = item.get("properties", {})
                title_prop = props.get("title", props.get("Name", {}))
                if isinstance(title_prop, dict):
                    title_items = title_prop.get("title", [])
                    if title_items:
                        title = title_items[0].get("plain_text", "")
            elif obj_type == "database":
                title_items = item.get("title", [])
                if title_items:
                    title = title_items[0].get("plain_text", "")

            pages.append({
                "id": item.get("id", ""),
                "title": title,
                "url": item.get("url", ""),
                "last_edited": item.get("last_edited_time", ""),
                "type": obj_type,
            })

        return {"ok": True, "pages": pages, "total": len(pages)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except httpx.HTTPStatusError as e:
        logger.error("Notion search failed (HTTP %s): %s", e.response.status_code, e)
        return {"ok": False, "error": f"HTTP {e.response.status_code}: Check your NOTION_API_KEY"}
    except Exception as e:
        logger.error("Notion search failed: %s", e)
        return {"ok": False, "error": str(e)}


def create_notion_page(title: str, content: str, parent_page_id: str = "") -> dict[str, Any]:
    """Create a new page in Notion.

    Creates a page with the given title and content as paragraph blocks.
    If parent_page_id is provided, creates as a child page; otherwise
    creates in the workspace root.

    Args:
        title: Page title.
        content: Page body text. Paragraphs are split by double newlines.
        parent_page_id: Optional parent page ID for nesting.

    Returns:
        Dict with 'ok', 'id' (page ID), and 'url' (page URL).
    """
    try:
        headers = _notion_headers()

        # Build content blocks from text (split by double newlines for paragraphs)
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        children = []
        for para in paragraphs[:100]:  # Notion API limit: 100 blocks per request
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": para[:2000]}}],
                },
            })

        # Build parent reference
        if parent_page_id:
            parent = {"type": "page_id", "page_id": parent_page_id}
        else:
            # Without a parent, we need a page_id — Notion requires a parent
            # Use workspace-level page (requires integration to have access)
            parent = {"type": "page_id", "page_id": parent_page_id} if parent_page_id else None

        payload: dict[str, Any] = {
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}],
                },
            },
            "children": children,
        }

        if parent:
            payload["parent"] = parent

        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{_NOTION_API}/pages",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        return {
            "ok": True,
            "id": data.get("id", ""),
            "url": data.get("url", ""),
            "title": title,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except httpx.HTTPStatusError as e:
        logger.error("Notion page creation failed (HTTP %s): %s", e.response.status_code, e)
        error_body = ""
        try:
            error_body = e.response.json().get("message", "")
        except Exception:
            pass
        return {
            "ok": False,
            "error": f"HTTP {e.response.status_code}: {error_body or 'Check NOTION_API_KEY and parent_page_id'}",
        }
    except Exception as e:
        logger.error("Notion page creation failed: %s", e)
        return {"ok": False, "error": str(e)}


# --- Auto-register tools on import ---

register_tool(
    name="search_notion",
    function=search_notion,
    description="Search Notion pages by title or content. Requires NOTION_API_KEY.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "page_size": {"type": "integer", "description": "Max results (default 10)", "default": 10},
        },
        "required": ["query"],
    },
)

register_tool(
    name="create_notion_page",
    function=create_notion_page,
    description="Create a new page in Notion with title and content. Requires NOTION_API_KEY.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Page title"},
            "content": {"type": "string", "description": "Page body text (use \\n\\n for paragraphs)"},
            "parent_page_id": {
                "type": "string",
                "description": "Optional parent page ID for nesting",
                "default": "",
            },
        },
        "required": ["title", "content"],
    },
)
