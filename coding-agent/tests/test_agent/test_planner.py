"""Tests for agent.planner module."""

import pytest

from coding_agent.agent.planner import Plan, PlanManager, PlanStatus, PlanStep, StepStatus


class TestPlanStep:
    """Tests for PlanStep dataclass."""

    def test_default_status_is_pending(self):
        step = PlanStep(description="Read the file")
        assert step.status == StepStatus.PENDING
        assert step.tool_calls == []
        assert step.result == ""

    def test_custom_status(self):
        step = PlanStep(description="Fix bug", status=StepStatus.DONE)
        assert step.status == StepStatus.DONE


class TestPlan:
    """Tests for Plan dataclass."""

    def test_active_step_returns_first_pending(self):
        plan = Plan(
            goal="Fix bug",
            steps=[
                PlanStep(description="Read", status=StepStatus.DONE),
                PlanStep(description="Fix", status=StepStatus.IN_PROGRESS),
                PlanStep(description="Verify", status=StepStatus.PENDING),
            ],
            current_step=1,
        )
        assert plan.active_step is not None
        assert plan.active_step.description == "Fix"

    def test_active_step_none_when_all_done(self):
        plan = Plan(
            goal="Done",
            steps=[PlanStep(description="Step 1", status=StepStatus.DONE)],
        )
        assert plan.active_step is None

    def test_completed_steps(self):
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(description="A", status=StepStatus.DONE),
                PlanStep(description="B", status=StepStatus.PENDING),
                PlanStep(description="C", status=StepStatus.DONE),
            ],
        )
        assert len(plan.completed_steps) == 2

    def test_failed_steps(self):
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(description="A", status=StepStatus.FAILED),
                PlanStep(description="B", status=StepStatus.DONE),
            ],
        )
        assert len(plan.failed_steps) == 1

    def test_pending_steps(self):
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(description="A", status=StepStatus.DONE),
                PlanStep(description="B", status=StepStatus.PENDING),
                PlanStep(description="C", status=StepStatus.PENDING),
            ],
        )
        assert len(plan.pending_steps) == 2

    def test_to_dict(self):
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(description="A", status=StepStatus.DONE, result="Found it"),
                PlanStep(description="B", status=StepStatus.PENDING),
            ],
            current_step=1,
            status=PlanStatus.EXECUTING,
        )
        d = plan.to_dict()
        assert d["goal"] == "Test"
        assert d["status"] == "executing"
        assert d["total_steps"] == 2
        assert d["completed"] == 1
        assert d["steps"][0]["result"] == "Found it"


class TestPlanManager:
    """Tests for PlanManager class."""

    def test_initial_state(self):
        m = PlanManager()
        assert m.plan is None
        assert m.has_plan is False

    def test_create_plan(self):
        m = PlanManager()
        plan = m.create_plan("Fix bug", ["Read", "Fix", "Verify"])
        assert plan.goal == "Fix bug"
        assert len(plan.steps) == 3
        assert plan.status == PlanStatus.EXECUTING
        assert m.has_plan is True

    def test_create_plan_replaces_existing(self):
        m = PlanManager()
        m.create_plan("First", ["A"])
        plan2 = m.create_plan("Second", ["B", "C"])
        assert plan2.goal == "Second"
        assert len(plan2.steps) == 2

    def test_start_step(self):
        m = PlanManager()
        m.create_plan("Test", ["A", "B", "C"])
        step = m.start_step(1)
        assert step.status == StepStatus.IN_PROGRESS
        # Previous pending steps are marked done
        assert m.plan.steps[0].status == StepStatus.DONE
        assert m.plan.steps[0].result == "Skipped"

    def test_start_step_already_done_keeps_status(self):
        m = PlanManager()
        m.create_plan("Test", ["A", "B"])
        m.complete_step(0, "Done manually")
        m.start_step(1)
        assert m.plan.steps[0].status == StepStatus.DONE
        assert m.plan.steps[0].result == "Done manually"

    def test_start_step_out_of_range(self):
        m = PlanManager()
        m.create_plan("Test", ["A"])
        with pytest.raises(IndexError):
            m.start_step(5)

    def test_start_step_no_plan(self):
        m = PlanManager()
        with pytest.raises(ValueError):
            m.start_step(0)

    def test_complete_step(self):
        m = PlanManager()
        m.create_plan("Test", ["A", "B"])
        m.start_step(0)
        step = m.complete_step(0, "Found it")
        assert step.status == StepStatus.DONE
        assert step.result == "Found it"

    def test_complete_step_marks_plan_completed(self):
        m = PlanManager()
        m.create_plan("Test", ["A"])
        m.start_step(0)
        m.complete_step(0)
        assert m.plan.status == PlanStatus.COMPLETED

    def test_fail_step(self):
        m = PlanManager()
        m.create_plan("Test", ["A", "B"])
        m.start_step(0)
        step = m.fail_step(0, "Error occurred")
        assert step.status == StepStatus.FAILED
        assert step.result == "Error occurred"

    def test_needs_replan(self):
        m = PlanManager()
        m.create_plan("Test", ["A", "B"])
        m.start_step(0)
        assert m.needs_replan() is False
        m.fail_step(0, "Failed")
        assert m.needs_replan() is True

    def test_needs_replan_no_plan(self):
        m = PlanManager()
        assert m.needs_replan() is False

    def test_get_next_step_index(self):
        m = PlanManager()
        m.create_plan("Test", ["A", "B", "C"])
        m.start_step(0)
        m.complete_step(0)
        assert m.get_next_step_index() == 1

    def test_get_next_step_index_none_when_all_done(self):
        m = PlanManager()
        m.create_plan("Test", ["A"])
        m.start_step(0)
        m.complete_step(0)
        assert m.get_next_step_index() is None

    def test_is_complete(self):
        m = PlanManager()
        m.create_plan("Test", ["A", "B"])
        assert m.is_complete() is False
        m.start_step(0)
        m.complete_step(0)
        assert m.is_complete() is False
        m.start_step(1)
        m.complete_step(1)
        assert m.is_complete() is True

    def test_is_complete_no_plan(self):
        m = PlanManager()
        assert m.is_complete() is False

    def test_to_prompt(self):
        m = PlanManager()
        m.create_plan("Fix login", ["Read auth.py", "Find bug", "Fix it"])
        m.start_step(0)
        m.complete_step(0, "Read successfully")
        m.start_step(1)
        prompt = m.to_prompt()
        assert "Fix login" in prompt
        assert "Read auth.py" in prompt
        assert "[x]" in prompt
        assert "[>]" in prompt
        assert "1/3 steps done" in prompt

    def test_to_prompt_no_plan(self):
        m = PlanManager()
        assert m.to_prompt() == ""

    def test_add_tool_call(self):
        m = PlanManager()
        m.create_plan("Test", ["A"])
        m.start_step(0)
        m.add_tool_call(0, {"name": "read_file", "args": {"path": "x.py"}})
        assert len(m.plan.steps[0].tool_calls) == 1

    def test_add_tool_call_no_plan(self):
        m = PlanManager()
        with pytest.raises(ValueError):
            m.add_tool_call(0, {})

    def test_reset(self):
        m = PlanManager()
        m.create_plan("Test", ["A"])
        m.reset()
        assert m.plan is None
        assert m.has_plan is False

    def test_start_step_out_of_range_negative(self):
        m = PlanManager()
        m.create_plan("Test", ["A"])
        with pytest.raises(IndexError):
            m.start_step(-1)
