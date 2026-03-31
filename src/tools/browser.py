"""PAGAL OS Browser Tool — fetch and extract text from web pages."""

import logging
from typing import Any

import httpx

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


def browse_url(url: str) -> dict[str, Any]:
    """Fetch a URL and extract readable text content.

    Uses httpx to fetch the page and BeautifulSoup to extract text,
    stripping scripts, styles, and navigation elements.

    Args:
        url: The URL to fetch and parse.

    Returns:
        Dict with 'ok', 'result' (extracted text), 'title', and 'url' keys.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PagalOS/1.0; +https://pagal-os.local)",
        }

        with httpx.Client(timeout=15, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return {
                "ok": True,
                "result": response.text[:5000],
                "title": "",
                "url": str(response.url),
            }

        # Parse HTML with BeautifulSoup
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return {"ok": False, "error": "beautifulsoup4 package not installed"}

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove scripts, styles, nav elements
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        # Extract title
        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        # Extract text
        text = soup.get_text(separator="\n", strip=True)

        # Limit output to ~5000 chars
        if len(text) > 5000:
            text = text[:5000] + "\n... (truncated)"

        logger.info("Browsed %s: %d chars extracted", url, len(text))
        return {
            "ok": True,
            "result": text,
            "title": title,
            "url": str(response.url),
        }

    except httpx.TimeoutException:
        logger.warning("Browse timed out for %s", url)
        return {"ok": False, "error": f"Timeout fetching {url}"}
    except httpx.HTTPStatusError as e:
        logger.error("Browse HTTP error for %s: %s", url, e)
        return {"ok": False, "error": f"HTTP {e.response.status_code} for {url}"}
    except Exception as e:
        logger.error("Browse failed for %s: %s", url, e)
        return {"ok": False, "error": f"Browse failed: {e}"}


# Auto-register on import
register_tool(
    name="browse_url",
    function=browse_url,
    description="Fetch a web page and extract its readable text content.",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch and extract text from",
            },
        },
        "required": ["url"],
    },
)
