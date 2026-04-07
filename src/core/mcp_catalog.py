"""MCP Server Catalog — pre-configured MCP servers that can be enabled with one click.

Each entry defines the command, args, and environment needed to connect
to a popular MCP server. Users pick from the catalog in the dashboard
and the system connects automatically.
"""

import logging
from typing import Any

logger = logging.getLogger("pagal_os")

# ---------------------------------------------------------------------------
# Catalog of popular MCP servers
# ---------------------------------------------------------------------------

MCP_CATALOG: list[dict[str, Any]] = [
    {
        "id": "github",
        "name": "GitHub",
        "description": "Access repositories, issues, PRs, and code search.",
        "category": "Development",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env_keys": ["GITHUB_TOKEN"],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/github",
    },
    {
        "id": "filesystem",
        "name": "Filesystem",
        "description": "Read, write, and manage local files and directories.",
        "category": "Productivity",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/pagal-fs"],
        "env_keys": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
    },
    {
        "id": "brave-search",
        "name": "Brave Search",
        "description": "Web search via Brave Search API (privacy-focused).",
        "category": "Research",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env_keys": ["BRAVE_API_KEY"],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search",
    },
    {
        "id": "postgres",
        "name": "PostgreSQL",
        "description": "Query and manage PostgreSQL databases.",
        "category": "Data",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres"],
        "env_keys": ["POSTGRES_URL"],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/postgres",
    },
    {
        "id": "sqlite",
        "name": "SQLite",
        "description": "Query and manage SQLite databases.",
        "category": "Data",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite"],
        "env_keys": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
    },
    {
        "id": "slack",
        "name": "Slack",
        "description": "Send messages, read channels, and manage Slack workspace.",
        "category": "Communication",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env_keys": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/slack",
    },
    {
        "id": "google-drive",
        "name": "Google Drive",
        "description": "Read and search files in Google Drive.",
        "category": "Productivity",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gdrive"],
        "env_keys": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive",
    },
    {
        "id": "notion",
        "name": "Notion",
        "description": "Read and update Notion pages and databases.",
        "category": "Productivity",
        "command": "npx",
        "args": ["-y", "notion-mcp-server"],
        "env_keys": ["NOTION_API_KEY"],
        "docs_url": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "puppeteer",
        "name": "Puppeteer (Browser)",
        "description": "Control a headless browser — navigate, screenshot, interact.",
        "category": "Automation",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "env_keys": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer",
    },
    {
        "id": "memory",
        "name": "Memory (KG)",
        "description": "Persistent memory using a local knowledge graph.",
        "category": "AI",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "env_keys": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
    },
]


def list_catalog(category: str | None = None) -> list[dict[str, Any]]:
    """List available MCP servers from the catalog.

    Args:
        category: Optional category filter.

    Returns:
        List of catalog entries.
    """
    items = MCP_CATALOG
    if category:
        items = [s for s in items if s["category"].lower() == category.lower()]
    return items


def get_catalog_entry(server_id: str) -> dict[str, Any] | None:
    """Get a specific MCP server entry by ID."""
    for entry in MCP_CATALOG:
        if entry["id"] == server_id:
            return entry
    return None


def install_from_catalog(server_id: str, env_overrides: dict[str, str] | None = None) -> dict[str, Any]:
    """Connect to an MCP server from the catalog.

    Args:
        server_id: Catalog entry ID.
        env_overrides: Optional environment variable overrides.

    Returns:
        Dict with 'ok' and connection status.
    """
    entry = get_catalog_entry(server_id)
    if not entry:
        return {"ok": False, "error": f"MCP server '{server_id}' not found in catalog"}

    try:
        import os

        # Check required env vars
        missing = [k for k in entry["env_keys"] if not os.getenv(k) and not (env_overrides or {}).get(k)]
        if missing:
            return {
                "ok": False,
                "error": f"Missing environment variables: {', '.join(missing)}. Set them in .env file.",
            }

        from src.core.mcp import connect_mcp_server

        env = env_overrides or {}
        # Pass relevant env vars to the MCP server
        for key in entry["env_keys"]:
            val = os.getenv(key, "")
            if val and key not in env:
                env[key] = val

        ok = connect_mcp_server(
            name=entry["id"],
            command=entry["command"],
            args=entry["args"],
            env=env if env else None,
        )

        if ok:
            return {"ok": True, "message": f"Connected to {entry['name']}"}
        return {"ok": False, "error": f"Failed to connect to {entry['name']}"}

    except Exception as e:
        logger.error("Failed to install MCP server '%s': %s", server_id, e)
        return {"ok": False, "error": str(e)}


def get_catalog_categories() -> list[str]:
    """Get unique categories from the catalog."""
    return sorted(set(s["category"] for s in MCP_CATALOG))
