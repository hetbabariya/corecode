"""Tests for agent.error_recovery module."""

from coding_agent.agent.error_recovery import (
    ErrorCategory,
    ErrorTracker,
    RetryStrategy,
    ToolCallRecord,
)


class TestErrorTrackerRecord:
    """Tests for recording tool calls."""

    def test_record_successful_call(self):
        tracker = ErrorTracker()
        tracker.record_tool_call("read_file", {"path": "x.py"}, success=True)
        assert len(tracker.get_history()) == 1
        assert tracker.get_history()[0].success is True

    def test_record_failed_call(self):
        tracker = ErrorTracker()
        tracker.record_tool_call("edit_file", {"path": "x.py"}, success=False, error="File not found")
        assert len(tracker.get_history()) == 1
        assert tracker.get_history()[0].success is False
        assert tracker.get_history()[0].error == "File not found"

    def test_record_resets_consecutive_on_success(self):
        tracker = ErrorTracker()
        tracker.record_tool_call("edit_file", {}, success=False, error="err")
        tracker.record_tool_call("edit_file", {}, success=False, error="err")
        tracker.record_tool_call("edit_file", {}, success=True)
        assert "edit_file" not in tracker.get_consecutive_errors()

    def test_record_tracks_consecutive_errors(self):
        tracker = ErrorTracker()
        tracker.record_tool_call("edit_file", {}, success=False, error="err")
        tracker.record_tool_call("edit_file", {}, success=False, error="err")
        assert tracker.get_consecutive_errors()["edit_file"] == 2


class TestErrorTrackerStuck:
    """Tests for stuck detection."""

    def test_not_stuck_with_few_calls(self):
        tracker = ErrorTracker(stuck_threshold=3)
        tracker.record_tool_call("edit_file", {"path": "x.py"}, success=False, error="err")
        assert tracker.is_stuck() is False

    def test_stuck_same_tool_same_args(self):
        tracker = ErrorTracker(stuck_threshold=3)
        args = {"path": "x.py", "old_text": "a", "new_text": "b"}
        for _ in range(3):
            tracker.record_tool_call("edit_file", args, success=False, error="not found")
        assert tracker.is_stuck() is True

    def test_not_stuck_different_args(self):
        tracker = ErrorTracker(stuck_threshold=3)
        for i in range(3):
            tracker.record_tool_call("edit_file", {"path": f"x{i}.py"}, success=False, error=f"error {i}")
        assert tracker.is_stuck() is False

    def test_stuck_same_error_same_tool(self):
        tracker = ErrorTracker(stuck_threshold=3)
        for i in range(3):
            tracker.record_tool_call("edit_file", {"path": f"x{i}.py"}, success=False, error="same error")
        assert tracker.is_stuck() is True

    def test_not_stuck_different_errors(self):
        tracker = ErrorTracker(stuck_threshold=3)
        tracker.record_tool_call("edit_file", {"path": "a.py"}, success=False, error="error 1")
        tracker.record_tool_call("edit_file", {"path": "b.py"}, success=False, error="error 2")
        tracker.record_tool_call("edit_file", {"path": "c.py"}, success=False, error="error 3")
        assert tracker.is_stuck() is False

    def test_not_stuck_with_successes(self):
        tracker = ErrorTracker(stuck_threshold=3)
        tracker.record_tool_call("edit_file", {"path": "a.py"}, success=False, error="err")
        tracker.record_tool_call("edit_file", {"path": "b.py"}, success=True)
        tracker.record_tool_call("edit_file", {"path": "c.py"}, success=False, error="err")
        assert tracker.is_stuck() is False


class TestErrorTrackerStrategy:
    """Tests for strategy suggestions."""

    def test_suggest_retry_for_transient(self):
        tracker = ErrorTracker()
        tracker.record_tool_call("execute_command", {}, success=False, error="rate limit 429")
        strategy = tracker.suggest_strategy()
        assert strategy == RetryStrategy.RETRY

    def test_suggest_alternative_for_permanent(self):
        tracker = ErrorTracker()
        tracker.record_tool_call("read_file", {}, success=False, error="File not found: x.py")
        strategy = tracker.suggest_strategy()
        assert strategy == RetryStrategy.ALTERNATIVE

    def test_suggest_replan_for_logic(self):
        tracker = ErrorTracker()
        tracker.record_tool_call("edit_file", {}, success=False, error="old_text not found in file")
        strategy = tracker.suggest_strategy()
        assert strategy == RetryStrategy.REPLAN

    def test_suggest_ask_user_when_stuck_too_long(self):
        tracker = ErrorTracker(stuck_threshold=2)
        args = {"path": "x.py"}
        # Round 1: stuck → ALTERNATIVE (error classified as unknown)
        for _ in range(2):
            tracker.record_tool_call("edit_file", args, success=False, error="err")
        assert tracker.is_stuck() is True
        strategy = tracker.suggest_strategy()
        assert strategy == RetryStrategy.ALTERNATIVE
        # Round 2: stuck → REPLAN
        for _ in range(2):
            tracker.record_tool_call("edit_file", args, success=False, error="err")
        assert tracker.is_stuck() is True
        strategy = tracker.suggest_strategy()
        assert strategy == RetryStrategy.REPLAN
        # Round 3: stuck → ASK_USER
        for _ in range(2):
            tracker.record_tool_call("edit_file", args, success=False, error="err")
        assert tracker.is_stuck() is True
        strategy = tracker.suggest_strategy()
        assert strategy == RetryStrategy.ASK_USER


class TestErrorTrackerCategorize:
    """Tests for error categorization."""

    def test_transient_rate_limit(self):
        tracker = ErrorTracker()
        assert tracker.categorize_error("Rate limit exceeded") == ErrorCategory.TRANSIENT

    def test_transient_timeout(self):
        tracker = ErrorTracker()
        assert tracker.categorize_error("Request timed out") == ErrorCategory.TRANSIENT

    def test_permanent_not_found(self):
        tracker = ErrorTracker()
        assert tracker.categorize_error("File not found") == ErrorCategory.PERMANENT

    def test_permanent_permission(self):
        tracker = ErrorTracker()
        assert tracker.categorize_error("Permission denied") == ErrorCategory.PERMANENT

    def test_logic_not_found_in(self):
        tracker = ErrorTracker()
        assert tracker.categorize_error("old_text not found in x.py") == ErrorCategory.LOGIC

    def test_logic_multiple_matches(self):
        tracker = ErrorTracker()
        assert tracker.categorize_error("old_text appears 3 times") == ErrorCategory.LOGIC

    def test_unknown_error(self):
        tracker = ErrorTracker()
        assert tracker.categorize_error("something weird happened") == ErrorCategory.UNKNOWN


class TestErrorTrackerMessage:
    """Tests for stuck messages."""

    def test_stuck_message_includes_tool_name(self):
        tracker = ErrorTracker(stuck_threshold=2)
        args = {"path": "x.py"}
        for _ in range(2):
            tracker.record_tool_call("edit_file", args, success=False, error="err")
        msg = tracker.get_stuck_message()
        assert "edit_file" in msg

    def test_stuck_message_emphasizes_on_third(self):
        tracker = ErrorTracker(stuck_threshold=2)
        args = {"path": "x.py"}
        for _ in range(2):
            tracker.record_tool_call("edit_file", args, success=False, error="err")
        # First two calls → "different approach"
        msg1 = tracker.get_stuck_message()
        assert "different approach" in msg1.lower()
        msg2 = tracker.get_stuck_message()
        assert "different approach" in msg2.lower()
        # Third call → "completely different"
        msg3 = tracker.get_stuck_message()
        assert "completely different" in msg3.lower()


class TestErrorTrackerReset:
    """Tests for reset."""

    def test_reset_clears_all(self):
        tracker = ErrorTracker()
        tracker.record_tool_call("edit_file", {}, success=False, error="err")
        tracker.record_tool_call("edit_file", {}, success=False, error="err")
        tracker.reset()
        assert len(tracker.get_history()) == 0
        assert tracker.get_consecutive_errors() == {}


class TestErrorTrackerSummary:
    """Tests for summary output."""

    def test_summary_empty(self):
        tracker = ErrorTracker()
        assert "No tool calls" in tracker.get_summary()

    def test_summary_with_calls(self):
        tracker = ErrorTracker()
        tracker.record_tool_call("read_file", {}, success=True)
        tracker.record_tool_call("edit_file", {}, success=False, error="err")
        summary = tracker.get_summary()
        assert "read_file" in summary
        assert "edit_file" in summary
        assert "FAILED" in summary


class TestToolCallRecord:
    """Tests for ToolCallRecord dataclass."""

    def test_record_fields(self):
        r = ToolCallRecord(
            name="read_file",
            args_hash="abc123",
            success=True,
            error="",
            timestamp=1.0,
        )
        assert r.name == "read_file"
        assert r.success is True
