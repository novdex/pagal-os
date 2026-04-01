"""PAGAL OS Doctor — system health check and auto-repair.

Performs a comprehensive check of all PAGAL OS components:
configuration, tools, databases, directories, API keys, and more.
Auto-fixes what it can (missing directories, stale processes, corrupt JSON).

Usage:
    python pagal.py doctor

Or programmatically:
    from src.core.doctor import run_doctor
    results = run_doctor()
"""

import importlib
import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# All modules that should be importable
_ALL_MODULES = [
    "src.core.a2a",
    "src.core.analytics",
    "src.core.approval",
    "src.core.cloning",
    "src.core.collaboration",
    "src.core.config",
    "src.core.creator",
    "src.core.encryption",
    "src.core.hands",
    "src.core.healing",
    "src.core.knowledge",
    "src.core.llm",
    "src.core.marketplace",
    "src.core.mcp",
    "src.core.memory",
    "src.core.observability",
    "src.core.process_manager",
    "src.core.resources",
    "src.core.runtime",
    "src.core.sandbox",
    "src.core.security",
    "src.core.sharing",
    "src.core.validators",
    "src.core.versioning",
    "src.core.webhooks",
    "src.core.worlds",
    "src.api.routes",
    "src.api.server",
    "src.cli.main",
    "src.sdk.agent",
    "src.sdk.decorators",
    "src.tools.registry",
    "src.tools.browser",
    "src.tools.computer",
    "src.tools.files",
    "src.tools.multimodal",
    "src.tools.search",
    "src.tools.shell",
]


def _check_config() -> dict[str, Any]:
    """Check 1: Verify config loads correctly.

    Returns:
        Dict with 'ok', 'message', and optional 'fixed' keys.
    """
    try:
        from src.core.config import load_config
        config = load_config()
        if config.version >= 1:
            return {"ok": True, "message": "Config loads correctly"}
        return {"ok": False, "message": "Config loaded but version is invalid"}
    except Exception as e:
        return {"ok": False, "message": f"Config failed to load: {e}"}


def _check_tools() -> dict[str, Any]:
    """Check 2: Verify all 16 tools register.

    Returns:
        Dict with 'ok', 'message', 'details'.
    """
    try:
        import src.tools  # noqa: F401
        from src.tools.registry import list_tools
        tools = list_tools()
        count = len(tools)
        if count >= 16:
            return {"ok": True, "message": f"All {count} tools registered"}
        return {
            "ok": False,
            "message": f"Only {count}/16 tools registered",
            "details": tools,
        }
    except Exception as e:
        return {"ok": False, "message": f"Tool registration failed: {e}"}


def _check_agents_dir() -> dict[str, Any]:
    """Check 3: Verify agents directory exists and has agents.

    Returns:
        Dict with 'ok', 'message', and optional 'fixed'.
    """
    try:
        from src.core.config import get_config
        config = get_config()
        agents_dir = config.agents_dir

        if not agents_dir.exists():
            agents_dir.mkdir(parents=True, exist_ok=True)
            return {
                "ok": True,
                "message": "Agents directory created (was missing)",
                "fixed": True,
            }

        agents = list(agents_dir.glob("*.yaml"))
        if not agents:
            return {
                "ok": False,
                "message": f"Agents directory exists at {agents_dir} but has no agents",
            }

        return {
            "ok": True,
            "message": f"Agents directory has {len(agents)} agent(s)",
        }
    except Exception as e:
        return {"ok": False, "message": f"Agents directory check failed: {e}"}


def _check_databases() -> dict[str, Any]:
    """Check 4: Verify SQLite databases are healthy.

    Returns:
        Dict with 'ok', 'message', and optional 'fixed'.
    """
    try:
        from src.core.config import get_config
        config = get_config()
        db_path = config.base_dir / "pagal.db"

        if not db_path.exists():
            return {"ok": True, "message": "No databases yet (will be created on first use)"}

        # Check database integrity
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()

        if result and result[0] == "ok":
            return {"ok": True, "message": "SQLite database healthy"}

        return {"ok": False, "message": f"Database integrity check failed: {result}"}
    except Exception as e:
        return {"ok": False, "message": f"Database check failed: {e}"}


def _check_modules() -> dict[str, Any]:
    """Check 5: Verify all modules import without errors.

    Returns:
        Dict with 'ok', 'message', 'details'.
    """
    failed: list[str] = []
    loaded = 0

    for module_name in _ALL_MODULES:
        try:
            importlib.import_module(module_name)
            loaded += 1
        except Exception as e:
            failed.append(f"{module_name}: {e}")

    total = len(_ALL_MODULES)
    if not failed:
        return {"ok": True, "message": f"All {total} modules import successfully"}
    return {
        "ok": False,
        "message": f"{loaded}/{total} modules loaded, {len(failed)} failed",
        "details": failed,
    }


def _check_storage_dirs() -> dict[str, Any]:
    """Check 6: Verify storage directories exist, create if missing.

    Returns:
        Dict with 'ok', 'message', and optional 'fixed'.
    """
    try:
        from src.core.config import get_config
        config = get_config()

        required_dirs = [
            config.base_dir,
            config.agents_dir,
            config.memory_dir,
            config.tools_dir,
            config.logs_dir,
            config.base_dir / "versions",
            config.base_dir / "shared",
            config.base_dir / "teams",
        ]

        created: list[str] = []
        for d in required_dirs:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created.append(str(d))

        if created:
            return {
                "ok": True,
                "message": f"Created {len(created)} missing director(ies)",
                "fixed": True,
                "details": created,
            }

        return {"ok": True, "message": "All storage directories exist"}
    except Exception as e:
        return {"ok": False, "message": f"Storage directory check failed: {e}"}


def _check_api_key() -> dict[str, Any]:
    """Check 7: Verify API key is configured (OpenRouter).

    Returns:
        Dict with 'ok', 'message'.
    """
    try:
        from src.core.config import get_config
        config = get_config()

        if config.openrouter_api_key:
            # Mask the key for display
            masked = config.openrouter_api_key[:8] + "..." + config.openrouter_api_key[-4:]
            return {"ok": True, "message": f"API key configured ({masked})"}

        return {
            "ok": False,
            "message": "No OPENROUTER_API_KEY set. Set it in .env or environment.",
        }
    except Exception as e:
        return {"ok": False, "message": f"API key check failed: {e}"}


def _check_disk_space() -> dict[str, Any]:
    """Check 8: Verify sufficient disk space.

    Returns:
        Dict with 'ok', 'message'.
    """
    try:
        from src.core.config import get_config
        config = get_config()

        usage = shutil.disk_usage(str(config.base_dir))
        free_gb = usage.free / (1024 ** 3)

        if free_gb < 0.1:
            return {
                "ok": False,
                "message": f"Low disk space: {free_gb:.2f} GB free",
            }

        return {
            "ok": True,
            "message": f"Disk space OK: {free_gb:.1f} GB free",
        }
    except Exception as e:
        return {"ok": False, "message": f"Disk space check failed: {e}"}


def _check_stale_hands() -> dict[str, Any]:
    """Check 9: Check for stale hands/processes and clean up.

    Returns:
        Dict with 'ok', 'message', and optional 'fixed'.
    """
    try:
        from src.core.config import get_config
        config = get_config()
        hands_file = config.base_dir / "hands.json"

        if not hands_file.exists():
            return {"ok": True, "message": "No stale hands"}

        try:
            data = json.loads(hands_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                # Fix corrupt hands.json
                hands_file.write_text("[]", encoding="utf-8")
                return {
                    "ok": True,
                    "message": "Fixed corrupt hands.json (was not a list)",
                    "fixed": True,
                }
        except json.JSONDecodeError:
            hands_file.write_text("[]", encoding="utf-8")
            return {
                "ok": True,
                "message": "Fixed corrupt hands.json (invalid JSON)",
                "fixed": True,
            }

        return {"ok": True, "message": f"Hands file OK ({len(data)} entries)"}
    except Exception as e:
        return {"ok": False, "message": f"Stale hands check failed: {e}"}


def _check_marketplace() -> dict[str, Any]:
    """Check 10: Verify marketplace registry is valid.

    Returns:
        Dict with 'ok', 'message', and optional 'fixed'.
    """
    try:
        from src.core.config import get_config
        config = get_config()
        marketplace_file = config.base_dir / "marketplace.json"

        if not marketplace_file.exists():
            return {"ok": True, "message": "No marketplace registry yet (will be created on first use)"}

        try:
            data = json.loads(marketplace_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {
                    "ok": True,
                    "message": f"Marketplace registry valid ({len(data)} entries)",
                }
            # Fix corrupt marketplace
            marketplace_file.write_text("[]", encoding="utf-8")
            return {
                "ok": True,
                "message": "Fixed corrupt marketplace.json (was not a list)",
                "fixed": True,
            }
        except json.JSONDecodeError:
            marketplace_file.write_text("[]", encoding="utf-8")
            return {
                "ok": True,
                "message": "Fixed corrupt marketplace.json (invalid JSON)",
                "fixed": True,
            }
    except Exception as e:
        return {"ok": False, "message": f"Marketplace check failed: {e}"}


def run_doctor() -> dict[str, Any]:
    """Run all health checks and return a comprehensive report.

    Returns:
        Dict with 'total', 'passed', 'failed', 'fixed', and 'checks' list.
    """
    checks = [
        ("Config", _check_config),
        ("Tools", _check_tools),
        ("Agents Directory", _check_agents_dir),
        ("Databases", _check_databases),
        ("Modules", _check_modules),
        ("Storage Directories", _check_storage_dirs),
        ("API Key", _check_api_key),
        ("Disk Space", _check_disk_space),
        ("Stale Hands", _check_stale_hands),
        ("Marketplace", _check_marketplace),
    ]

    results: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    fixed = 0

    for name, check_fn in checks:
        try:
            result = check_fn()
            result["name"] = name
            results.append(result)

            if result.get("ok"):
                passed += 1
            else:
                failed += 1

            if result.get("fixed"):
                fixed += 1
        except Exception as e:
            logger.error("Doctor check '%s' crashed: %s", name, e)
            results.append({
                "name": name,
                "ok": False,
                "message": f"Check crashed: {e}",
            })
            failed += 1

    total = len(checks)

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "fixed": fixed,
        "checks": results,
    }


def print_doctor_report(report: dict[str, Any]) -> None:
    """Print a formatted doctor report to stdout.

    Args:
        report: The report dict from run_doctor().
    """
    total = report["total"]
    passed = report["passed"]
    failed = report["failed"]
    fixed = report["fixed"]

    print()
    print("=" * 60)
    print(f"  PAGAL OS Doctor -- {passed}/{total} checks passed")
    print("=" * 60)
    print()

    for check in report["checks"]:
        icon = "[PASS]" if check.get("ok") else "[FAIL]"
        fix_tag = " (auto-fixed)" if check.get("fixed") else ""
        print(f"  {icon} {check['name']}: {check['message']}{fix_tag}")

        # Print details if present and check failed
        details = check.get("details")
        if details and not check.get("ok"):
            if isinstance(details, list):
                for item in details[:5]:
                    print(f"         - {item}")
                if len(details) > 5:
                    print(f"         ... and {len(details) - 5} more")

    print()
    if failed == 0:
        print("  All systems healthy!")
    else:
        print(f"  {failed} issue(s) found.")
        if fixed > 0:
            print(f"  {fixed} issue(s) auto-fixed.")
    print()
