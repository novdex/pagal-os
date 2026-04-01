#!/usr/bin/env python3
"""PAGAL OS — AI Agent Operating System.

Run: python pagal.py <command>

Commands:
    create    - Create a new agent from a description
    run       - Run an agent with a task
    list      - List all available agents
    status    - Show agent status
    stop      - Stop a running agent
    server    - Start the API + web dashboard
    hand      - Manage autonomous scheduled agents (start/stop/list)
    team      - Multi-agent team collaboration (create/run/list)
    telegram  - Start the Telegram bot
    ps        - List all agent processes (process manager)
    kill      - Kill an agent process by PID
    memory    - Cross-session memory management (search/stats)
"""

import sys
from pathlib import Path

# Ensure project root is on Python path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.cli.main import main

if __name__ == "__main__":
    main()
