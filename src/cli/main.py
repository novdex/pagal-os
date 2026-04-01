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
    """Handle the 'server' command -- start the API + web dashboard.

    Handles Ctrl+C gracefully: stops hands, closes DB connections, saves state.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    import signal

    import uvicorn

    from src.core.config import get_config

    config = get_config()
    print(f"Starting PAGAL OS server on http://localhost:{config.web_port}")
    print("Press Ctrl+C to stop.")

    def _graceful_shutdown(signum: int, frame: object) -> None:
        """Handle shutdown signal by cleaning up resources."""
        print("\nPAGAL OS shutting down...")

        # Stop all running hands
        try:
            from src.core.hands import _active_hands, stop_hand
            hand_names = list(_active_hands.keys())
            for name in hand_names:
                try:
                    stop_hand(name)
                except Exception:
                    pass
            if hand_names:
                print(f"  Stopped {len(hand_names)} hand(s).")
        except Exception:
            pass

        # Stop MCP server
        try:
            from src.core.mcp import stop_mcp_server
            stop_mcp_server()
        except Exception:
            pass

        # Stop A2A server
        try:
            from src.core.a2a import stop_a2a_server
            stop_a2a_server()
        except Exception:
            pass

        print("  Shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)

    try:
        uvicorn.run(
            "src.api.server:app",
            host="0.0.0.0",
            port=config.web_port,
            reload=False,
            log_level="info",
        )
    except SystemExit:
        pass


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


# --- Process Manager Commands ---


def cmd_ps(_args: argparse.Namespace) -> None:
    """Handle the 'ps' command — list all agent processes.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    from src.core.process_manager import get_system_stats, list_processes

    processes = list_processes()
    stats = get_system_stats()

    if not processes:
        print("No agent processes. Run an agent first.")
        return

    print(f"{'PID':<10} {'Agent':<20} {'Status':<12} {'Uptime':<10} {'Tokens':<10} {'Tools':<8} {'Pri':<5}")
    print("-" * 80)
    for p in processes:
        uptime_str = f"{p['uptime_seconds']:.0f}s"
        print(
            f"{p['pid']:<10} {p['agent_name']:<20} {p['status']:<12} "
            f"{uptime_str:<10} {p['tokens_used']:<10} {p['tool_calls']:<8} {p['priority']:<5}"
        )

    print(f"\nSystem: {stats['running']} running, {stats['total_tokens']} total tokens, "
          f"uptime {stats['uptime_seconds']:.0f}s")


def cmd_kill(args: argparse.Namespace) -> None:
    """Handle the 'kill' command — kill an agent process.

    Args:
        args: Parsed CLI arguments with 'pid' field.
    """
    from src.core.process_manager import kill_process

    if kill_process(args.pid):
        print(f"Process {args.pid} killed.")
    else:
        print(f"Process {args.pid} not found.", file=sys.stderr)
        sys.exit(1)


# --- Memory Commands ---


def cmd_memory_search(args: argparse.Namespace) -> None:
    """Handle 'memory search' — search an agent's cross-session memory.

    Args:
        args: Parsed CLI arguments with 'agent' and 'query' fields.
    """
    from src.core.memory import search_memory

    results = search_memory(args.agent, args.query)
    if not results:
        print(f"No memory found for agent '{args.agent}' matching '{args.query}'")
        return

    for r in results:
        source_tag = f"[{r.get('source', '?')}]"
        role = r.get("role", "")
        created = r.get("created_at", "")
        content = r.get("content", "")[:120]
        print(f"{source_tag} {role} ({created}): {content}")


def cmd_memory_stats(args: argparse.Namespace) -> None:
    """Handle 'memory stats' — show memory statistics.

    Args:
        args: Parsed CLI arguments with optional 'agent' field.
    """
    from src.core.memory import get_memory_stats

    agent_name = args.agent if hasattr(args, "agent") and args.agent else None
    stats = get_memory_stats(agent_name)

    print("Memory Stats:")
    print(f"  Messages:  {stats.get('total_messages', 0)}")
    print(f"  Summaries: {stats.get('total_summaries', 0)}")
    if "agents" in stats:
        print("\n  Per-Agent Messages:")
        for a in stats["agents"]:
            print(f"    {a['agent']}: {a['messages']}")


# --- Telegram Command ---


# --- Clone / Fork / Diff Commands ---


def cmd_clone(args: argparse.Namespace) -> None:
    """Handle the 'clone' command — clone an existing agent.

    Args:
        args: Parsed CLI arguments with 'source' and 'new_name' fields.
    """
    from src.core.cloning import clone_agent

    if clone_agent(args.source, args.new_name):
        print(f"Agent '{args.source}' cloned to '{args.new_name}'!")
        print(f"Run it with: python pagal.py run {args.new_name} \"your task here\"")
    else:
        print(f"Failed to clone agent '{args.source}'.", file=sys.stderr)
        sys.exit(1)


def cmd_fork(args: argparse.Namespace) -> None:
    """Handle the 'fork' command — fork an agent with modifications.

    Args:
        args: Parsed CLI arguments with 'source', 'new_name', and optional modifiers.
    """
    from src.core.cloning import fork_agent

    changes: dict = {}
    if hasattr(args, "model") and args.model:
        changes["model"] = args.model
    if hasattr(args, "personality") and args.personality:
        changes["personality"] = args.personality
    if hasattr(args, "add_tools") and args.add_tools:
        changes["add_tools"] = [t.strip() for t in args.add_tools.split(",") if t.strip()]
    if hasattr(args, "remove_tools") and args.remove_tools:
        changes["remove_tools"] = [t.strip() for t in args.remove_tools.split(",") if t.strip()]

    if fork_agent(args.source, args.new_name, changes):
        print(f"Agent '{args.source}' forked to '{args.new_name}'!")
        if changes:
            print(f"Changes applied: {', '.join(changes.keys())}")
    else:
        print(f"Failed to fork agent '{args.source}'.", file=sys.stderr)
        sys.exit(1)


def cmd_diff(args: argparse.Namespace) -> None:
    """Handle the 'diff' command — compare two agents.

    Args:
        args: Parsed CLI arguments with 'agent_a' and 'agent_b' fields.
    """
    from src.core.cloning import diff_agents

    result = diff_agents(args.agent_a, args.agent_b)
    if not result.get("ok"):
        print(f"Error: {result.get('error', 'unknown error')}", file=sys.stderr)
        sys.exit(1)

    if result.get("identical"):
        print(f"Agents '{args.agent_a}' and '{args.agent_b}' are identical (excluding metadata).")
    else:
        print(f"Differences between '{args.agent_a}' and '{args.agent_b}':")
        print("-" * 60)
        for d in result.get("differences", []):
            print(f"  {d['field']}:")
            print(f"    {args.agent_a}: {d['value_a']}")
            print(f"    {args.agent_b}: {d['value_b']}")


# --- Webhook Commands ---


def cmd_webhook_create(args: argparse.Namespace) -> None:
    """Handle 'webhook create' — register a new webhook trigger.

    Args:
        args: Parsed CLI arguments with 'agent' and 'event' fields.
    """
    from src.core.webhooks import register_webhook

    url = register_webhook(args.agent, args.event)
    if url:
        print(f"Webhook created for agent '{args.agent}'!")
        print(f"  URL: {url}")
        print(f"  Event type: {args.event}")
        print(f"\nSend a POST request to the URL to trigger the agent.")
    else:
        print("Failed to create webhook.", file=sys.stderr)
        sys.exit(1)


def cmd_webhook_list(_args: argparse.Namespace) -> None:
    """Handle 'webhook list' — list all registered webhooks.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    from src.core.webhooks import list_webhooks

    webhooks = list_webhooks()
    if not webhooks:
        print("No webhooks registered.")
        print("Create one with: python pagal.py webhook create <agent> --event http")
        return

    print(f"{'ID':<10} {'Agent':<20} {'Event':<10} {'Triggers':<10} {'URL'}")
    print("-" * 90)
    for wh in webhooks:
        print(
            f"{wh['id']:<10} {wh['agent_name']:<20} {wh['event_type']:<10} "
            f"{wh['trigger_count']:<10} {wh['url']}"
        )


def cmd_webhook_delete(args: argparse.Namespace) -> None:
    """Handle 'webhook delete' — remove a webhook.

    Args:
        args: Parsed CLI arguments with 'webhook_id' field.
    """
    from src.core.webhooks import delete_webhook

    if delete_webhook(args.webhook_id):
        print(f"Webhook '{args.webhook_id}' deleted.")
    else:
        print(f"Webhook '{args.webhook_id}' not found.", file=sys.stderr)
        sys.exit(1)


# --- Analytics Commands ---


def cmd_analytics(args: argparse.Namespace) -> None:
    """Handle the 'analytics' command — show agent analytics.

    Args:
        args: Parsed CLI arguments with optional 'agent' field.
    """
    if hasattr(args, "agent") and args.agent:
        from src.core.analytics import get_agent_analytics

        stats = get_agent_analytics(args.agent, days=30)
        print(f"Analytics for '{args.agent}' (last 30 days):")
        print(f"  Total runs:    {stats['total_runs']}")
        print(f"  Success rate:  {stats['success_rate']}%")
        print(f"  Avg duration:  {stats['avg_duration']}s")
        print(f"  Total tokens:  {stats['total_tokens']}")
        print(f"  Total cost:    ${stats['total_cost']:.4f}")
        print(f"  Runs/day:      {stats['runs_per_day']}")
    else:
        from src.core.analytics import get_all_analytics

        stats = get_all_analytics(days=30)
        print("System-wide Analytics (last 30 days):")
        print(f"  Total runs:    {stats['total_runs']}")
        print(f"  Success rate:  {stats['success_rate']}%")
        print(f"  Avg duration:  {stats['avg_duration']}s")
        print(f"  Total tokens:  {stats['total_tokens']}")
        print(f"  Total cost:    ${stats['total_cost']:.4f}")
        if stats.get("agents"):
            print(f"\n  Per-Agent Breakdown:")
            print(f"  {'Agent':<20} {'Runs':<8} {'Success':<10} {'Tokens':<10} {'Cost'}")
            print("  " + "-" * 60)
            for a in stats["agents"]:
                print(
                    f"  {a['agent_name']:<20} {a['runs']:<8} "
                    f"{a['success_rate']}%{'':<6} {a['tokens']:<10} "
                    f"${a['cost']:.4f}"
                )


# --- Telegram Command ---


# --- Versioning Commands ---


def cmd_versions(args: argparse.Namespace) -> None:
    """Handle 'versions' — list all versions of an agent.

    Args:
        args: Parsed CLI arguments with 'agent' field.
    """
    from src.core.versioning import list_versions

    versions = list_versions(args.agent)
    if not versions:
        print(f"No versions found for agent '{args.agent}'.")
        return

    print(f"Versions for agent '{args.agent}':")
    print(f"  {'Version':<10} {'Date':<30} {'Size'}")
    print("  " + "-" * 55)
    for v in versions:
        size = f"{v['size_bytes']} bytes"
        print(f"  v{v['version']:<9} {v['date']:<30} {size}")


def cmd_rollback(args: argparse.Namespace) -> None:
    """Handle 'rollback' — restore an agent to a previous version.

    Args:
        args: Parsed CLI arguments with 'agent' and 'version' fields.
    """
    from src.core.versioning import rollback

    if rollback(args.agent, args.version):
        print(f"Agent '{args.agent}' rolled back to version {args.version}.")
    else:
        print(f"Failed to rollback agent '{args.agent}' to version {args.version}.", file=sys.stderr)
        sys.exit(1)


# --- Encryption Commands ---


def cmd_encrypt(args: argparse.Namespace) -> None:
    """Handle 'encrypt' — encrypt an agent's memory and config.

    Args:
        args: Parsed CLI arguments with 'agent' field.
    """
    from src.core.encryption import encrypt_agent_memory

    if encrypt_agent_memory(args.agent):
        print(f"Agent '{args.agent}' memory and config encrypted.")
    else:
        print(f"No files found to encrypt for agent '{args.agent}'.")


def cmd_decrypt(args: argparse.Namespace) -> None:
    """Handle 'decrypt' — decrypt and display an agent's encrypted files.

    Args:
        args: Parsed CLI arguments with 'agent' field.
    """
    from src.core.encryption import decrypt_agent_memory

    results = decrypt_agent_memory(args.agent)
    if not results:
        print(f"No encrypted files found for agent '{args.agent}'.")
        return

    for r in results:
        print(f"\n--- {r['file']} ---")
        if "content" in r:
            print(r["content"][:500])
        elif "error" in r:
            print(f"Error: {r['error']}")


# --- Sharing Commands ---


def cmd_share(args: argparse.Namespace) -> None:
    """Handle 'share' — export an agent and generate a share code.

    Args:
        args: Parsed CLI arguments with 'agent' field.
    """
    from src.core.sharing import export_agent

    try:
        file_path = export_agent(args.agent)
        # The share code is embedded in the exported file
        import json
        from pathlib import Path

        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        code = data.get("share_code", "N/A")
        print(f"Agent '{args.agent}' shared!")
        print(f"  Share code: {code}")
        print(f"  File: {file_path}")
        print(f"\nSend the file to someone, or use the share code on the same machine.")
    except FileNotFoundError:
        print(f"Agent '{args.agent}' not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error sharing agent: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_import(args: argparse.Namespace) -> None:
    """Handle 'import' — import an agent from a shared file or code.

    Args:
        args: Parsed CLI arguments with 'source' field (file path or share code).
    """
    from pathlib import Path

    source = args.source

    # Check if it's a file path
    if Path(source).exists():
        from src.core.sharing import import_agent
        try:
            name = import_agent(source)
            print(f"Agent '{name}' imported successfully!")
            print(f"Run it with: python pagal.py run {name} \"your task here\"")
        except Exception as e:
            print(f"Error importing agent: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Try as a share code
        from src.core.sharing import get_shared_agent, import_agent as _import
        agent_data = get_shared_agent(source)
        if agent_data:
            # Write temp file and import
            import json
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8",
            ) as tmp:
                json.dump(agent_data, tmp, indent=2)
                tmp_path = tmp.name
            try:
                name = _import(tmp_path)
                print(f"Agent '{name}' imported from share code '{source}'!")
                print(f"Run it with: python pagal.py run {name} \"your task here\"")
            except Exception as e:
                print(f"Error importing agent: {e}", file=sys.stderr)
                sys.exit(1)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        else:
            print(f"Share code '{source}' not found, and it's not a valid file path.", file=sys.stderr)
            sys.exit(1)


# --- Traces Commands ---


def cmd_traces(args: argparse.Namespace) -> None:
    """Handle 'traces' — list recent agent traces.

    Args:
        args: Parsed CLI arguments with optional 'agent' field.
    """
    from src.core.observability import get_recent_traces

    agent_name = args.agent if hasattr(args, "agent") and args.agent else None
    traces = get_recent_traces(agent_name=agent_name, limit=20)

    if not traces:
        print("No traces recorded yet. Run an agent to generate traces.")
        return

    print(f"{'Run ID':<14} {'Agent':<20} {'Events':<8} {'Duration':<12} {'Tokens':<10} {'Started'}")
    print("-" * 90)
    for t in traces:
        dur = f"{t.get('total_duration_ms', 0)}ms"
        started = t.get("started_at", "")
        if isinstance(started, str) and len(started) > 19:
            started = started[:19]
        print(
            f"{t['run_id']:<14} {t['agent_name']:<20} "
            f"{t.get('event_count', 0):<8} {dur:<12} "
            f"{t.get('total_tokens', 0):<10} {started}"
        )


def cmd_trace_detail(args: argparse.Namespace) -> None:
    """Handle 'trace' — show detailed events for a specific trace run.

    Args:
        args: Parsed CLI arguments with 'run_id' field.
    """
    from src.core.observability import get_trace, get_trace_summary

    summary = get_trace_summary(args.run_id)
    if not summary.get("ok"):
        print(f"Trace '{args.run_id}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Trace: {args.run_id}")
    print(f"  Agent:      {summary.get('agent_name', '')}")
    print(f"  Events:     {summary.get('event_count', 0)}")
    print(f"  Duration:   {summary.get('total_time_ms', 0)}ms")
    print(f"  Tokens:     {summary.get('total_tokens', 0)}")
    print(f"  Tool calls: {summary.get('tool_calls_count', 0)}")
    print(f"  LLM calls:  {summary.get('llm_calls_count', 0)}")
    print(f"  Errors:     {summary.get('errors_count', 0)}")
    print()

    events = get_trace(args.run_id)
    for evt in events:
        etype = evt.get("event_type", "")
        content = evt.get("content", "")[:120]
        dur = evt.get("duration_ms", 0)
        dur_str = f" ({dur}ms)" if dur else ""
        print(f"  [{etype:<12}]{dur_str} {content}")


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


def cmd_doctor(_args: argparse.Namespace) -> None:
    """Handle the 'doctor' command -- run system health check.

    Args:
        _args: Parsed CLI arguments (unused).
    """
    from src.core.doctor import print_doctor_report, run_doctor

    report = run_doctor()
    print_doctor_report(report)


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

    # --- Clone / Fork / Diff commands ---
    clone_p = subparsers.add_parser("clone", help="Clone an existing agent")
    clone_p.add_argument("source", help="Source agent name")
    clone_p.add_argument("new_name", help="Name for the cloned agent")

    fork_p = subparsers.add_parser("fork", help="Fork an agent with modifications")
    fork_p.add_argument("source", help="Source agent name")
    fork_p.add_argument("new_name", help="Name for the forked agent")
    fork_p.add_argument("--model", default=None, help="New model to use")
    fork_p.add_argument("--personality", default=None, help="New personality")
    fork_p.add_argument("--add-tools", default=None, help="Comma-separated tools to add")
    fork_p.add_argument("--remove-tools", default=None, help="Comma-separated tools to remove")

    diff_p = subparsers.add_parser("diff", help="Show differences between two agents")
    diff_p.add_argument("agent_a", help="First agent name")
    diff_p.add_argument("agent_b", help="Second agent name")

    # --- Webhook commands ---
    webhook_p = subparsers.add_parser("webhook", help="Manage webhook triggers")
    webhook_sub = webhook_p.add_subparsers(dest="webhook_command", help="Webhook sub-commands")

    # pagal webhook create <agent> --event http
    webhook_create_p = webhook_sub.add_parser("create", help="Register a new webhook")
    webhook_create_p.add_argument("agent", help="Agent name to trigger")
    webhook_create_p.add_argument("--event", default="http", help='Event type: "http", "github", "email", "custom"')

    # pagal webhook list
    webhook_sub.add_parser("list", help="List all webhooks")

    # pagal webhook delete <id>
    webhook_delete_p = webhook_sub.add_parser("delete", help="Delete a webhook")
    webhook_delete_p.add_argument("webhook_id", help="Webhook ID to delete")

    # --- Analytics command ---
    analytics_p = subparsers.add_parser("analytics", help="View agent analytics")
    analytics_p.add_argument("--agent", default=None, help="Specific agent (omit for system-wide)")

    # --- Telegram command ---
    subparsers.add_parser("telegram", help="Start the Telegram bot")

    # --- Process Manager commands ---
    subparsers.add_parser("ps", help="List all agent processes")

    kill_p = subparsers.add_parser("kill", help="Kill an agent process")
    kill_p.add_argument("pid", help="Process ID to kill")

    # --- Versioning commands ---
    versions_p = subparsers.add_parser("versions", help="List all versions of an agent")
    versions_p.add_argument("agent", help="Agent name")

    rollback_p = subparsers.add_parser("rollback", help="Rollback an agent to a previous version")
    rollback_p.add_argument("agent", help="Agent name")
    rollback_p.add_argument("version", type=int, help="Version number to restore")

    # --- Encryption commands ---
    encrypt_p = subparsers.add_parser("encrypt", help="Encrypt an agent's memory and config")
    encrypt_p.add_argument("agent", help="Agent name to encrypt")

    decrypt_p = subparsers.add_parser("decrypt", help="Decrypt and show an agent's encrypted files")
    decrypt_p.add_argument("agent", help="Agent name to decrypt")

    # --- Sharing commands ---
    share_p = subparsers.add_parser("share", help="Share an agent (export + generate share code)")
    share_p.add_argument("agent", help="Agent name to share")

    import_p = subparsers.add_parser("import", help="Import an agent from a shared file or code")
    import_p.add_argument("source", help="File path or share code")

    # --- Doctor command ---
    subparsers.add_parser("doctor", help="Run system health check and auto-repair")

    # --- Traces commands ---
    traces_p = subparsers.add_parser("traces", help="List recent agent traces")
    traces_p.add_argument("--agent", default=None, help="Filter by agent name")

    trace_p = subparsers.add_parser("trace", help="View detailed trace events for a run")
    trace_p.add_argument("run_id", help="Run ID to view")

    # --- Memory commands ---
    memory_p = subparsers.add_parser("memory", help="Cross-session memory management")
    memory_sub = memory_p.add_subparsers(dest="memory_command", help="Memory sub-commands")

    # pagal memory search <agent> <query>
    memory_search_p = memory_sub.add_parser("search", help="Search an agent's memory")
    memory_search_p.add_argument("agent", help="Agent name")
    memory_search_p.add_argument("query", help="Search keywords")

    # pagal memory stats [--agent <name>]
    memory_stats_p = memory_sub.add_parser("stats", help="Show memory statistics")
    memory_stats_p.add_argument("--agent", default=None, help="Filter by agent name")

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

    # Route memory sub-commands
    if args.command == "memory":
        memory_commands = {
            "search": cmd_memory_search,
            "stats": cmd_memory_stats,
        }
        handler = memory_commands.get(args.memory_command)
        if handler:
            handler(args)
        else:
            memory_p.print_help()
        return

    # Route webhook sub-commands
    if args.command == "webhook":
        webhook_commands = {
            "create": cmd_webhook_create,
            "list": cmd_webhook_list,
            "delete": cmd_webhook_delete,
        }
        handler = webhook_commands.get(args.webhook_command)
        if handler:
            handler(args)
        else:
            webhook_p.print_help()
        return

    commands = {
        "create": cmd_create,
        "run": cmd_run,
        "list": cmd_list,
        "status": cmd_status,
        "stop": cmd_stop,
        "server": cmd_server,
        "telegram": cmd_telegram,
        "ps": cmd_ps,
        "kill": cmd_kill,
        "clone": cmd_clone,
        "fork": cmd_fork,
        "diff": cmd_diff,
        "analytics": cmd_analytics,
        "versions": cmd_versions,
        "rollback": cmd_rollback,
        "encrypt": cmd_encrypt,
        "decrypt": cmd_decrypt,
        "share": cmd_share,
        "import": cmd_import,
        "traces": cmd_traces,
        "trace": cmd_trace_detail,
        "doctor": cmd_doctor,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
