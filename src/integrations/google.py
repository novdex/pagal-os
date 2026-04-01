"""Google Integrations — search, docs, and sheets tools for PAGAL OS agents.

Provides web search via SerpAPI (with DuckDuckGo fallback), Google Docs
reading for public documents, and CSV data formatting for spreadsheet import.
All functions auto-register as tools on import.
"""

import csv
import io
import logging
import os
from typing import Any

import httpx

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


def search_google(query: str, num_results: int = 5) -> dict[str, Any]:
    """Search Google via SerpAPI, falling back to DuckDuckGo if no API key.

    Args:
        query: The search query string.
        num_results: Maximum number of results to return (default 5).

    Returns:
        Dict with 'ok', 'source' (serpapi or duckduckgo), and 'results' list.
        Each result has 'title', 'url', and 'snippet'.
    """
    try:
        serpapi_key = os.environ.get("SERPAPI_KEY", "")
        if serpapi_key:
            return _search_serpapi(query, num_results, serpapi_key)
        return _search_duckduckgo(query, num_results)
    except Exception as e:
        logger.error("Google search failed: %s", e)
        return {"ok": False, "error": str(e)}


def _search_serpapi(query: str, num_results: int, api_key: str) -> dict[str, Any]:
    """Search via SerpAPI.

    Args:
        query: Search query.
        num_results: Max results.
        api_key: SerpAPI API key.

    Returns:
        Dict with search results.
    """
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                "https://serpapi.com/search",
                params={
                    "q": query,
                    "api_key": api_key,
                    "num": num_results,
                    "engine": "google",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("organic_results", [])[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })

        return {"ok": True, "source": "serpapi", "results": results}
    except Exception as e:
        logger.warning("SerpAPI failed, falling back to DuckDuckGo: %s", e)
        return _search_duckduckgo(query, num_results)


def _search_duckduckgo(query: str, num_results: int) -> dict[str, Any]:
    """Search via DuckDuckGo as fallback.

    Args:
        query: Search query.
        num_results: Max results.

    Returns:
        Dict with search results.
    """
    try:
        from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })

        return {"ok": True, "source": "duckduckgo", "results": results}
    except Exception as e:
        logger.error("DuckDuckGo search failed: %s", e)
        return {"ok": False, "error": f"All search backends failed: {e}"}


def read_google_doc(doc_url: str) -> dict[str, Any]:
    """Fetch content from a public Google Doc via its export URL.

    Converts the Google Doc URL to an export-as-text URL and fetches
    the plain-text content. Only works with publicly shared documents.

    Args:
        doc_url: The Google Doc URL (e.g. https://docs.google.com/document/d/DOC_ID/...).

    Returns:
        Dict with 'ok', 'content' (the document text), and 'url'.
    """
    try:
        # Extract document ID from various URL formats
        doc_id = ""
        if "/d/" in doc_url:
            doc_id = doc_url.split("/d/")[1].split("/")[0]
        elif "id=" in doc_url:
            doc_id = doc_url.split("id=")[1].split("&")[0]

        if not doc_id:
            return {"ok": False, "error": "Could not extract document ID from URL"}

        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"

        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(export_url)
            resp.raise_for_status()

        return {
            "ok": True,
            "content": resp.text,
            "url": doc_url,
            "doc_id": doc_id,
            "length": len(resp.text),
        }
    except httpx.HTTPStatusError as e:
        logger.error("Failed to read Google Doc (HTTP %s): %s", e.response.status_code, e)
        return {"ok": False, "error": f"HTTP {e.response.status_code}: Document may not be publicly accessible"}
    except Exception as e:
        logger.error("Failed to read Google Doc: %s", e)
        return {"ok": False, "error": str(e)}


def create_google_sheet_data(data: list[list]) -> dict[str, Any]:
    """Format tabular data as CSV for Google Sheets import.

    Takes a list of rows (each row is a list of cell values) and
    produces a CSV string ready for pasting or importing into a spreadsheet.

    Args:
        data: List of rows, where each row is a list of cell values.
              First row is treated as headers.

    Returns:
        Dict with 'ok', 'csv' (the formatted CSV string), and 'rows'/'cols' counts.
    """
    try:
        if not data:
            return {"ok": False, "error": "No data provided"}

        output = io.StringIO()
        writer = csv.writer(output)
        for row in data:
            writer.writerow(row)

        csv_content = output.getvalue()

        return {
            "ok": True,
            "csv": csv_content,
            "rows": len(data),
            "cols": len(data[0]) if data else 0,
        }
    except Exception as e:
        logger.error("Failed to create sheet data: %s", e)
        return {"ok": False, "error": str(e)}


# --- Auto-register tools on import ---

register_tool(
    name="search_google",
    function=search_google,
    description="Search Google via SerpAPI (or DuckDuckGo fallback). Returns titles, URLs, and snippets.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "num_results": {"type": "integer", "description": "Max results (default 5)", "default": 5},
        },
        "required": ["query"],
    },
)

register_tool(
    name="read_google_doc",
    function=read_google_doc,
    description="Fetch content from a public Google Doc. Provide the full Google Doc URL.",
    parameters={
        "type": "object",
        "properties": {
            "doc_url": {"type": "string", "description": "Google Doc URL"},
        },
        "required": ["doc_url"],
    },
)

register_tool(
    name="create_google_sheet_data",
    function=create_google_sheet_data,
    description="Format tabular data as CSV for Google Sheets import. Pass a list of rows.",
    parameters={
        "type": "object",
        "properties": {
            "data": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "string"}},
                "description": "List of rows, each row is a list of cell values",
            },
        },
        "required": ["data"],
    },
)
