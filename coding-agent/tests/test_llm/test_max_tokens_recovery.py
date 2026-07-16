"""Tests for max tokens recovery (Phase A.3)."""

from __future__ import annotations

import pytest

from coding_agent.llm.streaming import StreamParser, StreamEventType
from coding_agent.llm.client import _normalize_stop_reason


class TestNormalizeStopReason:
    """Test the _normalize_stop_reason function."""

    def test_length_to_max_tokens(self) -> None:
        assert _normalize_stop_reason("length") == "max_tokens"

    def test_max_tokens_to_max_tokens(self) -> None:
        assert _normalize_stop_reason("MAX_TOKENS") == "max_tokens"

    def test_stop(self) -> None:
        assert _normalize_stop_reason("stop") == "stop"

    def test_empty(self) -> None:
        assert _normalize_stop_reason("") == ""

    def test_unknown(self) -> None:
        assert _normalize_stop_reason("unknown_reason") == "unknown_reason"

    def test_case_insensitive(self) -> None:
        assert _normalize_stop_reason("LENGTH") == "max_tokens"
        assert _normalize_stop_reason("Stop") == "stop"


class TestStreamParserStopReason:
    """Test that StreamParser emits STOP_REASON event."""

    def test_stop_reason_emitted(self) -> None:
        parser = StreamParser()
        chunk = {
            "choices": [{
                "delta": {"content": "Hello"},
                "finish_reason": "length"
            }]
        }
        events = parser.feed(chunk)
        
        # Should have TEXT, STOP_REASON, and DONE events
        event_types = [e.type for e in events]
        assert StreamEventType.TEXT in event_types
        assert StreamEventType.STOP_REASON in event_types
        assert StreamEventType.DONE in event_types

    def test_stop_reason_data(self) -> None:
        parser = StreamParser()
        chunk = {
            "choices": [{
                "delta": {},
                "finish_reason": "length"
            }]
        }
        events = parser.feed(chunk)
        
        stop_reason_events = [e for e in events if e.type == StreamEventType.STOP_REASON]
        assert len(stop_reason_events) == 1
        assert stop_reason_events[0].data == {"finish_reason": "length"}

    def test_no_stop_reason_when_no_finish(self) -> None:
        parser = StreamParser()
        chunk = {
            "choices": [{
                "delta": {"content": "Hello"},
                "finish_reason": None
            }]
        }
        events = parser.feed(chunk)
        
        event_types = [e.type for e in events]
        assert StreamEventType.STOP_REASON not in event_types

    def test_stop_reason_with_tool_calls(self) -> None:
        parser = StreamParser()
        # First chunk with tool call (complete arguments)
        chunk1 = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "test", "arguments": "{}"}
                    }]
                },
                "finish_reason": None
            }]
        }
        events1 = parser.feed(chunk1)
        
        # Tool call should be emitted in first chunk
        event_types1 = [e.type for e in events1]
        assert StreamEventType.TOOL_CALL in event_types1
        
        # Second chunk with finish_reason
        chunk2 = {
            "choices": [{
                "delta": {},
                "finish_reason": "length"
            }]
        }
        events2 = parser.feed(chunk2)
        
        # Should have STOP_REASON and DONE (tool call already emitted)
        event_types2 = [e.type for e in events2]
        assert StreamEventType.STOP_REASON in event_types2
        assert StreamEventType.DONE in event_types2
