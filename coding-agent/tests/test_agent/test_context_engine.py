"""Tests for agent.context_engine module."""

import pytest

from coding_agent.agent.context import ContextManager, ConversationMessage
from coding_agent.agent.context_engine import ContextSlice, SmartContextEngine
from coding_agent.agent.error_recovery import ErrorTracker


@pytest.fixture
def context():
    return ContextManager(max_tokens=100_000)


@pytest.fixture
def error_tracker():
    return ErrorTracker()


@pytest.fixture
def engine(context, error_tracker):
    return SmartContextEngine(context, error_tracker)


class TestContextSlice:
    """Tests for ContextSlice dataclass."""

    def test_fields(self):
        s = ContextSlice(content="hello", priority=10, source="recent", token_estimate=5)
        assert s.content == "hello"
        assert s.priority == 10
        assert s.source == "recent"
        assert s.token_estimate == 5

    def test_default_token_estimate(self):
        s = ContextSlice(content="hello", priority=10, source="recent")
        assert s.token_estimate == 0


class TestSmartContextEngineRecord:
    """Tests for recording tool results and verification."""

    def test_record_tool_result(self, engine):
        engine.record_tool_result("read_file", "file content", success=True)
        assert len(engine._last_tool_results) == 1

    def test_record_tool_result_truncates(self, engine):
        long_result = "x" * 1000
        engine.record_tool_result("read_file", long_result, success=True)
        assert len(engine._last_tool_results[0]["result"]) == 500

    def test_record_tool_result_keeps_last_10(self, engine):
        for i in range(15):
            engine.record_tool_result(f"tool_{i}", f"result_{i}", success=True)
        assert len(engine._last_tool_results) == 10
        assert engine._last_tool_results[0]["name"] == "tool_5"

    def test_record_verification(self, engine):
        engine.record_verification("syntax", passed=True, message="OK")
        assert len(engine._verification_results) == 1

    def test_record_verification_keeps_last_5(self, engine):
        for i in range(8):
            engine.record_verification(f"check_{i}", passed=False, message=f"err_{i}")
        assert len(engine._verification_results) == 5
        assert engine._verification_results[0]["check_type"] == "check_3"

    def test_set_pending_tool_calls(self, engine):
        calls = [{"name": "edit_file", "args": {}}]
        engine.set_pending_tool_calls(calls)
        assert engine._pending_tool_calls == calls

    def test_clear_history(self, engine):
        engine.record_tool_result("t", "r", success=True)
        engine.record_verification("v", passed=False, message="m")
        engine.set_pending_tool_calls([{}])
        engine.clear_history()
        assert len(engine._last_tool_results) == 0
        assert len(engine._verification_results) == 0
        assert len(engine._pending_tool_calls) == 0


class TestSmartContextEngineSelect:
    """Tests for select_context method."""

    def test_empty_context(self, engine):
        slices = engine.select_context()
        assert len(slices) == 0

    def test_includes_recent_messages(self, engine, context):
        context.add_user_message("hello")
        context.add_assistant_message("hi there")
        slices = engine.select_context()
        assert len(slices) >= 1
        assert slices[0].source == "recent"

    def test_recent_messages_priority_highest(self, engine, context):
        context.add_user_message("hello")
        engine.record_tool_result("t", "r", success=True)
        slices = engine.select_context()
        assert slices[0].source == "recent"
        assert slices[0].priority == 100

    def test_tool_results_included(self, engine, context):
        context.add_user_message("hello")
        engine.record_tool_result("read_file", "content", success=True)
        slices = engine.select_context()
        sources = [s.source for s in slices]
        assert "recent" in sources
        assert "tool_result" in sources

    def test_error_context_included_on_failures(self, engine, context, error_tracker):
        context.add_user_message("hello")
        error_tracker.record_tool_call("edit_file", {}, success=False, error="err")
        error_tracker.record_tool_call("edit_file", {}, success=False, error="err")
        slices = engine.select_context(include_error_context=True)
        sources = [s.source for s in slices]
        assert "error" in sources

    def test_error_context_excluded_when_no_failures(self, engine, context, error_tracker):
        context.add_user_message("hello")
        error_tracker.record_tool_call("edit_file", {}, success=True)
        slices = engine.select_context(include_error_context=True)
        sources = [s.source for s in slices]
        assert "error" not in sources

    def test_verification_included_on_failures(self, engine, context):
        context.add_user_message("hello")
        engine.record_verification("syntax", passed=False, message="invalid")
        slices = engine.select_context(include_verification=True)
        sources = [s.source for s in slices]
        assert "verification" in sources

    def test_verification_excluded_when_all_pass(self, engine, context):
        context.add_user_message("hello")
        engine.record_verification("syntax", passed=True, message="ok")
        slices = engine.select_context(include_verification=True)
        sources = [s.source for s in slices]
        assert "verification" not in sources

    def test_plan_included_when_enabled(self, engine, context):
        context.add_user_message("hello")
        slices = engine.select_context(include_plan=True, plan_text="Step 1: do stuff")
        sources = [s.source for s in slices]
        assert "plan" in sources

    def test_plan_excluded_when_disabled(self, engine, context):
        context.add_user_message("hello")
        slices = engine.select_context(include_plan=False, plan_text="Step 1: do stuff")
        sources = [s.source for s in slices]
        assert "plan" not in sources

    def test_sorted_by_priority(self, engine, context):
        context.add_user_message("hello")
        engine.record_tool_result("t", "r", success=True)
        engine.record_verification("v", passed=False, message="err")
        slices = engine.select_context(include_plan=True, plan_text="plan")
        priorities = [s.priority for s in slices]
        assert priorities == sorted(priorities, reverse=True)

    def test_token_budget_respected(self, engine, context):
        context.add_user_message("hello")
        engine._max_context_tokens = 20  # very small budget
        slices = engine.select_context(
            include_error_context=True,
            include_verification=True,
            include_plan=True,
            plan_text="x" * 1000,
        )
        total = sum(s.token_estimate for s in slices)
        assert total <= 20


class TestSmartContextEngineFormat:
    """Tests for format_selected_context method."""

    def test_empty_slices(self, engine):
        result = engine.format_selected_context([])
        assert result == ""

    def test_single_slice(self, engine):
        slices = [ContextSlice(content="hello", priority=10, source="recent")]
        result = engine.format_selected_context(slices)
        assert "[RECENT]" in result
        assert "hello" in result

    def test_multiple_slices(self, engine):
        slices = [
            ContextSlice(content="hello", priority=10, source="recent"),
            ContextSlice(content="error msg", priority=5, source="error"),
        ]
        result = engine.format_selected_context(slices)
        assert "[RECENT]" in result
        assert "[ERROR]" in result

    def test_total_tokens(self, engine):
        slices = [
            ContextSlice(content="hello", priority=10, source="recent", token_estimate=5),
            ContextSlice(content="world", priority=5, source="error", token_estimate=3),
        ]
        assert engine.get_total_tokens(slices) == 8


class TestSmartContextEngineIntegration:
    """Integration tests with real context manager."""

    def test_full_flow(self, engine, context, error_tracker):
        # Add messages
        context.add_user_message("Fix the bug in main.py")
        context.add_assistant_message("I'll read the file first")
        context.add_user_message("ok go ahead")

        # Record tool results
        engine.record_tool_result("read_file", "def main(): pass", success=True)

        # Record errors
        error_tracker.record_tool_call("edit_file", {"path": "main.py"}, success=False, error="old_text not found")

        # Record verification
        engine.record_verification("syntax", passed=False, message="IndentationError on line 5")

        # Select context
        slices = engine.select_context(
            include_error_context=True,
            include_verification=True,
            include_plan=True,
            plan_text="Plan:\n1. Read file\n2. Fix bug\n3. Verify",
        )

        # Verify
        assert len(slices) >= 3
        sources = [s.source for s in slices]
        assert "recent" in sources
        assert "tool_result" in sources
        assert "error" in sources
        assert "verification" in sources
        assert "plan" in sources

        # Format
        formatted = engine.format_selected_context(slices)
        assert len(formatted) > 0

    def test_no_error_tracker(self, context):
        engine = SmartContextEngine(context, error_tracker=None)
        context.add_user_message("hello")
        slices = engine.select_context(include_error_context=True)
        sources = [s.source for s in slices]
        assert "error" not in sources
