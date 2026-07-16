"""Tests for reactive compact (Phase A.4)."""

from __future__ import annotations

import pytest

from coding_agent.agent.context import ContextManager, ConversationMessage
from coding_agent.agent.loop import _is_context_overflow_error


class TestContextOverflowDetection:
    """Test the _is_context_overflow_error function."""

    def test_prompt_too_long(self) -> None:
        exc = Exception("prompt_too_long: max tokens exceeded")
        assert _is_context_overflow_error(exc)

    def test_context_length_exceeded(self) -> None:
        exc = Exception("context_length_exceeded")
        assert _is_context_overflow_error(exc)

    def test_maximum_context_length(self) -> None:
        exc = Exception("maximum context length exceeded")
        assert _is_context_overflow_error(exc)

    def test_context_window(self) -> None:
        exc = Exception("context window too small")
        assert _is_context_overflow_error(exc)

    def test_token_limit(self) -> None:
        exc = Exception("token limit exceeded")
        assert _is_context_overflow_error(exc)

    def test_http_400(self) -> None:
        exc = Exception("HTTP 400 Bad Request")
        assert _is_context_overflow_error(exc)

    def test_not_overflow(self) -> None:
        exc = Exception("rate limit exceeded")
        assert not _is_context_overflow_error(exc)

    def test_empty_message(self) -> None:
        exc = Exception("")
        assert not _is_context_overflow_error(exc)


class TestDropOldestToolResults:
    """Test the drop_oldest_tool_results method."""

    def test_drop_tool_results(self) -> None:
        ctx = ContextManager()
        ctx.messages = [
            ConversationMessage(role="user", content="Hello"),
            ConversationMessage(role="assistant", content="Hi", tool_calls=[{"id": "1"}]),
            ConversationMessage(role="tool", content="result1", tool_call_id="1", name="test"),
            ConversationMessage(role="assistant", content="Done", tool_calls=[{"id": "2"}]),
            ConversationMessage(role="tool", content="result2", tool_call_id="2", name="test"),
        ]

        dropped = ctx.drop_oldest_tool_results(count=1)

        assert dropped == 1
        assert len(ctx.messages) == 4
        # First tool result should be dropped, second one remains
        tool_messages = [m for m in ctx.messages if m.role == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "result2"

    def test_drop_multiple(self) -> None:
        ctx = ContextManager()
        ctx.messages = [
            ConversationMessage(role="user", content="Hello"),
            ConversationMessage(role="tool", content="result1", tool_call_id="1", name="test"),
            ConversationMessage(role="tool", content="result2", tool_call_id="2", name="test"),
            ConversationMessage(role="tool", content="result3", tool_call_id="3", name="test"),
        ]

        dropped = ctx.drop_oldest_tool_results(count=2)

        assert dropped == 2
        assert len(ctx.messages) == 2
        assert ctx.messages[0].role == "user"
        assert ctx.messages[1].content == "result3"

    def test_no_tool_results(self) -> None:
        ctx = ContextManager()
        ctx.messages = [
            ConversationMessage(role="user", content="Hello"),
            ConversationMessage(role="assistant", content="Hi"),
        ]

        dropped = ctx.drop_oldest_tool_results(count=2)

        assert dropped == 0
        assert len(ctx.messages) == 2

    def test_preserve_non_tool_messages(self) -> None:
        ctx = ContextManager()
        ctx.messages = [
            ConversationMessage(role="user", content="Hello"),
            ConversationMessage(role="assistant", content="Hi"),
            ConversationMessage(role="tool", content="result", tool_call_id="1", name="test"),
            ConversationMessage(role="user", content="Thanks"),
        ]

        dropped = ctx.drop_oldest_tool_results(count=1)

        assert dropped == 1
        assert len(ctx.messages) == 3
        # User and assistant messages should be preserved
        assert ctx.messages[0].role == "user"
        assert ctx.messages[1].role == "assistant"
        assert ctx.messages[2].role == "user"


class TestReactiveCompactEvent:
    """Test REACTIVE_COMPACT event type exists."""

    def test_event_type_exists(self) -> None:
        from coding_agent.agent.events import EventType
        assert hasattr(EventType, "REACTIVE_COMPACT")
        assert EventType.REACTIVE_COMPACT.value == "reactive_compact"
