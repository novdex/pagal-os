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
    doctor    - Run system health check and auto-repair
"""

import signal
import sys
from pathlib import Path

# Ensure project root is on Python path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.cli.main import main


def _shutdown_handler(signum: int, frame: object) -> None:
    """Handle Ctrl+C at the top level — stop hands, save state, exit cleanly."""
    print("\nPAGAL OS shutting down...")
    try:
        from src.core.hands import _active_hands, stop_hand
        for name in list(_active_hands.keys()):
            try:
                stop_hand(name)
            except Exception:
                pass
    except Exception:
        pass
    print("  Shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)
    main()
