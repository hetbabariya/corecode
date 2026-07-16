"""Tests for agent.context module."""

from coding_agent.agent.context import ContextManager, ConversationMessage


class TestConversationMessage:
    def test_to_dict_basic(self):
        msg = ConversationMessage(role="user", content="hello")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "hello"}

    def test_to_dict_with_tool_calls(self):
        tc = [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ]
        msg = ConversationMessage(role="assistant", content="", tool_calls=tc)
        d = msg.to_dict()
        assert d["tool_calls"] == tc

    def test_to_dict_tool_result(self):
        msg = ConversationMessage(
            role="tool", content="file data", tool_call_id="c1", name="read_file"
        )
        d = msg.to_dict()
        assert d["tool_call_id"] == "c1"
        assert d["name"] == "read_file"

    def test_to_dict_no_optional_fields(self):
        msg = ConversationMessage(role="assistant", content="ok")
        d = msg.to_dict()
        assert "tool_calls" not in d
        assert "tool_call_id" not in d
        assert "name" not in d


class TestContextManager:
    def test_build_messages_empty(self):
        ctx = ContextManager()
        msgs = ctx.build_messages()
        assert msgs == []

    def test_build_messages_with_system_prompt(self):
        ctx = ContextManager()
        ctx.system_prompt = "You are a coding agent."
        msgs = ctx.build_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are a coding agent."

    def test_add_user_message(self):
        ctx = ContextManager()
        ctx.add_user_message("Fix the bug")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "user"
        assert ctx.messages[0].content == "Fix the bug"

    def test_add_assistant_message(self):
        ctx = ContextManager()
        ctx.add_assistant_message("I'll read the file")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "assistant"

    def test_add_assistant_with_tool_calls(self):
        ctx = ContextManager()
        tc = [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ]
        ctx.add_assistant_message("", tool_calls=tc)
        assert ctx.messages[0].tool_calls == tc

    def test_add_tool_result(self):
        ctx = ContextManager()
        ctx.add_tool_result("c1", "read_file", "file contents here")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "tool"
        assert ctx.messages[0].tool_call_id == "c1"
        assert ctx.messages[0].name == "read_file"
        assert ctx.messages[0].content == "file contents here"

    def test_full_conversation_flow(self):
        ctx = ContextManager()
        ctx.system_prompt = "You are a coding agent."
        ctx.add_user_message("Read main.py")
        ctx.add_assistant_message(
            "",
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"main.py"}',
                    },
                }
            ],
        )
        ctx.add_tool_result("c1", "read_file", "def main(): ...")
        ctx.add_assistant_message("The file defines a main function.")

        msgs = ctx.build_messages()
        roles = [m["role"] for m in msgs]
        assert roles == ["system", "user", "assistant", "tool", "assistant"]

    def test_estimate_tokens(self):
        ctx = ContextManager()
        ctx.add_user_message("Hello world")
        tokens = ctx.estimate_tokens()
        assert tokens > 0

    def test_needs_summarization_false_initially(self):
        ctx = ContextManager(max_tokens=100_000)
        ctx.add_user_message("Hi")
        assert ctx.needs_summarization() is False

    def test_needs_summarization_true_when_full(self):
        ctx = ContextManager(max_tokens=10)
        ctx.add_user_message("x" * 200)
        assert ctx.needs_summarization() is True

    def test_summarize_old_messages_keeps_recent(self):
        ctx = ContextManager()
        for i in range(10):
            ctx.add_user_message(f"message {i}")
        ctx.summarize_old_messages("Summary of first 5 messages.")
        assert len(ctx.messages) == 5
        assert ctx.messages[0].content == "message 5"
        assert ctx.messages[-1].content == "message 9"
        assert ctx._summary == "Summary of first 5 messages."

    def test_summarize_noop_when_few_messages(self):
        ctx = ContextManager()
        ctx.add_user_message("msg1")
        ctx.add_user_message("msg2")
        ctx.summarize_old_messages("summary")
        assert len(ctx.messages) == 2

    def test_clear(self):
        ctx = ContextManager()
        ctx.system_prompt = "test"
        ctx.add_user_message("hello")
        ctx._summary = "old summary"
        ctx.clear()
        assert ctx.messages == []
        assert ctx._summary == ""
        assert ctx.system_prompt == "test"

    def test_project_context_in_build(self):
        ctx = ContextManager()
        ctx.project_context = "Project: FastAPI"
        ctx.system_prompt = "You are a coding agent."
        msgs = ctx.build_messages()
        assert len(msgs) == 2
        assert msgs[1]["content"] == "Project: FastAPI"

    def test_summary_in_build(self):
        ctx = ContextManager()
        ctx.system_prompt = "You are a coding agent."
        # Need >5 messages to trigger summarization
        ctx.add_user_message("hello")
        ctx.add_assistant_message("hi")
        ctx.add_user_message("bye")
        ctx.add_assistant_message("goodbye")
        ctx.add_user_message("one more")
        ctx.add_assistant_message("response 6")
        ctx.summarize_old_messages("Earlier conversation about greetings.")
        msgs = ctx.build_messages()
        # system + summary + 5 recent
        assert len(msgs) == 7
        assert "Summary of previous conversation" in msgs[1]["content"]

    def test_format_old_messages_empty_when_few(self):
        ctx = ContextManager()
        ctx.add_user_message("msg1")
        assert ctx.format_old_messages() == ""

    def test_format_old_messages_returns_readable_string(self):
        ctx = ContextManager()
        for i in range(8):
            ctx.add_user_message(f"message {i}")
        result = ctx.format_old_messages()
        assert "message 0" in result
        assert "message 2" in result
        assert "message 7" not in result

    def test_format_old_messages_includes_tool_calls(self):
        ctx = ContextManager()
        for i in range(6):
            ctx.add_user_message(f"msg {i}")
        tc = [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ]
        ctx.add_assistant_message("", tool_calls=tc)
        for i in range(5):
            ctx.add_user_message(f"msg after {i}")
        result = ctx.format_old_messages()
        assert "read_file" in result

    def test_format_old_messages_skips_system(self):
        ctx = ContextManager()
        ctx.system_prompt = "System prompt"
        for i in range(6):
            ctx.add_user_message(f"msg {i}")
        result = ctx.format_old_messages()
        assert "System prompt" not in result


class TestMicroCompact:
    """Tests for compact_old_tool_results method."""

    def test_no_compact_when_few_messages(self):
        ctx = ContextManager()
        ctx.add_user_message("hello")
        ctx.add_tool_result("c1", "read_file", "x" * 600)
        compacted = ctx.compact_old_tool_results(keep_recent=10)
        assert compacted == 0
        # Tool result should be preserved (not compacted)
        tool_msg = [m for m in ctx.messages if m.role == "tool"][0]
        assert len(tool_msg.content) > 500

    def test_compact_old_tool_results(self):
        ctx = ContextManager()
        # Add 15 messages with tool results
        for i in range(15):
            ctx.add_user_message(f"msg {i}")
            ctx.add_tool_result(f"c{i}", "read_file", "x" * 600)

        compacted = ctx.compact_old_tool_results(keep_recent=10)
        assert compacted > 0
        # Old tool results should be compacted
        tool_msgs = [m for m in ctx.messages if m.role == "tool"]
        assert "[Old tool result:" in tool_msgs[0].content
        # Recent tool results should be preserved
        assert len(tool_msgs[-1].content) > 500

    def test_compact_preserves_metadata(self):
        ctx = ContextManager()
        for i in range(15):
            ctx.add_user_message(f"msg {i}")
            ctx.add_tool_result(f"c{i}", "read_file", "line1\nline2\n" + "x" * 600)

        ctx.compact_old_tool_results(keep_recent=10)
        tool_msgs = [m for m in ctx.messages if m.role == "tool"]
        compacted_msg = tool_msgs[0]
        assert "read_file" in compacted_msg.content
        assert "ok" in compacted_msg.content
        assert "lines" in compacted_msg.content

    def test_compact_failed_tool_result(self):
        ctx = ContextManager()
        for i in range(15):
            ctx.add_user_message(f"msg {i}")
            ctx.add_tool_result(f"c{i}", "read_file", "Error: file not found" + "x" * 600)

        ctx.compact_old_tool_results(keep_recent=10)
        tool_msgs = [m for m in ctx.messages if m.role == "tool"]
        # Failed results should show "failed"
        assert "failed" in tool_msgs[0].content

    def test_compact_skips_small_results(self):
        ctx = ContextManager()
        for i in range(15):
            ctx.add_user_message(f"msg {i}")
            ctx.add_tool_result(f"c{i}", "read_file", "small content")

        compacted = ctx.compact_old_tool_results(keep_recent=10)
        assert compacted == 0

    def test_compact_preserves_non_tool_messages(self):
        ctx = ContextManager()
        for i in range(15):
            ctx.add_user_message(f"msg {i}")
            if i % 2 == 0:
                ctx.add_tool_result(f"c{i}", "read_file", "x" * 600)

        ctx.compact_old_tool_results(keep_recent=10)
        # User messages should be preserved
        user_msgs = [m for m in ctx.messages if m.role == "user"]
        assert user_msgs[0].content == "msg 0"

    def test_micro_compact_event_type_exists(self):
        from coding_agent.agent.events import EventType
        assert hasattr(EventType, "MICRO_COMPACT")
        assert EventType.MICRO_COMPACT.value == "micro_compact"
