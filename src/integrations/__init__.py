"""PAGAL OS Integrations — plugin system for connecting agents to popular apps.

Importing this package auto-registers all integration tools (Google, GitHub, Notion).
"""

from src.integrations import google  # noqa: F401
from src.integrations import github_integration  # noqa: F401
from src.integrations import notion  # noqa: F401
