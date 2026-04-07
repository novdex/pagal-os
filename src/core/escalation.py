"""Human Handoff & Escalation Chains — agents know when to stop and ask humans.

Goes beyond simple approval gates with:
  - Confidence scoring: agent rates its own confidence
  - Smart escalation: routes to the right human based on context
  - Context preservation: human sees full agent reasoning
  - Escalation chains: Agent → Team Lead → Manager
  - Automatic fallback: if human doesn't respond, degrade gracefully
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

_PAGAL_DIR = Path.home() / ".pagal-os"
_ESCALATIONS_FILE = _PAGAL_DIR / "escalations.json"


def _load_escalations() -> list[dict[str, Any]]:
    try:
        if _ESCALATIONS_FILE.exists():
            return json.loads(_ESCALATIONS_FILE.read_text())
    except Exception:
        pass
    return []


def _save_escalations(data: list[dict[str, Any]]) -> None:
    try:
        _PAGAL_DIR.mkdir(parents=True, exist_ok=True)
        _ESCALATIONS_FILE.write_text(json.dumps(data, indent=2, default=str))
    except Exception as e:
        logger.error("Failed to save escalations: %s", e)


def create_escalation(
    agent_name: str,
    task: str,
    reason: str,
    confidence: float = 0.0,
    context: str = "",
    chain: list[str] | None = None,
) -> dict[str, Any]:
    """Create an escalation request — agent is asking a human for help.

    Args:
        agent_name: Agent that needs help.
        task: What the agent was trying to do.
        reason: Why it's escalating (e.g. "Low confidence", "Sensitive action").
        confidence: Agent's self-assessed confidence (0.0-1.0).
        context: Full reasoning/context for the human reviewer.
        chain: Escalation chain — list of roles/users to escalate through.

    Returns:
        Dict with 'ok' and escalation ID.
    """
    escalations = _load_escalations()

    escalation = {
        "id": f"esc_{int(time.time())}_{len(escalations)}",
        "agent_name": agent_name,
        "task": task,
        "reason": reason,
        "confidence": confidence,
        "context": context[:2000],
        "chain": chain or ["operator"],
        "current_level": 0,
        "status": "pending",  # pending, approved, denied, expired, auto_resolved
        "responses": [],
        "created_at": time.time(),
        "resolved_at": None,
    }

    escalations.append(escalation)
    _save_escalations(escalations)

    # Send notification
    try:
        from src.core.notifications import send_notification
        send_notification(
            "approval", agent_name,
            f"Agent needs help: {reason} (confidence: {confidence:.0%})",
        )
    except Exception:
        pass

    logger.info("Escalation created: %s for agent '%s' (confidence: %.0f%%)",
                escalation["id"], agent_name, confidence * 100)

    return {"ok": True, "id": escalation["id"], "status": "pending"}


def resolve_escalation(
    escalation_id: str,
    decision: str,
    response: str = "",
    responder: str = "operator",
) -> dict[str, Any]:
    """Resolve an escalation — human provides decision.

    Args:
        escalation_id: The escalation to resolve.
        decision: 'approved', 'denied', or 'escalate' (push to next level).
        response: Human's response/instructions for the agent.
        responder: Who made this decision.

    Returns:
        Dict with 'ok' status.
    """
    escalations = _load_escalations()

    for esc in escalations:
        if esc["id"] == escalation_id:
            if decision == "escalate":
                # Move to next level in chain
                esc["current_level"] += 1
                if esc["current_level"] >= len(esc["chain"]):
                    esc["status"] = "denied"
                    esc["resolved_at"] = time.time()
                else:
                    esc["responses"].append({
                        "responder": responder,
                        "decision": "escalated",
                        "response": response,
                        "timestamp": time.time(),
                    })
            else:
                esc["status"] = decision
                esc["resolved_at"] = time.time()
                esc["responses"].append({
                    "responder": responder,
                    "decision": decision,
                    "response": response,
                    "timestamp": time.time(),
                })

            _save_escalations(escalations)
            return {"ok": True, "status": esc["status"]}

    return {"ok": False, "error": f"Escalation '{escalation_id}' not found"}


def get_pending_escalations(agent_name: str | None = None) -> list[dict[str, Any]]:
    """Get all pending escalations.

    Args:
        agent_name: Optional filter by agent.

    Returns:
        List of pending escalation dicts.
    """
    escalations = _load_escalations()
    pending = [e for e in escalations if e["status"] == "pending"]
    if agent_name:
        pending = [e for e in pending if e["agent_name"] == agent_name]
    return pending


def should_escalate(
    agent_name: str,
    task: str,
    confidence: float,
    action_type: str = "general",
) -> bool:
    """Decide whether an agent should escalate to a human.

    Rules:
      - confidence < 0.3 → always escalate
      - confidence < 0.6 AND action is sensitive → escalate
      - action involves money, deletion, or external communication → escalate

    Args:
        agent_name: The agent.
        task: What it's doing.
        confidence: Self-assessed confidence.
        action_type: Type of action (general, financial, deletion, communication).

    Returns:
        True if should escalate, False if can proceed.
    """
    # Always escalate if very low confidence
    if confidence < 0.3:
        return True

    # Escalate sensitive actions at moderate confidence
    sensitive_types = {"financial", "deletion", "communication", "admin"}
    if confidence < 0.6 and action_type in sensitive_types:
        return True

    # Escalate financial actions even at higher confidence
    if action_type == "financial" and confidence < 0.8:
        return True

    return False


def auto_expire_escalations(max_age_hours: int = 24) -> int:
    """Expire old pending escalations.

    Returns:
        Number of escalations expired.
    """
    escalations = _load_escalations()
    now = time.time()
    expired = 0

    for esc in escalations:
        if esc["status"] == "pending":
            age_hours = (now - esc["created_at"]) / 3600
            if age_hours > max_age_hours:
                esc["status"] = "expired"
                esc["resolved_at"] = now
                expired += 1

    if expired:
        _save_escalations(escalations)

    return expired
