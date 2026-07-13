"""Tests for agent.loop module."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from coding_agent.agent.context import ContextManager
from coding_agent.agent.events import EventType
from coding_agent.agent.loop import AgentLoop
from coding_agent.agent.permissions import Permission, PermissionManager
from coding_agent.llm.client import LLMResponse
from coding_agent.llm.streaming import StreamEvent, StreamEventType
from coding_agent.llm.tokens import TokenUsage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fake_stream(events: list[StreamEvent]) -> Any:
    """Fake async iterator for LLM stream events."""
    for e in events:
        yield e


def _make_llm_response(
    content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=10, model="test"),
        model="test",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentLoop:
    """Tests for the core agentic loop."""

    def _make_agent(
        self,
        llm_client: Any | None = None,
        workspace: Path | None = None,
        max_iterations: int = 5,
    ) -> AgentLoop:
        if llm_client is None:
            llm_client = AsyncMock()
            llm_client.model = "test-model"
            llm_client.provider = "test"
            llm_client.stream = AsyncMock(return_value=_fake_stream([]))

        return AgentLoop(
            llm_client=llm_client,
            permission_manager=PermissionManager(level=Permission.READ),
            context_manager=ContextManager(max_tokens=100_000),
            workspace=workspace or Path("."),
            max_iterations=max_iterations,
        )

    async def test_simple_text_response(self):
        """LLM returns text with no tool calls → yields TEXT then DONE."""
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"

        async def fake_stream(messages, tools=None):
            yield StreamEvent(type=StreamEventType.TEXT, data="Hello!")
            yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        agent = self._make_agent(llm_client=llm)
        events = [e async for e in agent.process_input("Hi")]

        types = [e.type for e in events]
        assert EventType.TEXT in types
        assert EventType.DONE in types

    async def test_tool_call_execution(self):
        """LLM requests a tool call → agent executes it and feeds result back."""
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"

        tool_call_dict = {
            "id": "call_0",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "pyproject.toml"}),
            },
        }

        call_count = 0

        async def fake_stream(messages, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: return tool call
                yield StreamEvent(
                    type=StreamEventType.TEXT, data="Let me read the file."
                )
                yield StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call_dict)
                yield StreamEvent(type=StreamEventType.DONE)
            else:
                # Second call: return text only (task done)
                yield StreamEvent(
                    type=StreamEventType.TEXT, data="The file has the bug."
                )
                yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        agent = self._make_agent(llm_client=llm)
        events = [e async for e in agent.process_input("Read pyproject.toml")]

        types = [e.type for e in events]
        assert EventType.TOOL_START in types
        assert EventType.TOOL_RESULT in types
        assert EventType.DONE in types

        # Verify tool result was added to context
        tool_msgs = [m for m in agent.context.messages if m.role == "tool"]
        assert len(tool_msgs) == 1

    async def test_permission_request(self):
        """Write tool triggers permission request event."""
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"

        tool_call_dict = {
            "id": "call_0",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "test.py", "content": "print('hi')"}),
            },
        }

        call_count = 0

        async def fake_stream(messages, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call_dict)
                yield StreamEvent(type=StreamEventType.DONE)
            else:
                yield StreamEvent(type=StreamEventType.TEXT, data="Done.")
                yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        agent = self._make_agent(llm_client=llm)
        events = [e async for e in agent.process_input("Create test.py")]

        perm_events = [e for e in events if e.type == EventType.PERMISSION_REQUEST]
        assert len(perm_events) == 1
        assert perm_events[0].data["tool_name"] == "write_file"

    async def test_max_iterations(self):
        """Loop stops after max_iterations."""
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"

        # Always return a tool call → loop keeps going
        tool_call_dict = {
            "id": "call_0",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "x.py"}),
            },
        }

        async def fake_stream(messages, tools=None):
            yield StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call_dict)
            yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        agent = self._make_agent(llm_client=llm, max_iterations=2)
        events = [e async for e in agent.process_input("do something")]

        assert events[-1].type == EventType.MAX_ITERATIONS

    async def test_context_receives_all_messages(self):
        """After a full tool-call cycle, context has user, assistant, tool messages."""
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"

        tool_call_dict = {
            "id": "call_0",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "x.py"}),
            },
        }

        call_count = 0

        async def fake_stream(messages, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call_dict)
                yield StreamEvent(type=StreamEventType.DONE)
            else:
                yield StreamEvent(type=StreamEventType.TEXT, data="Done.")
                yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        agent = self._make_agent(llm_client=llm)
        _ = [e async for e in agent.process_input("read x.py")]

        roles = [m.role for m in agent.context.messages]
        assert "user" in roles
        assert "assistant" in roles
        assert "tool" in roles

    async def test_system_prompt_set(self):
        """Agent loop sets the system prompt from workspace."""
        agent = self._make_agent(workspace=Path("."))
        assert agent.context.system_prompt != ""
        assert "coding agent" in agent.context.system_prompt.lower()

    async def test_reset(self):
        """Reset clears context and permissions."""
        agent = self._make_agent()
        agent.context.add_user_message("hello")
        agent.permissions.approve_tool("write_file")

        agent.reset()

        assert len(agent.context.messages) == 0
        assert agent.permissions.check("write_file", "write") is False
