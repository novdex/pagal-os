"""Web Crawling Engine — crawl and index entire websites.

Crawl4AI-style crawler that follows links, extracts text, respects robots.txt,
and can save results to files or the knowledge graph.
All functions auto-register as tools on import.
"""

import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")

# Rate limiting: minimum seconds between requests to the same domain
_RATE_LIMIT_SECONDS = 1.0
_last_request_time: dict[str, float] = {}

# User agent for crawler
_USER_AGENT = "PAGAL-OS-Crawler/1.0"


def _respect_rate_limit(domain: str) -> None:
    """Wait if needed to respect per-domain rate limiting.

    Ensures at least _RATE_LIMIT_SECONDS between requests to the same domain.

    Args:
        domain: The domain being crawled.
    """
    now = time.time()
    last = _last_request_time.get(domain, 0.0)
    elapsed = now - last
    if elapsed < _RATE_LIMIT_SECONDS:
        time.sleep(_RATE_LIMIT_SECONDS - elapsed)
    _last_request_time[domain] = time.time()


def _check_robots_txt(base_url: str, path: str = "/") -> bool:
    """Check if crawling the given path is allowed by robots.txt.

    Args:
        base_url: The base URL of the site (scheme + domain).
        path: The path to check.

    Returns:
        True if crawling is allowed, False if disallowed.
    """
    try:
        rp = RobotFileParser()
        robots_url = f"{base_url}/robots.txt"
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(_USER_AGENT, f"{base_url}{path}")
    except Exception as e:
        logger.debug("Could not read robots.txt for %s: %s", base_url, e)
        # If we can't read robots.txt, allow crawling (permissive default)
        return True


def _extract_text(html: str) -> tuple[str, str]:
    """Extract title and body text from HTML.

    Args:
        html: Raw HTML string.

    Returns:
        Tuple of (title, body_text).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style elements
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    body_text = soup.get_text(separator="\n", strip=True)
    # Clean up excessive whitespace
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    body_text = "\n".join(lines)

    return title, body_text


def _extract_links(html: str, base_url: str, same_domain: str) -> list[str]:
    """Extract same-domain links from HTML.

    Args:
        html: Raw HTML string.
        base_url: The URL of the current page (for resolving relative links).
        same_domain: Only return links matching this domain.

    Returns:
        List of absolute URLs on the same domain.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        # Resolve relative URLs
        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)

        # Filter: same domain, HTTP(S) only, no fragments/anchors
        if (
            parsed.netloc == same_domain
            and parsed.scheme in ("http", "https")
        ):
            # Remove fragment
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            # Remove trailing slash for consistency
            if clean_url.endswith("/") and len(parsed.path) > 1:
                clean_url = clean_url.rstrip("/")
            links.add(clean_url)

    return list(links)


def _is_crawl_url_safe(url: str) -> str | None:
    """Block crawling private/reserved IP addresses (SSRF protection).

    Returns an error message if blocked, None if safe.
    """
    import ipaddress
    import socket

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"Blocked URL scheme: {parsed.scheme}"
        hostname = parsed.hostname
        if not hostname:
            return "Invalid URL: no hostname"
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


def crawl_website(url: str, max_pages: int = 10, depth: int = 2) -> dict[str, Any]:
    """Crawl a website starting from a URL, following same-domain links.

    Extracts text from each page, respects robots.txt, and rate-limits
    requests to 1 per second.
    Blocks requests to private/reserved IP addresses (SSRF protection).

    Args:
        url: Starting URL to crawl.
        max_pages: Maximum number of pages to crawl (default 10).
        depth: Maximum link depth to follow (default 2).

    Returns:
        Dict with 'ok', 'pages' (list of page data), and 'total_pages'.
        Each page has 'url', 'title', 'text', and 'depth'.
    """
    try:
        # SSRF protection
        ssrf_error = _is_crawl_url_safe(url)
        if ssrf_error:
            logger.warning("Crawl blocked (SSRF): %s — %s", url, ssrf_error)
            return {"ok": False, "error": ssrf_error}

        parsed_start = urlparse(url)
        domain = parsed_start.netloc
        base_url = f"{parsed_start.scheme}://{domain}"

        # Check robots.txt for the starting URL
        if not _check_robots_txt(base_url, parsed_start.path or "/"):
            return {"ok": False, "error": f"robots.txt disallows crawling {url}"}

        visited: set[str] = set()
        pages: list[dict[str, Any]] = []
        # Queue: (url, depth_level)
        queue: list[tuple[str, int]] = [(url, 0)]

        with httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            while queue and len(pages) < max_pages:
                current_url, current_depth = queue.pop(0)

                # Normalize URL
                parsed_current = urlparse(current_url)
                normalized = f"{parsed_current.scheme}://{parsed_current.netloc}{parsed_current.path}"
                if normalized in visited:
                    continue
                visited.add(normalized)

                # Check robots.txt
                if not _check_robots_txt(base_url, parsed_current.path or "/"):
                    logger.debug("Skipping %s (disallowed by robots.txt)", current_url)
                    continue

                # Rate limit
                _respect_rate_limit(domain)

                try:
                    resp = client.get(current_url)
                    resp.raise_for_status()

                    # Only process HTML pages
                    content_type = resp.headers.get("content-type", "")
                    if "text/html" not in content_type:
                        continue

                    title, text = _extract_text(resp.text)
                    pages.append({
                        "url": current_url,
                        "title": title,
                        "text": text[:10000],  # Cap text length per page
                        "depth": current_depth,
                    })

                    # Extract and queue links if within depth limit
                    if current_depth < depth:
                        links = _extract_links(resp.text, current_url, domain)
                        for link in links:
                            if link not in visited:
                                queue.append((link, current_depth + 1))

                except httpx.HTTPStatusError as e:
                    logger.debug("HTTP %s for %s", e.response.status_code, current_url)
                except Exception as e:
                    logger.debug("Failed to crawl %s: %s", current_url, e)

        return {
            "ok": True,
            "pages": pages,
            "total_pages": len(pages),
            "domain": domain,
        }
    except Exception as e:
        logger.error("Crawl failed for %s: %s", url, e)
        return {"ok": False, "error": str(e)}


def crawl_and_save(url: str, output_dir: str, max_pages: int = 10, depth: int = 2) -> dict[str, Any]:
    """Crawl a website and save each page as a text file.

    Args:
        url: Starting URL to crawl.
        output_dir: Directory to save text files.
        max_pages: Maximum number of pages to crawl (default 10).
        depth: Maximum link depth to follow (default 2).

    Returns:
        Dict with 'ok', 'files_saved' (list of file paths), and 'total_pages'.
    """
    try:
        result = crawl_website(url, max_pages=max_pages, depth=depth)
        if not result["ok"]:
            return result

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        files_saved: list[str] = []
        for i, page in enumerate(result["pages"]):
            # Create a safe filename from the URL
            parsed = urlparse(page["url"])
            safe_name = parsed.path.strip("/").replace("/", "_") or "index"
            safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in safe_name)
            filename = f"{i:03d}_{safe_name}.txt"
            filepath = out_path / filename

            content = f"URL: {page['url']}\nTitle: {page['title']}\n{'=' * 60}\n\n{page['text']}"
            filepath.write_text(content, encoding="utf-8")
            files_saved.append(str(filepath))

        return {
            "ok": True,
            "files_saved": files_saved,
            "total_pages": len(files_saved),
            "output_dir": str(out_path),
        }
    except Exception as e:
        logger.error("Crawl-and-save failed for %s: %s", url, e)
        return {"ok": False, "error": str(e)}


def crawl_to_knowledge(url: str, agent_name: str, max_pages: int = 10, depth: int = 2) -> dict[str, Any]:
    """Crawl a website and add all content to the knowledge graph.

    Each crawled page becomes a knowledge entry linked to the specified agent.

    Args:
        url: Starting URL to crawl.
        agent_name: Agent to associate the knowledge with.
        max_pages: Maximum number of pages to crawl (default 10).
        depth: Maximum link depth to follow (default 2).

    Returns:
        Dict with 'ok', 'pages_added' count, and 'agent_name'.
    """
    try:
        result = crawl_website(url, max_pages=max_pages, depth=depth)
        if not result["ok"]:
            return result

        from src.core.knowledge import add_knowledge

        pages_added = 0
        for page in result["pages"]:
            try:
                topic = page["title"] or urlparse(page["url"]).path
                content = page["text"][:500]  # Keep first 500 chars for knowledge
                add_knowledge(
                    agent_name=agent_name,
                    topic=topic,
                    content=content,
                    source=f"crawl:{page['url']}",
                )
                pages_added += 1
            except Exception as e:
                logger.debug("Failed to add knowledge for %s: %s", page["url"], e)

        return {
            "ok": True,
            "pages_added": pages_added,
            "total_crawled": result["total_pages"],
            "agent_name": agent_name,
            "domain": result.get("domain", ""),
        }
    except Exception as e:
        logger.error("Crawl-to-knowledge failed for %s: %s", url, e)
        return {"ok": False, "error": str(e)}


# --- Auto-register tools on import ---

register_tool(
    name="crawl_website",
    function=crawl_website,
    description="Crawl a website starting from a URL. Follows same-domain links, extracts text. Respects robots.txt.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Starting URL to crawl"},
            "max_pages": {"type": "integer", "description": "Max pages to crawl (default 10)", "default": 10},
            "depth": {"type": "integer", "description": "Max link depth (default 2)", "default": 2},
        },
        "required": ["url"],
    },
)

register_tool(
    name="crawl_and_save",
    function=crawl_and_save,
    description="Crawl a website and save each page as a text file in the given directory.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Starting URL to crawl"},
            "output_dir": {"type": "string", "description": "Directory to save text files"},
            "max_pages": {"type": "integer", "description": "Max pages (default 10)", "default": 10},
            "depth": {"type": "integer", "description": "Max link depth (default 2)", "default": 2},
        },
        "required": ["url", "output_dir"],
    },
)

register_tool(
    name="crawl_to_knowledge",
    function=crawl_to_knowledge,
    description="Crawl a website and add all content to an agent's knowledge graph.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Starting URL to crawl"},
            "agent_name": {"type": "string", "description": "Agent to associate knowledge with"},
            "max_pages": {"type": "integer", "description": "Max pages (default 10)", "default": 10},
            "depth": {"type": "integer", "description": "Max link depth (default 2)", "default": 2},
        },
        "required": ["url", "agent_name"],
    },
)
