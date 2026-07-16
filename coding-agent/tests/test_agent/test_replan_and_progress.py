"""Tests for Phase B.2 (Auto-replanning) and B.4 (Progress evaluation)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from coding_agent.agent.planner import Plan, PlanManager, PlanStep, PlanStatus, StepStatus


class TestPlanManagerReplacePlan:
    def test_replace_plan(self) -> None:
        pm = PlanManager()
        pm.create_plan("old goal", ["step 1", "step 2"])
        assert pm.plan is not None
        assert pm.plan.goal == "old goal"

        new_plan = Plan(
            goal="new goal",
            steps=[PlanStep(description="new step")],
            status=PlanStatus.EXECUTING,
        )
        pm.replace_plan(new_plan)
        assert pm.plan is not None
        assert pm.plan.goal == "new goal"
        assert len(pm.plan.steps) == 1

    def test_replace_plan_logs(self) -> None:
        pm = PlanManager()
        pm.create_plan("old", ["s1"])
        new = Plan(goal="new", steps=[PlanStep(description="s2")])
        pm.replace_plan(new)
        assert pm.plan.goal == "new"


class TestAutoReplanning:
    """Test the auto-replanning logic in loop.py via _parse_plan_response."""

    def test_parse_valid_json(self, tmp_path: Path) -> None:
        from coding_agent.agent.loop import AgentLoop

        loop = AgentLoop.__new__(AgentLoop)
        content = json.dumps({
            "goal": "Fix the bug",
            "steps": ["Read file", "Find issue", "Fix it"],
        })
        plan = loop._parse_plan_response(content)
        assert plan is not None
        assert plan.goal == "Fix the bug"
        assert len(plan.steps) == 3
        assert plan.steps[0].description == "Read file"

    def test_parse_json_in_markdown(self, tmp_path: Path) -> None:
        from coding_agent.agent.loop import AgentLoop

        loop = AgentLoop.__new__(AgentLoop)
        content = '```json\n{"goal": "Test", "steps": ["a", "b"]}\n```'
        plan = loop._parse_plan_response(content)
        assert plan is not None
        assert plan.goal == "Test"
        assert len(plan.steps) == 2

    def test_parse_empty_steps_returns_none(self, tmp_path: Path) -> None:
        from coding_agent.agent.loop import AgentLoop

        loop = AgentLoop.__new__(AgentLoop)
        content = json.dumps({"goal": "Test", "steps": []})
        plan = loop._parse_plan_response(content)
        assert plan is None

    def test_parse_invalid_json_returns_none(self, tmp_path: Path) -> None:
        from coding_agent.agent.loop import AgentLoop

        loop = AgentLoop.__new__(AgentLoop)
        plan = loop._parse_plan_response("not json at all")
        assert plan is None

    def test_parse_garbage_content_returns_none(self, tmp_path: Path) -> None:
        from coding_agent.agent.loop import AgentLoop

        loop = AgentLoop.__new__(AgentLoop)
        plan = loop._parse_plan_response("```yaml\nfoo: bar\n```")
        assert plan is None


class TestProgressEvaluation:
    """Test the progress evaluation logic."""

    def _make_loop_with_plan(
        self, completed: int, failed: int, total: int
    ) -> object:
        from coding_agent.agent.loop import AgentLoop

        loop = AgentLoop.__new__(AgentLoop)
        loop.plan_manager = PlanManager()
        steps = [f"step {i}" for i in range(total)]
        loop.plan_manager.create_plan("test goal", steps)

        for i in range(completed):
            loop.plan_manager.start_step(i)
            loop.plan_manager.complete_step(i, "done")
        for i in range(completed, completed + failed):
            loop.plan_manager.start_step(i)
            loop.plan_manager.fail_step(i, "failed")

        loop._tool_count = completed + failed
        loop._accumulated_cost = 0.05
        loop._start_time = 0.0
        loop.error_tracker = MagicMock()
        loop.error_tracker.is_stuck.return_value = False
        return loop

    def test_progress_all_done(self) -> None:
        loop = self._make_loop_with_plan(completed=3, failed=0, total=3)
        progress = loop._evaluate_progress()
        assert progress["completed"] == 3
        assert progress["failed"] == 0
        assert progress["total"] == 3
        assert progress["progress_ratio"] == 1.0
        assert progress["is_stalled"] is False

    def test_progress_partial(self) -> None:
        loop = self._make_loop_with_plan(completed=1, failed=1, total=4)
        progress = loop._evaluate_progress()
        assert progress["completed"] == 1
        assert progress["failed"] == 1
        assert progress["total"] == 4
        assert progress["progress_ratio"] == 0.25

    def test_progress_stalled(self) -> None:
        loop = self._make_loop_with_plan(completed=0, failed=2, total=3)
        loop._tool_count = 5
        loop.error_tracker.is_stuck.return_value = True
        progress = loop._evaluate_progress()
        assert progress["is_stalled"] is True

    def test_progress_no_plan(self) -> None:
        from coding_agent.agent.loop import AgentLoop

        loop = AgentLoop.__new__(AgentLoop)
        loop.plan_manager = PlanManager()
        loop._tool_count = 2
        loop._accumulated_cost = 0.01
        loop._start_time = 0.0
        loop.error_tracker = MagicMock()
        loop.error_tracker.is_stuck.return_value = False
        progress = loop._evaluate_progress()
        assert progress["completed"] == 0
        assert progress["total"] == 0
        assert progress["progress_ratio"] == 0.0
