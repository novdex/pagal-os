"""PAGAL OS Browser Tool — fetch and extract text from web pages."""

import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


def _is_url_safe(url: str) -> str | None:
    """Check if a URL is safe to fetch (not targeting private/reserved IPs).

    Returns an error message if blocked, None if safe.
    """
    try:
        parsed = urlparse(url)

        # Only allow http and https
        if parsed.scheme not in ("http", "https"):
            return f"Blocked URL scheme: {parsed.scheme} (only http/https allowed)"

        hostname = parsed.hostname
        if not hostname:
            return "Invalid URL: no hostname"

        # Resolve hostname to IP and check for private/reserved ranges
        try:
            addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
            for family, _, _, _, sockaddr in addr_info:
                ip = ipaddress.ip_address(sockaddr[0])
                if ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local:
                    return f"Blocked: URL resolves to private/reserved IP ({ip})"
        except socket.gaierror:
            return f"Cannot resolve hostname: {hostname}"

        return None
    except Exception as e:
        return f"URL validation error: {e}"


def browse_url(url: str) -> dict[str, Any]:
    """Fetch a URL and extract readable text content.

    Uses httpx to fetch the page and BeautifulSoup to extract text,
    stripping scripts, styles, and navigation elements.
    Blocks requests to private/reserved IP addresses (SSRF protection).

    Args:
        url: The URL to fetch and parse.

    Returns:
        Dict with 'ok', 'result' (extracted text), 'title', and 'url' keys.
    """
    try:
        # SSRF protection: block private/reserved IPs
        ssrf_error = _is_url_safe(url)
        if ssrf_error:
            logger.warning("Browse blocked (SSRF): %s — %s", url, ssrf_error)
            return {"ok": False, "error": ssrf_error}

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PagalOS/1.0; +https://pagal-os.local)",
        }

        with httpx.Client(timeout=15, follow_redirects=True, max_redirects=5) as client:
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
