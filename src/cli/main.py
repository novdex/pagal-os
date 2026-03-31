"""PAGAL OS CLI — command-line interface for managing AI agents."""

import argparse
import json
import logging
import sys

logger = logging.getLogger("pagal_os")


def _setup_logging() -> None:
    """Configure logging for the CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_create(args: argparse.Namespace) -> None:
    """Handle the 'create' command — create an agent from a description.

    Args:
        args: Parsed CLI arguments with 'description' field.
    """
    from src.core.creator import create_agent_from_description

    print(f"Creating agent from: {args.description}")
    try:
        name = create_agent_from_description(args.description)
        print(f"Agent '{name}' created successfully!")
        print(f"Run it with: python pagal.py run {name} \"your task here\"")
    except Exception as e:
        print(f"Error creating agent: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_run(args: argparse.Namespace) -> None:
    """Handle the 'run' command — execute an agent with a task.

    Args:
        args: Parsed CLI arguments with 'agent' and 'task' fields.
    """
    from src.core.runtime import load_agent, run_agent
    from src.core.sandbox import run_in_sandbox

    print(f"Running agent '{args.agent}' with task: {args.task}")
    print("-" * 60)

    try:
        agent = load_agent(args.agent)
        result = run_in_sandbox(agent, args.task)

        if result.ok:
            print(result.output)
            print("-" * 60)
            print(f"Tools used: {', '.join(result.tools_used) if result.tools_used else 'none'}")
            print(f"Duration: {result.duration_seconds:.1f}s")
        else:
            print(f"Error: {result.error}", file=sys.stderr)
            sys.exit(1)
    except FileNotFoundError as e:
        print(f"Agent not found: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(_args: argparse.Namespace) -> None:
    """Handle the 'list' command — list all available agents.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    from src.core.runtime import list_agents

    agents = list_agents()

    if not agents:
        print("No agents found. Create one with: python pagal.py create \"description\"")
        return

    print(f"{'Name':<20} {'Status':<12} {'Description'}")
    print("-" * 60)
    for agent in agents:
        status_icon = "[*]" if agent["status"] == "running" else "[ ]"
        print(f"{agent['name']:<20} {status_icon} {agent['status']:<9} {agent['description'][:40]}")


def cmd_status(args: argparse.Namespace) -> None:
    """Handle the 'status' command — show agent statuses.

    Args:
        args: Parsed CLI arguments.
    """
    from src.core.runtime import get_agent_status, list_agents

    if hasattr(args, "agent") and args.agent:
        status = get_agent_status(args.agent)
        print(json.dumps(status, indent=2))
    else:
        agents = list_agents()
        for agent in agents:
            status = get_agent_status(agent["name"])
            print(f"{agent['name']}: {status.get('status', 'unknown')}")


def cmd_stop(args: argparse.Namespace) -> None:
    """Handle the 'stop' command — stop a running agent.

    Args:
        args: Parsed CLI arguments with 'agent' field.
    """
    from src.core.runtime import stop_agent

    if stop_agent(args.agent):
        print(f"Agent '{args.agent}' stopped.")
    else:
        print(f"Agent '{args.agent}' is not running.")


def cmd_server(_args: argparse.Namespace) -> None:
    """Handle the 'server' command — start the API + web dashboard.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    import uvicorn

    from src.core.config import get_config

    config = get_config()
    print(f"Starting PAGAL OS server on http://localhost:{config.web_port}")
    print("Press Ctrl+C to stop.")

    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=config.web_port,
        reload=False,
        log_level="info",
    )


def main() -> None:
    """Entry point for the PAGAL OS CLI."""
    _setup_logging()

    # Ensure tools are loaded
    import src.tools  # noqa: F401

    parser = argparse.ArgumentParser(
        prog="pagal",
        description="PAGAL OS — AI Agent Operating System",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # pagal create "description"
    create_p = subparsers.add_parser("create", help="Create a new agent from a description")
    create_p.add_argument("description", help="Natural language description of the agent")

    # pagal run <agent> "task"
    run_p = subparsers.add_parser("run", help="Run an agent with a task")
    run_p.add_argument("agent", help="Name of the agent to run")
    run_p.add_argument("task", help="Task for the agent to perform")

    # pagal list
    subparsers.add_parser("list", help="List all available agents")

    # pagal status [agent]
    status_p = subparsers.add_parser("status", help="Show agent status")
    status_p.add_argument("agent", nargs="?", default=None, help="Agent name (optional)")

    # pagal stop <agent>
    stop_p = subparsers.add_parser("stop", help="Stop a running agent")
    stop_p.add_argument("agent", help="Name of the agent to stop")

    # pagal server
    subparsers.add_parser("server", help="Start the API + web dashboard")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    commands = {
        "create": cmd_create,
        "run": cmd_run,
        "list": cmd_list,
        "status": cmd_status,
        "stop": cmd_stop,
        "server": cmd_server,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
