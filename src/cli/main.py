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


# --- Store Commands ---


def cmd_store_search(args: argparse.Namespace) -> None:
    """Handle 'store search' — search the agent marketplace.

    Args:
        args: Parsed CLI arguments with 'query' field.
    """
    from src.core.marketplace import search_marketplace

    results = search_marketplace(args.query)
    if not results:
        print(f"No agents found for '{args.query}'")
        return

    print(f"{'ID':<20} {'Name':<25} {'Description'}")
    print("-" * 80)
    for agent in results:
        print(f"{agent['id']:<20} {agent['name']:<25} {agent['description'][:35]}")


def cmd_store_install(args: argparse.Namespace) -> None:
    """Handle 'store install' — install an agent from the marketplace.

    Args:
        args: Parsed CLI arguments with 'agent_id' field.
    """
    from src.core.marketplace import install_agent

    print(f"Installing agent '{args.agent_id}'...")
    if install_agent(args.agent_id):
        print(f"Agent '{args.agent_id}' installed successfully!")
        print(f"Run it with: python pagal.py run {args.agent_id} \"your task here\"")
    else:
        print(f"Failed to install agent '{args.agent_id}'.", file=sys.stderr)
        sys.exit(1)


def cmd_store_list(_args: argparse.Namespace) -> None:
    """Handle 'store list' — list all marketplace agents.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    from src.core.marketplace import list_marketplace

    agents = list_marketplace()
    if not agents:
        print("Marketplace is empty.")
        return

    print(f"{'ID':<20} {'Name':<25} {'Downloads':<10} {'Description'}")
    print("-" * 90)
    for agent in agents:
        print(
            f"{agent['id']:<20} {agent['name']:<25} "
            f"{agent.get('downloads', 0):<10} {agent['description'][:35]}"
        )


# --- Knowledge Commands ---


def cmd_knowledge_search(args: argparse.Namespace) -> None:
    """Handle 'knowledge search' — search the knowledge graph.

    Args:
        args: Parsed CLI arguments with 'query' and optional 'agent' fields.
    """
    from src.core.knowledge import search_knowledge

    agent_name = args.agent if hasattr(args, "agent") and args.agent else None
    results = search_knowledge(args.query, agent_name=agent_name)

    if not results:
        print(f"No knowledge found for '{args.query}'")
        return

    for node in results:
        print(f"[{node['id']}] {node['topic']} (by {node['agent_name']})")
        print(f"    {node['content'][:80]}")
        if node.get("source"):
            print(f"    Source: {node['source']}")
        print()


def cmd_knowledge_stats(_args: argparse.Namespace) -> None:
    """Handle 'knowledge stats' — show knowledge graph statistics.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    from src.core.knowledge import get_stats

    stats = get_stats()
    print(f"Knowledge Graph Stats:")
    print(f"  Facts:       {stats['total_nodes']}")
    print(f"  Connections: {stats['total_edges']}")
    print(f"  Topics:      {stats['unique_topics']}")
    if stats["top_topics"]:
        print("\n  Top Topics:")
        for t in stats["top_topics"]:
            print(f"    - {t['topic']} ({t['count']} entries)")


# --- Hands Commands ---


def cmd_hand_start(args: argparse.Namespace) -> None:
    """Handle 'hand start' — start an autonomous scheduled agent.

    Args:
        args: Parsed CLI arguments with 'agent', 'schedule', and 'task' fields.
    """
    from src.core.hands import start_hand

    result = start_hand(args.agent, args.schedule, args.task)
    if result.get("ok"):
        print(f"Hand started: {result['agent']}")
        print(f"  Schedule: {result['schedule']} (every {result['interval_seconds']}s)")
        print(f"  Task: {args.task}")
    else:
        print(f"Error: {result.get('error', 'unknown error')}", file=sys.stderr)
        sys.exit(1)


def cmd_hand_stop(args: argparse.Namespace) -> None:
    """Handle 'hand stop' — stop a scheduled hand.

    Args:
        args: Parsed CLI arguments with 'agent' field.
    """
    from src.core.hands import stop_hand

    if stop_hand(args.agent):
        print(f"Hand '{args.agent}' stopped.")
    else:
        print(f"Hand '{args.agent}' is not running.")


def cmd_hand_list(_args: argparse.Namespace) -> None:
    """Handle 'hand list' — list all active hands.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    from src.core.hands import list_hands

    hands = list_hands()
    if not hands:
        print("No active hands. Start one with:")
        print('  python pagal.py hand start <agent> --schedule "every 1h" --task "your task"')
        return

    print(f"{'Agent':<20} {'Status':<10} {'Schedule':<15} {'Last Run':<25} {'Task'}")
    print("-" * 100)
    for h in hands:
        last_run = h.get("last_run", "never") or "never"
        if isinstance(last_run, str) and len(last_run) > 22:
            last_run = last_run[:22]
        print(
            f"{h['agent']:<20} {h['status']:<10} {h['schedule']:<15} "
            f"{last_run:<25} {h['task'][:30]}"
        )


# --- Team Commands ---


def cmd_team_create(args: argparse.Namespace) -> None:
    """Handle 'team create' — create a multi-agent team.

    Args:
        args: Parsed CLI arguments with 'name', 'agents', and 'coordinator' fields.
    """
    from src.core.collaboration import create_team

    agents_list = [a.strip() for a in args.agents.split(",") if a.strip()]
    goal = args.goal if hasattr(args, "goal") and args.goal else f"Team {args.name}"

    result = create_team(args.name, agents_list, args.coordinator, goal)
    if result.get("ok"):
        print(f"Team '{result['name']}' created!")
        print(f"  Coordinator: {result['coordinator']}")
        print(f"  Agents: {', '.join(result['agents'])}")
        print(f"  Goal: {result['goal']}")
    else:
        print(f"Error: {result.get('error', 'unknown error')}", file=sys.stderr)
        sys.exit(1)


def cmd_team_run(args: argparse.Namespace) -> None:
    """Handle 'team run' — execute a task with a team.

    Args:
        args: Parsed CLI arguments with 'name' and 'task' fields.
    """
    from src.core.collaboration import run_team

    print(f"Running team '{args.name}' with task: {args.task}")
    print("Coordinating agents... this may take a while.")
    print("-" * 60)

    result = run_team(args.name, args.task)

    if result.get("ok"):
        print("\n=== TEAM REPORT ===\n")
        print(result["report"])
        print("\n=== SUBTASKS ===\n")
        for st in result.get("subtasks", []):
            status = "OK" if st.get("ok") else "FAILED"
            print(f"  [{status}] {st['agent']}: {st['subtask']}")
            if st.get("error"):
                print(f"         Error: {st['error']}")
        print(f"\nAgents used: {', '.join(result.get('agents_used', []))}")
    else:
        print(f"Error: {result.get('error', 'unknown error')}", file=sys.stderr)
        sys.exit(1)


def cmd_team_list(_args: argparse.Namespace) -> None:
    """Handle 'team list' — list all defined teams.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    from src.core.collaboration import list_teams

    teams = list_teams()
    if not teams:
        print("No teams found. Create one with:")
        print('  python pagal.py team create "name" --agents "a1,a2" --coordinator "a1"')
        return

    print(f"{'Name':<20} {'Coordinator':<20} {'Agents':<30} {'Goal'}")
    print("-" * 90)
    for t in teams:
        agents_str = ", ".join(t["agents"][:3])
        if len(t["agents"]) > 3:
            agents_str += f" (+{len(t['agents']) - 3})"
        print(f"{t['name']:<20} {t['coordinator']:<20} {agents_str:<30} {t['goal'][:30]}")


# --- Telegram Command ---


def cmd_telegram(_args: argparse.Namespace) -> None:
    """Handle 'telegram' — start the Telegram bot.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    import os

    from src.channels.telegram import start_telegram_bot

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not set.", file=sys.stderr)
        print("Set it in your .env file: TELEGRAM_BOT_TOKEN=your_token_here")
        print("Get a token from @BotFather on Telegram.")
        sys.exit(1)

    default_agent = "research_agent"
    # Try to load from config
    try:
        import yaml
        from pathlib import Path

        config_path = Path(__file__).parent.parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            tg_cfg = cfg.get("telegram", {})
            if isinstance(tg_cfg, dict):
                default_agent = tg_cfg.get("default_agent", default_agent)
    except Exception:
        pass

    start_telegram_bot(bot_token, default_agent)


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

    # --- Store commands ---
    store_p = subparsers.add_parser("store", help="Browse and install agents from the marketplace")
    store_sub = store_p.add_subparsers(dest="store_command", help="Store sub-commands")

    # pagal store search <query>
    store_search_p = store_sub.add_parser("search", help="Search the marketplace")
    store_search_p.add_argument("query", help="Search query")

    # pagal store install <id>
    store_install_p = store_sub.add_parser("install", help="Install an agent from the marketplace")
    store_install_p.add_argument("agent_id", help="Agent ID to install")

    # pagal store list
    store_sub.add_parser("list", help="List all marketplace agents")

    # --- Knowledge commands ---
    knowledge_p = subparsers.add_parser("knowledge", help="Query the knowledge graph")
    knowledge_sub = knowledge_p.add_subparsers(dest="knowledge_command", help="Knowledge sub-commands")

    # pagal knowledge search <query> [--agent <name>]
    knowledge_search_p = knowledge_sub.add_parser("search", help="Search the knowledge graph")
    knowledge_search_p.add_argument("query", help="Search query")
    knowledge_search_p.add_argument("--agent", default=None, help="Filter by agent name")

    # pagal knowledge stats
    knowledge_sub.add_parser("stats", help="Show knowledge graph statistics")

    # --- Hand commands ---
    hand_p = subparsers.add_parser("hand", help="Manage autonomous scheduled agents (Hands)")
    hand_sub = hand_p.add_subparsers(dest="hand_command", help="Hand sub-commands")

    # pagal hand start <agent> --schedule "every 1h" --task "find AI news"
    hand_start_p = hand_sub.add_parser("start", help="Start a scheduled hand")
    hand_start_p.add_argument("agent", help="Name of the agent to schedule")
    hand_start_p.add_argument("--schedule", required=True, help='Schedule: "every 5m", "every 1h", "daily at 08:00"')
    hand_start_p.add_argument("--task", required=True, help="Task for the hand to execute on each run")

    # pagal hand stop <agent>
    hand_stop_p = hand_sub.add_parser("stop", help="Stop a scheduled hand")
    hand_stop_p.add_argument("agent", help="Name of the hand to stop")

    # pagal hand list
    hand_sub.add_parser("list", help="List all active hands")

    # --- Team commands ---
    team_p = subparsers.add_parser("team", help="Multi-agent team collaboration")
    team_sub = team_p.add_subparsers(dest="team_command", help="Team sub-commands")

    # pagal team create "name" --agents "a1,a2" --coordinator "a1"
    team_create_p = team_sub.add_parser("create", help="Create a new team")
    team_create_p.add_argument("name", help="Team name")
    team_create_p.add_argument("--agents", required=True, help="Comma-separated agent names")
    team_create_p.add_argument("--coordinator", required=True, help="Coordinator agent name")
    team_create_p.add_argument("--goal", default="", help="Team goal description")

    # pagal team run <name> "task"
    team_run_p = team_sub.add_parser("run", help="Run a team task")
    team_run_p.add_argument("name", help="Team name")
    team_run_p.add_argument("task", help="Task for the team to execute")

    # pagal team list
    team_sub.add_parser("list", help="List all teams")

    # --- Telegram command ---
    subparsers.add_parser("telegram", help="Start the Telegram bot")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # Route store sub-commands
    if args.command == "store":
        store_commands = {
            "search": cmd_store_search,
            "install": cmd_store_install,
            "list": cmd_store_list,
        }
        handler = store_commands.get(args.store_command)
        if handler:
            handler(args)
        else:
            store_p.print_help()
        return

    # Route knowledge sub-commands
    if args.command == "knowledge":
        knowledge_commands = {
            "search": cmd_knowledge_search,
            "stats": cmd_knowledge_stats,
        }
        handler = knowledge_commands.get(args.knowledge_command)
        if handler:
            handler(args)
        else:
            knowledge_p.print_help()
        return

    # Route hand sub-commands
    if args.command == "hand":
        hand_commands = {
            "start": cmd_hand_start,
            "stop": cmd_hand_stop,
            "list": cmd_hand_list,
        }
        handler = hand_commands.get(args.hand_command)
        if handler:
            handler(args)
        else:
            hand_p.print_help()
        return

    # Route team sub-commands
    if args.command == "team":
        team_commands = {
            "create": cmd_team_create,
            "run": cmd_team_run,
            "list": cmd_team_list,
        }
        handler = team_commands.get(args.team_command)
        if handler:
            handler(args)
        else:
            team_p.print_help()
        return

    commands = {
        "create": cmd_create,
        "run": cmd_run,
        "list": cmd_list,
        "status": cmd_status,
        "stop": cmd_stop,
        "server": cmd_server,
        "telegram": cmd_telegram,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
