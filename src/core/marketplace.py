"""Agent Marketplace — discover, install, and share agent configurations.

Community agents stored in a local JSON registry (MVP) that can later
connect to a remote GitHub-backed registry. Includes rating/review system
and install tracking.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config

logger = logging.getLogger("pagal_os")

# Paths
_PAGAL_DIR = Path.home() / ".pagal-os"
MARKETPLACE_FILE = _PAGAL_DIR / "marketplace.json"
PUBLISHED_DIR = _PAGAL_DIR / "published"

# Default registry entries shipped with PAGAL OS
_DEFAULT_REGISTRY: list[dict[str, Any]] = [
    # --- Productivity (5) ---
    {
        "id": "news_monitor",
        "name": "News Monitor",
        "description": "Monitors news on any topic and sends alerts",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "browse_url"],
        "yaml_url": "local",
        "featured": True,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Productivity",
    },
    {
        "id": "email_drafter",
        "name": "Email Drafter",
        "description": "Drafts professional emails from brief descriptions",
        "author": "pagal-os",
        "downloads": 0,
        "tools": [],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Productivity",
    },
    {
        "id": "meeting_notes",
        "name": "Meeting Notes",
        "description": "Summarizes meeting transcripts into action items",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["read_file", "write_file"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Productivity",
    },
    {
        "id": "daily_briefing",
        "name": "Daily Briefing",
        "description": "Creates a daily summary of news, weather, and tasks",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "browse_url"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Productivity",
    },
    {
        "id": "calendar_assistant",
        "name": "Calendar Assistant",
        "description": "Manages your schedule, sets reminders, and finds meeting slots",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Productivity",
    },
    # --- Research (5) ---
    {
        "id": "data_analyst",
        "name": "Data Analyst",
        "description": "Analyzes CSV/JSON data and creates reports",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["read_file", "write_file", "run_shell"],
        "yaml_url": "local",
        "featured": True,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Research",
    },
    {
        "id": "competitor_tracker",
        "name": "Competitor Tracker",
        "description": "Monitors competitor websites and reports changes",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "browse_url"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Research",
    },
    {
        "id": "tutor",
        "name": "AI Tutor",
        "description": "Explains any topic in simple terms with examples",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web"],
        "yaml_url": "local",
        "featured": True,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Research",
    },
    {
        "id": "arxiv_reader",
        "name": "ArXiv Paper Reader",
        "description": "Reads and summarizes academic papers from ArXiv into plain English",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "browse_url", "read_file"],
        "yaml_url": "local",
        "featured": True,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Research",
    },
    {
        "id": "market_researcher",
        "name": "Market Researcher",
        "description": "Researches markets, trends, and industries then writes detailed reports",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "browse_url", "write_file"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Research",
    },
    # --- Development (5) ---
    {
        "id": "code_reviewer",
        "name": "Code Reviewer",
        "description": "Reviews code changes for bugs and best practices",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["read_file", "run_shell"],
        "yaml_url": "local",
        "featured": True,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Development",
    },
    {
        "id": "bug_hunter",
        "name": "Bug Hunter",
        "description": "Scans code for common bugs and security issues",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["read_file", "run_shell"],
        "yaml_url": "local",
        "featured": True,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Development",
    },
    {
        "id": "test_writer",
        "name": "Test Writer",
        "description": "Generates unit and integration tests for your codebase",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["read_file", "write_file", "run_shell"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Development",
    },
    {
        "id": "api_documenter",
        "name": "API Documenter",
        "description": "Reads your API code and generates OpenAPI docs automatically",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["read_file", "write_file"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Development",
    },
    {
        "id": "dependency_auditor",
        "name": "Dependency Auditor",
        "description": "Checks project dependencies for vulnerabilities and outdated packages",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["read_file", "run_shell"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Development",
    },
    # --- Social Media (5) ---
    {
        "id": "social_media",
        "name": "Social Media Manager",
        "description": "Creates social media posts and content calendars",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Social Media",
    },
    {
        "id": "hashtag_optimizer",
        "name": "Hashtag Optimizer",
        "description": "Analyzes trending hashtags and suggests the best ones for reach",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Social Media",
    },
    {
        "id": "content_scheduler",
        "name": "Content Scheduler",
        "description": "Plans a week of social media posts with optimal posting times",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "write_file"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Social Media",
    },
    {
        "id": "engagement_analyzer",
        "name": "Engagement Analyzer",
        "description": "Analyzes social media engagement metrics and suggests improvements",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "browse_url"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Social Media",
    },
    {
        "id": "thread_writer",
        "name": "Thread Writer",
        "description": "Turns any topic into a viral Twitter/X thread with hooks and CTAs",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Social Media",
    },
    # --- Finance (5) ---
    {
        "id": "expense_tracker",
        "name": "Expense Tracker",
        "description": "Categorizes expenses from receipts and bank statements",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["read_file", "write_file"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Finance",
    },
    {
        "id": "invoice_generator",
        "name": "Invoice Generator",
        "description": "Creates professional invoices from project details and rates",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["write_file"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Finance",
    },
    {
        "id": "stock_watcher",
        "name": "Stock Watcher",
        "description": "Monitors stock prices and sends alerts on significant changes",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "browse_url"],
        "yaml_url": "local",
        "featured": True,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Finance",
    },
    {
        "id": "budget_planner",
        "name": "Budget Planner",
        "description": "Creates monthly budgets and tracks spending against goals",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["read_file", "write_file"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Finance",
    },
    {
        "id": "crypto_analyst",
        "name": "Crypto Analyst",
        "description": "Tracks cryptocurrency markets and provides daily sentiment analysis",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "browse_url"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Finance",
    },
    # --- Creative (5) ---
    {
        "id": "blog_writer",
        "name": "Blog Writer",
        "description": "Writes SEO-optimized blog posts on any topic with research",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "write_file"],
        "yaml_url": "local",
        "featured": True,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Creative",
    },
    {
        "id": "story_generator",
        "name": "Story Generator",
        "description": "Creates short stories, plot outlines, and character profiles",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["write_file"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Creative",
    },
    {
        "id": "brainstormer",
        "name": "Brainstormer",
        "description": "Generates creative ideas using lateral thinking and mind-mapping",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Creative",
    },
    {
        "id": "prompt_engineer",
        "name": "Prompt Engineer",
        "description": "Crafts and optimizes prompts for any AI model or task",
        "author": "pagal-os",
        "downloads": 0,
        "tools": [],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Creative",
    },
    {
        "id": "newsletter_writer",
        "name": "Newsletter Writer",
        "description": "Curates and writes weekly newsletters from trending topics",
        "author": "pagal-os",
        "downloads": 0,
        "tools": ["search_web", "browse_url", "write_file"],
        "yaml_url": "local",
        "featured": False,
        "rating": 0.0,
        "reviews": [],
        "installs": 0,
        "category": "Creative",
    },
]


def _ensure_registry() -> None:
    """Create the marketplace registry file with defaults if it doesn't exist.

    If the registry exists but has fewer entries than the default, merge new
    entries in (preserves user reviews/ratings on existing entries).
    """
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)

        if not MARKETPLACE_FILE.exists():
            MARKETPLACE_FILE.write_text(
                json.dumps(_DEFAULT_REGISTRY, indent=2),
                encoding="utf-8",
            )
            logger.info("Created default marketplace registry at %s", MARKETPLACE_FILE)
        else:
            # Merge any new default entries into existing registry
            try:
                existing = json.loads(MARKETPLACE_FILE.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    existing_ids = {e.get("id") for e in existing}
                    added = 0
                    for default_entry in _DEFAULT_REGISTRY:
                        if default_entry["id"] not in existing_ids:
                            existing.append(default_entry)
                            added += 1
                        else:
                            # Backfill category if missing on existing entries
                            for e in existing:
                                if e["id"] == default_entry["id"] and "category" not in e:
                                    e["category"] = default_entry.get("category", "General")
                    if added > 0:
                        MARKETPLACE_FILE.write_text(
                            json.dumps(existing, indent=2), encoding="utf-8",
                        )
                        logger.info("Added %d new entries to marketplace registry", added)
            except Exception as merge_err:
                logger.debug("Marketplace merge skipped: %s", merge_err)
    except Exception as e:
        logger.error("Failed to initialise marketplace registry: %s", e)


def _load_registry() -> list[dict[str, Any]]:
    """Load the marketplace registry from disk.

    Returns:
        List of agent entry dicts.
    """
    _ensure_registry()
    try:
        data = json.loads(MARKETPLACE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error("Failed to load marketplace registry: %s", e)
        return []


def _save_registry(registry: list[dict[str, Any]]) -> None:
    """Persist the marketplace registry to disk.

    Args:
        registry: Full list of agent entry dicts.
    """
    try:
        MARKETPLACE_FILE.write_text(
            json.dumps(registry, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error("Failed to save marketplace registry: %s", e)


def search_marketplace(query: str) -> list[dict[str, Any]]:
    """Search the curated registry for agents matching *query*.

    Performs case-insensitive substring matching against name, description,
    and tools.

    Args:
        query: Search string.

    Returns:
        List of matching agent dicts with keys: id, name, description,
        author, downloads, tools.
    """
    try:
        registry = _load_registry()
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        for entry in registry:
            searchable = " ".join([
                entry.get("name", ""),
                entry.get("description", ""),
                " ".join(entry.get("tools", [])),
                entry.get("author", ""),
                entry.get("id", ""),
            ]).lower()

            if query_lower in searchable:
                results.append({
                    "id": entry["id"],
                    "name": entry["name"],
                    "description": entry["description"],
                    "author": entry.get("author", "unknown"),
                    "downloads": entry.get("downloads", 0),
                    "tools": entry.get("tools", []),
                })

        return results
    except Exception as e:
        logger.error("Marketplace search failed: %s", e)
        return []


def install_agent(agent_id: str) -> bool:
    """Install an agent from the marketplace into ~/.pagal-os/agents/.

    For 'local' agents the YAML is generated from the registry metadata.
    For remote agents (future) the YAML would be downloaded from yaml_url.

    Args:
        agent_id: The unique marketplace ID of the agent.

    Returns:
        True if installed successfully, False otherwise.
    """
    try:
        registry = _load_registry()
        entry: dict[str, Any] | None = None

        for item in registry:
            if item["id"] == agent_id:
                entry = item
                break

        if entry is None:
            logger.warning("Agent '%s' not found in marketplace", agent_id)
            return False

        config = get_config()
        agent_path = config.agents_dir / f"{agent_id}.yaml"

        if entry.get("yaml_url") == "local":
            # Generate YAML from metadata
            agent_data = {
                "name": agent_id,
                "description": entry["description"],
                "model": config.default_model,
                "tools": entry.get("tools", []),
                "personality": (
                    f"You are {entry['name']}. {entry['description']}. "
                    "Be thorough, accurate, and helpful."
                ),
                "memory": True,
                "schedule": None,
            }
            with open(agent_path, "w", encoding="utf-8") as f:
                yaml.dump(agent_data, f, default_flow_style=False, sort_keys=False)
        else:
            # Future: download from entry["yaml_url"] using httpx
            logger.info(
                "Remote install not yet implemented for '%s'", agent_id,
            )
            return False

        # Increment download and install counters
        for item in registry:
            if item["id"] == agent_id:
                item["downloads"] = item.get("downloads", 0) + 1
                item["installs"] = item.get("installs", 0) + 1
                break
        _save_registry(registry)

        logger.info("Installed marketplace agent '%s' to %s", agent_id, agent_path)
        return True

    except Exception as e:
        logger.error("Failed to install agent '%s': %s", agent_id, e)
        return False


def publish_agent(agent_name: str) -> dict[str, Any]:
    """Package a local agent into a shareable format.

    Copies the agent YAML to ~/.pagal-os/published/ and adds it to the
    marketplace registry.

    Args:
        agent_name: Name of the local agent to publish.

    Returns:
        Dict with 'ok' bool and 'path' or 'error'.
    """
    try:
        config = get_config()
        source = config.agents_dir / f"{agent_name}.yaml"

        if not source.exists():
            return {"ok": False, "error": f"Agent '{agent_name}' not found"}

        PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
        dest = PUBLISHED_DIR / f"{agent_name}.yaml"

        # Copy YAML
        dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

        # Read agent metadata
        with open(source, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Add to registry if not already present
        registry = _load_registry()
        existing_ids = {e["id"] for e in registry}

        if agent_name not in existing_ids:
            registry.append({
                "id": agent_name,
                "name": data.get("name", agent_name),
                "description": data.get("description", ""),
                "author": "local",
                "downloads": 0,
                "tools": data.get("tools", []),
                "yaml_url": "local",
                "featured": False,
            })
            _save_registry(registry)

        logger.info("Published agent '%s' to %s", agent_name, dest)
        return {"ok": True, "path": str(dest)}

    except Exception as e:
        logger.error("Failed to publish agent '%s': %s", agent_name, e)
        return {"ok": False, "error": str(e)}


def list_marketplace() -> list[dict[str, Any]]:
    """Return all agents in the marketplace registry.

    Returns:
        Full list of agent entry dicts.
    """
    try:
        return _load_registry()
    except Exception as e:
        logger.error("Failed to list marketplace: %s", e)
        return []


def get_featured() -> list[dict[str, Any]]:
    """Return featured / top agents from the marketplace.

    Returns:
        List of agent dicts where featured is True, sorted by downloads
        descending.
    """
    try:
        registry = _load_registry()
        featured = [e for e in registry if e.get("featured", False)]
        featured.sort(key=lambda x: x.get("downloads", 0), reverse=True)
        return featured
    except Exception as e:
        logger.error("Failed to get featured agents: %s", e)
        return []


# --- Rating & Review System ---


def rate_agent(agent_id: str, rating: int, review: str = "") -> bool:
    """Rate an agent 1-5 stars with an optional text review.

    Appends the review to the agent's reviews list and recalculates
    the average rating.

    Args:
        agent_id: Marketplace agent ID.
        rating: Star rating from 1 to 5.
        review: Optional review text.

    Returns:
        True if the rating was saved, False otherwise.
    """
    try:
        if not 1 <= rating <= 5:
            logger.warning("Invalid rating %d for agent '%s' (must be 1-5)", rating, agent_id)
            return False

        registry = _load_registry()

        for entry in registry:
            if entry["id"] == agent_id:
                # Ensure reviews list exists
                if "reviews" not in entry or not isinstance(entry["reviews"], list):
                    entry["reviews"] = []

                entry["reviews"].append({
                    "rating": rating,
                    "review": review,
                    "date": time.strftime("%Y-%m-%d %H:%M:%S"),
                })

                # Recalculate average rating
                all_ratings = [r["rating"] for r in entry["reviews"]]
                entry["rating"] = round(sum(all_ratings) / len(all_ratings), 1)

                _save_registry(registry)
                logger.info("Agent '%s' rated %d stars", agent_id, rating)
                return True

        logger.warning("Agent '%s' not found in marketplace", agent_id)
        return False

    except Exception as e:
        logger.error("Failed to rate agent '%s': %s", agent_id, e)
        return False


def get_reviews(agent_id: str) -> list[dict[str, Any]]:
    """Get all reviews for an agent.

    Args:
        agent_id: Marketplace agent ID.

    Returns:
        List of review dicts, each with "rating", "review", and "date".
    """
    try:
        registry = _load_registry()

        for entry in registry:
            if entry["id"] == agent_id:
                return entry.get("reviews", [])

        logger.warning("Agent '%s' not found for reviews", agent_id)
        return []

    except Exception as e:
        logger.error("Failed to get reviews for '%s': %s", agent_id, e)
        return []


def get_top_rated(limit: int = 10) -> list[dict[str, Any]]:
    """Get agents sorted by average rating (highest first).

    Only includes agents that have at least one review.

    Args:
        limit: Maximum number of agents to return.

    Returns:
        List of agent dicts sorted by rating descending.
    """
    try:
        registry = _load_registry()
        rated = [
            e for e in registry
            if e.get("rating", 0) > 0 and len(e.get("reviews", [])) > 0
        ]
        rated.sort(key=lambda x: x.get("rating", 0), reverse=True)
        return rated[:limit]

    except Exception as e:
        logger.error("Failed to get top rated agents: %s", e)
        return []


def increment_installs(agent_id: str) -> None:
    """Increment the install counter for an agent.

    Called when an agent is installed from the marketplace.

    Args:
        agent_id: Marketplace agent ID.
    """
    try:
        registry = _load_registry()

        for entry in registry:
            if entry["id"] == agent_id:
                entry["installs"] = entry.get("installs", 0) + 1
                _save_registry(registry)
                logger.debug("Incremented installs for '%s'", agent_id)
                return

        logger.warning("Agent '%s' not found for install increment", agent_id)

    except Exception as e:
        logger.error("Failed to increment installs for '%s': %s", agent_id, e)
