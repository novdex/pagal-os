"""GitHub Integration — search repos, fetch READMEs, list issues, create gists.

Provides tools for interacting with GitHub's public API (no auth needed for
public repos) and authenticated endpoints (gists require GITHUB_TOKEN).
All functions auto-register as tools on import.
"""

import logging
import os
from typing import Any

import httpx

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")

_GITHUB_API = "https://api.github.com"


def _github_headers() -> dict[str, str]:
    """Build GitHub API headers, including auth token if available.

    Returns:
        Dict of HTTP headers for GitHub API requests.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PAGAL-OS/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def search_github_repos(query: str, num_results: int = 5) -> dict[str, Any]:
    """Search GitHub repositories via the public search API.

    Args:
        query: Search query (e.g. 'machine learning python').
        num_results: Maximum number of results to return (default 5).

    Returns:
        Dict with 'ok' and 'repos' list. Each repo has 'name', 'full_name',
        'description', 'url', 'stars', and 'language'.
    """
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{_GITHUB_API}/search/repositories",
                params={"q": query, "per_page": num_results, "sort": "stars"},
                headers=_github_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        repos = []
        for item in data.get("items", [])[:num_results]:
            repos.append({
                "name": item.get("name", ""),
                "full_name": item.get("full_name", ""),
                "description": item.get("description", "") or "",
                "url": item.get("html_url", ""),
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language", "") or "",
            })

        return {"ok": True, "repos": repos, "total_count": data.get("total_count", 0)}
    except Exception as e:
        logger.error("GitHub repo search failed: %s", e)
        return {"ok": False, "error": str(e)}


def get_repo_readme(owner: str, repo: str) -> dict[str, Any]:
    """Fetch the README content of a GitHub repository.

    Uses the GitHub API to get the decoded README text. Works for
    public repos without authentication.

    Args:
        owner: Repository owner (e.g. 'openai').
        repo: Repository name (e.g. 'openai-python').

    Returns:
        Dict with 'ok', 'content' (README text), and 'name' (filename).
    """
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{_GITHUB_API}/repos/{owner}/{repo}/readme",
                headers={**_github_headers(), "Accept": "application/vnd.github.raw+json"},
            )
            resp.raise_for_status()

        return {
            "ok": True,
            "content": resp.text,
            "owner": owner,
            "repo": repo,
            "length": len(resp.text),
        }
    except httpx.HTTPStatusError as e:
        logger.error("Failed to fetch README for %s/%s: HTTP %s", owner, repo, e.response.status_code)
        return {"ok": False, "error": f"HTTP {e.response.status_code}: README not found or repo is private"}
    except Exception as e:
        logger.error("Failed to fetch README for %s/%s: %s", owner, repo, e)
        return {"ok": False, "error": str(e)}


def list_repo_issues(owner: str, repo: str, num_results: int = 10) -> dict[str, Any]:
    """List open issues for a GitHub repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        num_results: Maximum number of issues to return (default 10).

    Returns:
        Dict with 'ok' and 'issues' list. Each issue has 'number', 'title',
        'url', 'labels', 'created_at', and 'user'.
    """
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{_GITHUB_API}/repos/{owner}/{repo}/issues",
                params={"state": "open", "per_page": num_results},
                headers=_github_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        issues = []
        for item in data[:num_results]:
            # Skip pull requests (they also appear in issues endpoint)
            if "pull_request" in item:
                continue
            issues.append({
                "number": item.get("number", 0),
                "title": item.get("title", ""),
                "url": item.get("html_url", ""),
                "labels": [lbl.get("name", "") for lbl in item.get("labels", [])],
                "created_at": item.get("created_at", ""),
                "user": item.get("user", {}).get("login", ""),
            })

        return {"ok": True, "issues": issues, "owner": owner, "repo": repo}
    except Exception as e:
        logger.error("Failed to list issues for %s/%s: %s", owner, repo, e)
        return {"ok": False, "error": str(e)}


def create_github_gist(
    filename: str,
    content: str,
    description: str = "",
    public: bool = False,
) -> dict[str, Any]:
    """Create a GitHub Gist. Requires GITHUB_TOKEN environment variable.

    Args:
        filename: Name of the file in the gist (e.g. 'notes.md').
        content: The file content.
        description: Optional gist description.
        public: Whether the gist is public (default False).

    Returns:
        Dict with 'ok', 'url' (gist HTML URL), and 'id' (gist ID).
    """
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return {"ok": False, "error": "GITHUB_TOKEN not set. Cannot create gist without authentication."}

        payload = {
            "description": description,
            "public": public,
            "files": {
                filename: {"content": content},
            },
        }

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{_GITHUB_API}/gists",
                json=payload,
                headers=_github_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        return {
            "ok": True,
            "url": data.get("html_url", ""),
            "id": data.get("id", ""),
            "filename": filename,
        }
    except httpx.HTTPStatusError as e:
        logger.error("Failed to create gist (HTTP %s): %s", e.response.status_code, e)
        return {"ok": False, "error": f"HTTP {e.response.status_code}: Check your GITHUB_TOKEN permissions"}
    except Exception as e:
        logger.error("Failed to create gist: %s", e)
        return {"ok": False, "error": str(e)}


# --- Auto-register tools on import ---

register_tool(
    name="search_github_repos",
    function=search_github_repos,
    description="Search GitHub repositories. Returns name, description, stars, and language.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query for GitHub repos"},
            "num_results": {"type": "integer", "description": "Max results (default 5)", "default": 5},
        },
        "required": ["query"],
    },
)

register_tool(
    name="get_repo_readme",
    function=get_repo_readme,
    description="Fetch the README content of a GitHub repository.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner (e.g. 'openai')"},
            "repo": {"type": "string", "description": "Repository name (e.g. 'openai-python')"},
        },
        "required": ["owner", "repo"],
    },
)

register_tool(
    name="list_repo_issues",
    function=list_repo_issues,
    description="List open issues for a GitHub repository.",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "num_results": {"type": "integer", "description": "Max issues (default 10)", "default": 10},
        },
        "required": ["owner", "repo"],
    },
)

register_tool(
    name="create_github_gist",
    function=create_github_gist,
    description="Create a GitHub Gist. Requires GITHUB_TOKEN env var.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Filename for the gist (e.g. 'notes.md')"},
            "content": {"type": "string", "description": "File content"},
            "description": {"type": "string", "description": "Gist description", "default": ""},
            "public": {"type": "boolean", "description": "Whether gist is public", "default": False},
        },
        "required": ["filename", "content"],
    },
)
