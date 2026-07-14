"""Tests for agent.events module."""

from coding_agent.agent.events import AgentEvent, EventType


class TestEventType:
    def test_all_types_exist(self):
        expected = {
            "text",
            "tool_start",
            "tool_result",
            "perm_req",
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
