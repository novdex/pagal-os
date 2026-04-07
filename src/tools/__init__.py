"""PAGAL OS tools — registry and built-in tools.

Importing this package auto-registers all built-in tools.
"""

from src.tools.registry import register_tool, get_tool, get_tool_schemas, list_tools, execute_tool  # noqa: F401
from src.tools import search, files, shell, browser, computer  # noqa: F401

# Multi-modal tools (image, PDF, audio) — import errors are non-fatal
try:
    from src.tools import multimodal  # noqa: F401
except Exception:
    pass

# Web crawler tools — import errors are non-fatal
try:
    from src.tools import crawler  # noqa: F401
except Exception:
    pass

# Integration tools (Google, GitHub, Notion) — import errors are non-fatal
try:
    from src import integrations  # noqa: F401
except Exception:
    pass

# RAG tools — document ingestion and query
try:
    from src.tools import rag_tools  # noqa: F401
except Exception:
    pass

# Webhook bridge tools — call external webhooks (Zapier/n8n)
try:
    from src.core import webhook_bridge  # noqa: F401
except Exception:
    pass

# Email tools — read and send emails
try:
    from src.channels import email_channel  # noqa: F401
except Exception:
    pass

# Auto-load user plugins from ~/.pagal-os/plugins/
try:
    from src.core.plugins import load_plugins
    load_plugins()
except Exception:
    pass
