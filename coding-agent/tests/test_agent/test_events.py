"""Tests for agent.events module."""

from coding_agent.agent.events import AgentEvent, EventType


class TestEventType:
    def test_all_types_exist(self):
        expected = {
            "text",
            "tool_start",
            "tool_result",
            "loop_start",
            "perm_req",
            "perm_check",
            "perm_res",
            "usage",
            "done",
            "error",
            "max_iter",
            "budget_exceeded",
            "plan_update",
            "verification",
            "stuck_detected",
            "ask_user",
            "context_health",
            "reflection",
            "max_tokens_recovery",
            "reactive_compact",
            "micro_compact",
            "undo_push",
            "sibling_abort",
            "hook_block",
            "hook_output",
            "perm_mode_changed",
            "subagent_started",
            "subagent_tool_start",
            "subagent_tool_result",
            "subagent_completed",
            "plan_mode_entered",
            "plan_mode_exited",
        }
        actual = {e.value for e in EventType}
        assert actual == expected

    def test_enum_members(self):
        assert EventType.TEXT.value == "text"
        assert EventType.TOOL_START.value == "tool_start"
        assert EventType.DONE.value == "done"


class TestAgentEvent:
    def test_create_text_event(self):
        evt = AgentEvent(type=EventType.TEXT, data="hello")
        assert evt.type == EventType.TEXT
        assert evt.data == "hello"

    def test_create_event_no_data(self):
        evt = AgentEvent(type=EventType.DONE)
        assert evt.type == EventType.DONE
        assert evt.data is None

    def test_create_tool_start_event(self):
        evt = AgentEvent(
            type=EventType.TOOL_START,
            data={"name": "read_file", "args": {"path": "main.py"}},
        )
        assert evt.type == EventType.TOOL_START
        assert evt.data["name"] == "read_file"
