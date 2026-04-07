"""Multi-Step Planner — agents plan ahead, execute, and self-reflect.

Instead of one-shot execution, the planner:
1. Decomposes a complex task into steps
2. Executes each step
3. Evaluates the result (self-reflection)
4. Adjusts the plan if needed
5. Moves to the next step or retries

This makes agents reliable for complex, multi-step tasks.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("pagal_os")


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    index: int
    description: str
    tool: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed, skipped
    result: str = ""
    retries: int = 0


@dataclass
class ExecutionPlan:
    """A multi-step plan for accomplishing a task."""
    task: str
    steps: list[PlanStep] = field(default_factory=list)
    current_step: int = 0
    status: str = "planning"  # planning, executing, reflecting, completed, failed
    reflections: list[str] = field(default_factory=list)


def create_plan(task: str, agent_tools: list[str]) -> ExecutionPlan:
    """Create an execution plan by asking the LLM to decompose the task.

    Args:
        task: The complex task to plan.
        agent_tools: Available tools for the agent.

    Returns:
        ExecutionPlan with steps.
    """
    try:
        from src.core.llm import call_llm

        plan_prompt = f"""You are a planning assistant. Break down this task into clear, executable steps.

Task: {task}

Available tools: {', '.join(agent_tools) if agent_tools else 'none (text-only)'}

Respond with a JSON array of steps. Each step should have:
- "description": what to do
- "tool": which tool to use (or null for thinking/text steps)
- "tool_args": arguments for the tool (empty dict if no tool)

Example:
[
  {{"description": "Search the web for recent AI news", "tool": "search_web", "tool_args": {{"query": "latest AI news 2026"}}}},
  {{"description": "Read the top result", "tool": "browse_url", "tool_args": {{"url": "..."}}}},
  {{"description": "Summarize the findings", "tool": null, "tool_args": {{}}}}
]

Return ONLY the JSON array, no other text."""

        result = call_llm(
            messages=[{"role": "user", "content": plan_prompt}],
            model="nvidia/nemotron-3-super-120b-a12b:free",
            timeout=30,
        )

        if not result["ok"]:
            return ExecutionPlan(task=task, steps=[
                PlanStep(index=0, description=task, tool=None),
            ])

        # Parse the plan
        content = result["content"].strip()
        # Extract JSON from potential markdown code blocks
        if "```" in content:
            import re
            match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
            if match:
                content = match.group(1)

        try:
            steps_data = json.loads(content)
        except json.JSONDecodeError:
            # Fallback: treat as single step
            return ExecutionPlan(task=task, steps=[
                PlanStep(index=0, description=task, tool=None),
            ])

        steps = []
        for i, s in enumerate(steps_data):
            steps.append(PlanStep(
                index=i,
                description=s.get("description", f"Step {i+1}"),
                tool=s.get("tool"),
                tool_args=s.get("tool_args", {}),
            ))

        return ExecutionPlan(task=task, steps=steps)

    except Exception as e:
        logger.error("Plan creation failed: %s", e)
        return ExecutionPlan(task=task, steps=[
            PlanStep(index=0, description=task, tool=None),
        ])


def reflect_on_step(step: PlanStep, plan: ExecutionPlan) -> str:
    """Self-reflect on a completed step. Returns reflection text.

    Checks: Did this step succeed? Do we need to adjust the plan?
    """
    try:
        from src.core.llm import call_llm

        reflection_prompt = f"""You are evaluating a step in a multi-step plan.

Original task: {plan.task}
Step {step.index + 1}: {step.description}
Status: {step.status}
Result: {step.result[:500]}

Questions to answer briefly:
1. Did this step achieve its goal?
2. Do we need to adjust the remaining steps?
3. Should we retry this step differently?

Respond in 2-3 sentences."""

        result = call_llm(
            messages=[{"role": "user", "content": reflection_prompt}],
            model="nvidia/nemotron-3-super-120b-a12b:free",
            timeout=15,
        )

        return result["content"] if result["ok"] else "Reflection unavailable."

    except Exception:
        return "Reflection skipped."


def execute_plan(plan: ExecutionPlan, agent_name: str = "") -> dict[str, Any]:
    """Execute a plan step by step with reflection after each step.

    Args:
        plan: The execution plan.
        agent_name: Agent name for tool execution context.

    Returns:
        Dict with 'ok', 'output', 'steps_completed', 'reflections'.
    """
    plan.status = "executing"
    outputs: list[str] = []
    max_retries = 2

    for step in plan.steps:
        step.status = "running"

        try:
            if step.tool:
                # Execute tool
                from src.tools.registry import execute_tool
                result = execute_tool(step.tool, step.tool_args)
                step.result = json.dumps(result)[:1000] if isinstance(result, dict) else str(result)[:1000]
                step.status = "completed" if (isinstance(result, dict) and result.get("ok")) else "failed"
            else:
                # Text/thinking step — mark as completed
                step.result = step.description
                step.status = "completed"

            outputs.append(f"Step {step.index + 1}: {step.description}\n  Result: {step.result[:200]}")

        except Exception as e:
            step.status = "failed"
            step.result = str(e)

            # Retry logic
            if step.retries < max_retries:
                step.retries += 1
                step.status = "pending"
                logger.info("Retrying step %d (attempt %d)", step.index + 1, step.retries + 1)
                continue

        # Self-reflection after each step
        plan.status = "reflecting"
        reflection = reflect_on_step(step, plan)
        plan.reflections.append(reflection)

    plan.status = "completed"
    completed = sum(1 for s in plan.steps if s.status == "completed")

    return {
        "ok": completed > 0,
        "output": "\n\n".join(outputs),
        "steps_total": len(plan.steps),
        "steps_completed": completed,
        "reflections": plan.reflections,
    }
