"""Multi-Model Router -- auto-select optimal model per task.

Routes simple tasks to free models and complex tasks to paid models,
minimizing cost while maintaining quality.
"""

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Model tiers: complexity -> model identifier
MODEL_TIERS: dict[str, str] = {
    "simple": "nvidia/nemotron-3-super-120b-a12b:free",  # free for easy stuff
    "medium": "nvidia/nemotron-3-super-120b-a12b:free",  # still free for medium
    "complex": "xiaomi/mimo-v2-pro",  # paid only for complex
}

# Keywords that suggest higher complexity
_COMPLEX_KEYWORDS: set[str] = {
    "analyze", "research", "compare", "investigate", "evaluate", "synthesize",
    "multi-step", "comprehensive", "detailed", "in-depth", "strategy",
    "architecture", "design", "debug", "optimize", "refactor", "plan",
}

_TOOL_KEYWORDS: set[str] = {
    "search", "browse", "read", "write", "file", "shell", "execute",
    "download", "upload", "send", "fetch", "scrape", "crawl",
}

# In-memory routing stats
_routing_stats: dict[str, int] = {"simple": 0, "medium": 0, "complex": 0}


def classify_complexity(task: str) -> str:
    """Classify a task's complexity based on length and content analysis.

    Rules:
    - Simple: < 20 words, single question, no tool keywords
    - Medium: 20-100 words, may need 1-2 tools
    - Complex: > 100 words, multi-step, research, analysis

    Args:
        task: The task description string.

    Returns:
        One of 'simple', 'medium', or 'complex'.
    """
    try:
        words = task.split()
        word_count = len(words)
        task_lower = task.lower()

        # Check for complex keywords
        complex_hits = sum(1 for kw in _COMPLEX_KEYWORDS if kw in task_lower)
        tool_hits = sum(1 for kw in _TOOL_KEYWORDS if kw in task_lower)

        # Count sentences (rough)
        sentences = len(re.split(r'[.!?]+', task.strip()))

        # Complex: long text, multiple complex keywords, or multi-step instructions
        if word_count > 100 or complex_hits >= 3 or (sentences > 4 and complex_hits >= 1):
            return "complex"

        # Medium: moderate length or needs tools
        if word_count >= 20 or tool_hits >= 2 or complex_hits >= 1:
            return "medium"

        # Simple: short and straightforward
        return "simple"
    except Exception as e:
        logger.debug("Complexity classification failed: %s", e)
        return "medium"  # default to medium on error


def select_model(task: str, agent_config: Any = None) -> str:
    """Select the best model for a given task.

    If the agent config specifies a model other than 'auto', returns
    that model directly. Otherwise, classifies complexity and picks
    from MODEL_TIERS.

    Args:
        task: The task description string.
        agent_config: Optional agent configuration object with a 'model' attribute.

    Returns:
        Model identifier string.
    """
    try:
        # If agent has a specific model (not 'auto'), use it
        if agent_config is not None:
            model = getattr(agent_config, "model", "auto")
            if model and model.lower() != "auto":
                return model

        complexity = classify_complexity(task)
        model = MODEL_TIERS.get(complexity, MODEL_TIERS["medium"])

        # Track routing stats
        _routing_stats[complexity] = _routing_stats.get(complexity, 0) + 1

        logger.info("Model router: task=%s... -> %s -> %s", task[:40], complexity, model)
        return model
    except Exception as e:
        logger.error("Model selection failed: %s", e)
        return MODEL_TIERS["medium"]


def get_routing_stats() -> dict[str, Any]:
    """Get statistics on how many tasks were routed to each tier.

    Returns:
        Dict with tier names as keys and call counts as values,
        plus total count.
    """
    total = sum(_routing_stats.values())
    return {
        "simple": _routing_stats.get("simple", 0),
        "medium": _routing_stats.get("medium", 0),
        "complex": _routing_stats.get("complex", 0),
        "total": total,
        "tiers": {k: v for k, v in MODEL_TIERS.items()},
    }


def reset_routing_stats() -> None:
    """Reset the in-memory routing statistics to zero.

    Useful for testing or periodic resets.
    """
    global _routing_stats
    _routing_stats = {"simple": 0, "medium": 0, "complex": 0}
    logger.info("Model routing stats reset")
