"""Planning tools: create_plan and update_plan.

These tools let the LLM create structured step-by-step plans and
track progress as it works through a task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool

if TYPE_CHECKING:
    from coding_agent.agent.planner import PlanManager


# Module-level reference set by the agent loop on initialization.
# This avoids circular imports between tools and the agent loop.
_plan_manager: PlanManager | None = None


def set_plan_manager(manager: Any) -> None:
    """Set the global plan manager reference (called by AgentLoop)."""
    global _plan_manager
    _plan_manager = manager


def get_plan_manager() -> Any:
    """Return the current plan manager."""
    return _plan_manager


@tool(
    name="create_plan",
    description=(
        "Create a step-by-step plan before starting work. "
        "Use this for multi-step tasks to organize your approach. "
        "Break the task into clear, actionable steps."
    ),
    permission="read",
)
async def create_plan(goal: str, steps: list[str]) -> ToolResult:
    """Create a plan with a goal and list of steps.

    Parameters
    ----------
    goal:
        A concise description of what you want to accomplish.
    steps:
        An ordered list of step descriptions. Each step should be
        a single actionable item.
    """
    manager = get_plan_manager()
    if manager is None:
        logger.debug("create_plan_failed", reason="manager_not_available")
        return ToolResult(
            success=False,
            error="Planning system not available. This is an internal error.",
        )

    if not steps:
        return ToolResult(
            success=False,
            error="A plan must have at least one step.",
        )

    plan = manager.create_plan(goal=goal, steps=steps)

    step_list = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(steps))
    return ToolResult(
        success=True,
        output=(
            f"Plan created: {goal}\n"
            f"Steps ({len(steps)}):\n{step_list}\n\n"
            f"Use update_plan to mark steps as you complete them."
        ),
        metadata={"plan": plan.to_dict()},
    )


@tool(
    name="update_plan",
    description=(
        "Update the status of a plan step. Use this as you work through "
        "your plan to track progress. Set status to 'in_progress' when "
        "starting a step, 'done' when completed, or 'failed' if it didn't work."
    ),
    permission="read",
)
async def update_plan(
    step_index: int,
    status: str,
    result: str = "",
) -> ToolResult:
    """Update a plan step's status.

    Parameters
    ----------
    step_index:
        Zero-based index of the step to update.
    status:
        New status: "in_progress", "done", or "failed".
    result:
        Optional result description (e.g. what was found or why it failed).
    """
    manager = get_plan_manager()
    if manager is None:
        return ToolResult(
            success=False,
            error="Planning system not available. This is an internal error.",
        )

    if manager.plan is None:
        return ToolResult(
            success=False,
            error="No active plan. Use create_plan first.",
        )

    plan = manager.plan
    if step_index < 0 or step_index >= len(plan.steps):
        return ToolResult(
            success=False,
            error=f"Step index {step_index} out of range. Plan has {len(plan.steps)} steps (0-{len(plan.steps) - 1}).",
        )

    step = plan.steps[step_index]

    if status == "in_progress":
        step = manager.start_step(step_index)
    elif status == "done":
        step = manager.complete_step(step_index, result)
    elif status == "failed":
        step = manager.fail_step(step_index, result)
    else:
        return ToolResult(
            success=False,
            error=f"Invalid status '{status}'. Use: in_progress, done, or failed.",
        )

    output = f"Step {step_index + 1} ({step.description}): {status}"
    if result:
        output += f" — {result}"

    # Check plan completion
    if manager.is_complete():
        output += "\n\nAll steps complete! Plan finished."
    elif manager.needs_replan():
        output += "\n\nThis step failed. Consider replanning or trying a different approach."

    return ToolResult(
        success=True,
        output=output,
        metadata={"plan": plan.to_dict()},
    )
