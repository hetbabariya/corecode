"""Planning system — structured task decomposition for the agent loop.

The planner lets the LLM create explicit step-by-step plans before executing,
track progress, and detect when replanning is needed after failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from coding_agent.logging import logger


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class PlanStatus(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlanStep:
    """A single step in a plan."""

    description: str
    status: StepStatus = StepStatus.PENDING
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    result: str = ""


@dataclass
class Plan:
    """A structured plan for a multi-step task."""

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    current_step: int = 0
    status: PlanStatus = PlanStatus.PLANNING

    @property
    def active_step(self) -> PlanStep | None:
        """Return the first non-done step, or None if all steps are done."""
        for i, step in enumerate(self.steps):
            if step.status not in (StepStatus.DONE,):
                return step
        return None

    @property
    def completed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.DONE]

    @property
    def failed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    @property
    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "status": self.status.value,
            "current_step": self.current_step,
            "total_steps": len(self.steps),
            "completed": len(self.completed_steps),
            "failed": len(self.failed_steps),
            "steps": [
                {
                    "index": i,
                    "description": s.description,
                    "status": s.status.value,
                    "result": s.result,
                }
                for i, s in enumerate(self.steps)
            ],
        }


class PlanManager:
    """Manages a plan's lifecycle: creation, step tracking, and replanning.

    Usage::

        manager = PlanManager()

        # LLM calls create_plan tool
        plan = manager.create_plan(
            goal="Fix the login bug",
            steps=["Read auth.py", "Find the bug", "Fix it", "Verify"],
        )

        # Agent works through steps
        manager.start_step(0)        # mark step 0 in progress
        manager.complete_step(0, "Found issue in line 42")
        manager.start_step(1)
        manager.complete_step(1, "Added null check")
        ...
    """

    def __init__(self) -> None:
        self._plan: Plan | None = None

    @property
    def plan(self) -> Plan | None:
        return self._plan

    @property
    def has_plan(self) -> bool:
        return self._plan is not None

    def create_plan(self, goal: str, steps: list[str]) -> Plan:
        """Create a new plan, replacing any existing one."""
        plan_steps = [PlanStep(description=desc) for desc in steps]
        self._plan = Plan(
            goal=goal,
            steps=plan_steps,
            status=PlanStatus.EXECUTING,
        )
        logger.info("plan_created", goal=goal, steps=len(steps))
        return self._plan

    def start_step(self, index: int) -> PlanStep:
        """Mark a step as in-progress. Returns the step."""
        if self._plan is None:
            raise ValueError("No active plan")
        if index < 0 or index >= len(self._plan.steps):
            raise IndexError(f"Step index {index} out of range (0-{len(self._plan.steps) - 1})")

        # Mark all previous steps as done if they're still pending
        for i in range(index):
            step = self._plan.steps[i]
            if step.status == StepStatus.PENDING:
                step.status = StepStatus.DONE
                step.result = "Skipped"

        step = self._plan.steps[index]
        step.status = StepStatus.IN_PROGRESS
        self._plan.current_step = index
        return step

    def complete_step(self, index: int, result: str = "") -> PlanStep:
        """Mark a step as done. Returns the step."""
        if self._plan is None:
            raise ValueError("No active plan")
        step = self._plan.steps[index]
        step.status = StepStatus.DONE
        step.result = result

        # Check if plan is complete
        if all(s.status in (StepStatus.DONE, StepStatus.IN_PROGRESS) for s in self._plan.steps):
            if all(s.status == StepStatus.DONE for s in self._plan.steps):
                self._plan.status = PlanStatus.COMPLETED
                logger.info("plan_completed", goal=self._plan.goal, steps=len(self._plan.steps))
            else:
                logger.debug(
                    "plan_step_completed",
                    step=index,
                    description=step.description,
                    completed=len(self._plan.completed_steps),
                    total=len(self._plan.steps),
                )

        return step

    def fail_step(self, index: int, result: str = "") -> PlanStep:
        """Mark a step as failed. Returns the step."""
        if self._plan is None:
            raise ValueError("No active plan")
        step = self._plan.steps[index]
        step.status = StepStatus.FAILED
        step.result = result
        logger.warning("plan_step_failed", step=index, description=step.description, result=result[:200])
        return step

    def needs_replan(self) -> bool:
        """Return True if the current step has failed and replanning is needed."""
        if self._plan is None:
            return False
        active = self._plan.active_step
        return active is not None and active.status == StepStatus.FAILED

    def get_next_step_index(self) -> int | None:
        """Return the index of the next pending step, or None if none left."""
        if self._plan is None:
            return None
        for i, step in enumerate(self._plan.steps):
            if step.status == StepStatus.PENDING:
                return i
        return None

    def is_complete(self) -> bool:
        """Return True if all steps are done."""
        if self._plan is None:
            return False
        return all(s.status == StepStatus.DONE for s in self._plan.steps)

    def to_prompt(self) -> str:
        """Serialize the current plan for injection into the system prompt."""
        if self._plan is None:
            return ""

        lines = [f"## Current Plan: {self._plan.goal}", ""]

        for i, step in enumerate(self._plan.steps):
            status_icon = {
                StepStatus.PENDING: "[ ]",
                StepStatus.IN_PROGRESS: "[>]",
                StepStatus.DONE: "[x]",
                StepStatus.FAILED: "[!]",
            }[step.status]

            line = f"{i + 1}. {status_icon} {step.description}"
            if step.result:
                line += f" — {step.result}"
            lines.append(line)

        lines.append("")
        lines.append(f"Progress: {len(self._plan.completed_steps)}/{len(self._plan.steps)} steps done")
        if self._plan.failed_steps:
            lines.append(f"Failed: {len(self._plan.failed_steps)} steps")
        lines.append(f"Status: {self._plan.status.value}")

        return "\n".join(lines)

    def add_tool_call(self, step_index: int, tool_call: dict[str, Any]) -> None:
        """Record a tool call on a specific step."""
        if self._plan is None:
            raise ValueError("No active plan")
        self._plan.steps[step_index].tool_calls.append(tool_call)

    def reset(self) -> None:
        """Clear the plan."""
        self._plan = None
