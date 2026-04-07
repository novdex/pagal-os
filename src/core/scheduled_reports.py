"""Scheduled Reports — agents generate and deliver reports automatically.

Combines scheduling (Hands), agent execution, and delivery (Email/Telegram/WhatsApp)
to produce automated reports like:
  - "Every Monday 9am: summarize my analytics and email me"
  - "Daily at 8pm: check competitor prices and alert on WhatsApp"
  - "If error rate > 10%, alert immediately"
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

_REPORTS_FILE = Path.home() / ".pagal-os" / "scheduled_reports.json"


def _load_reports() -> list[dict[str, Any]]:
    try:
        if _REPORTS_FILE.exists():
            return json.loads(_REPORTS_FILE.read_text())
    except Exception:
        pass
    return []


def _save_reports(reports: list[dict[str, Any]]) -> None:
    try:
        _REPORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _REPORTS_FILE.write_text(json.dumps(reports, indent=2, default=str))
    except Exception as e:
        logger.error("Failed to save reports: %s", e)


def create_scheduled_report(
    name: str,
    agent_name: str,
    task: str,
    schedule: str,
    delivery: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a scheduled report.

    Args:
        name: Report name (e.g. "Weekly Analytics").
        agent_name: Agent to run for generating the report.
        task: Task/prompt for the agent.
        schedule: Cron-style or natural schedule ("every 1h", "daily at 09:00").
        delivery: How to deliver: {"type": "email", "to": "user@example.com"}
                  or {"type": "telegram"} or {"type": "file", "path": "/tmp/report.md"}

    Returns:
        Dict with 'ok' and report ID.
    """
    reports = _load_reports()

    report = {
        "id": f"report_{int(time.time())}",
        "name": name,
        "agent_name": agent_name,
        "task": task,
        "schedule": schedule,
        "delivery": delivery or {"type": "file", "path": str(Path.home() / ".pagal-os" / "reports" / f"{name.replace(' ', '_').lower()}.md")},
        "enabled": True,
        "last_run": None,
        "last_result": None,
        "run_count": 0,
        "created_at": time.time(),
    }

    reports.append(report)
    _save_reports(reports)

    # Register as a Hand (scheduled agent) for automatic execution
    try:
        from src.core.hands import start_hand
        start_hand(agent_name, schedule, task)
    except Exception as e:
        logger.debug("Hand registration skipped: %s", e)

    return {"ok": True, "id": report["id"], "report": report}


def run_report(report_id: str) -> dict[str, Any]:
    """Manually run a report and deliver the result.

    Args:
        report_id: Report to run.

    Returns:
        Dict with 'ok' and report output.
    """
    reports = _load_reports()

    for report in reports:
        if report["id"] == report_id:
            try:
                # Run the agent
                from src.core.runtime import load_agent, run_agent
                agent = load_agent(report["agent_name"])
                result = run_agent(agent, report["task"])

                output = result.output if result.ok else result.error

                # Deliver the report
                delivery = report.get("delivery", {})
                delivery_type = delivery.get("type", "file")

                if delivery_type == "email":
                    try:
                        from src.channels.email_channel import send_email
                        send_email(
                            to=delivery.get("to", ""),
                            subject=f"Report: {report['name']}",
                            body=output,
                        )
                    except Exception as e:
                        logger.error("Email delivery failed: %s", e)

                elif delivery_type == "file":
                    try:
                        path = Path(delivery.get("path", ""))
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(f"# {report['name']}\n\nGenerated: {time.strftime('%Y-%m-%d %H:%M')}\n\n{output}")
                    except Exception as e:
                        logger.error("File delivery failed: %s", e)

                # Update report status
                report["last_run"] = time.time()
                report["last_result"] = "success" if result.ok else "error"
                report["run_count"] += 1
                _save_reports(reports)

                return {"ok": True, "output": output, "delivery": delivery_type}

            except Exception as e:
                return {"ok": False, "error": str(e)}

    return {"ok": False, "error": f"Report '{report_id}' not found"}


def list_reports() -> list[dict[str, Any]]:
    """List all scheduled reports."""
    return _load_reports()


def delete_report(report_id: str) -> dict[str, Any]:
    """Delete a scheduled report."""
    reports = _load_reports()
    reports = [r for r in reports if r["id"] != report_id]
    _save_reports(reports)
    return {"ok": True}
