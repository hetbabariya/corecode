"""Tests for subagent delegation (C.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coding_agent.agent.context import ContextManager
from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.loop import AgentLoop
from coding_agent.agent.permissions import Permission, PermissionManager
from coding_agent.agent.subagent import SubAgent, _create_filtered_registry
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import ToolRegistry, tool_registry
from coding_agent.tools.subagent import (
    delegate_task,
    set_parent_loop,
    set_semaphore,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fake_stream(events: list) -> Any:
    """Fake async iterator for LLM stream events."""
    for e in events:
        yield e


def _make_agent(
    llm_client: Any | None = None,
    workspace: Path | None = None,
    max_iterations: int = 5,
    depth: int = 0,
    tool_reg: ToolRegistry | None = None,
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
        tool_registry=tool_reg,
        depth=depth,
    )


# ---------------------------------------------------------------------------
# FilteredRegistry tests
# ---------------------------------------------------------------------------


class TestFilteredRegistry:
    def test_none_returns_source(self):
        source = ToolRegistry(name="source")
        result = _create_filtered_registry(None, source)
        assert result is source

    def test_filters_to_allowed_tools(self):
        source = ToolRegistry(name="source")
        read_tool = MagicMock()
        read_tool.name = "read_file"
        write_tool = MagicMock()
        write_tool.name = "write_file"
        source.register(read_tool)
        source.register(write_tool)

        filtered = _create_filtered_registry(["read_file"], source)
        assert filtered.list_tools() == ["read_file"]

    def test_raises_on_missing_tool(self):
        source = ToolRegistry(name="source")
        with pytest.raises(KeyError):
            _create_filtered_registry(["nonexistent"], source)

    def test_empty_list_creates_empty_registry(self):
        source = ToolRegistry(name="source")
        mock_tool = MagicMock()
        mock_tool.name = "read_file"
        source.register(mock_tool)
        filtered = _create_filtered_registry([], source)
        assert filtered.list_tools() == []


# ---------------------------------------------------------------------------
# SubAgent tests
# ---------------------------------------------------------------------------


class TestSubAgent:
    def test_creates_fresh_context(self):
        parent = _make_agent()
        sub = SubAgent(parent_loop=parent, prompt="test")
        assert sub._context is not parent.context
        assert len(sub._context.messages) == 0

    def test_tool_filtering(self):
        parent = _make_agent()
        sub = SubAgent(
            parent_loop=parent,
            prompt="test",
            allowed_tools=["read_file", "list_files"],
        )
        tool_names = sub._tool_registry.list_tools()
        assert "read_file" in tool_names
        assert "list_files" in tool_names
        assert "write_file" not in tool_names

    def test_read_only_permissions(self):
        parent = _make_agent()
        sub = SubAgent(parent_loop=parent, prompt="test")
        assert sub._permissions.level == Permission.READ

    def test_depth_tracking(self):
        parent = _make_agent(depth=0)
        sub = SubAgent(parent_loop=parent, prompt="test", depth=1)
        assert sub._depth == 1


# ---------------------------------------------------------------------------
# delegate_task tool tests
# ---------------------------------------------------------------------------


class TestDelegateTask:
    def test_tool_schema(self):
        schema = tool_registry.get_schema("delegate_task")
        assert schema["function"]["name"] == "delegate_task"
        params = schema["function"]["parameters"]
        assert "properties" in params
        assert "prompt" in params["properties"]
        assert "tools" in params["properties"]
        assert "max_iterations" in params["properties"]

    def test_no_parent_loop_returns_error(self):
        set_parent_loop(None)
        result = asyncio.get_event_loop().run_until_complete(
            delegate_task.__wrapped__(prompt="test")
        )
        assert not result.success
        assert "not initialized" in result.error

    def test_depth_limit_enforced(self):
        parent = _make_agent(depth=1)
        set_parent_loop(parent)
        set_semaphore(asyncio.Semaphore(3))

        result = asyncio.get_event_loop().run_until_complete(
            delegate_task.__wrapped__(prompt="test")
        )
        assert not result.success
        assert "depth limit" in result.error

    async def test_successful_delegation(self):
        from coding_agent.llm.streaming import StreamEvent, StreamEventType

        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"

        async def fake_stream(messages, tools=None):
            yield StreamEvent(type=StreamEventType.TEXT, data="subagent result")
            yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        parent = _make_agent(llm_client=llm, depth=0)
        set_parent_loop(parent)
        set_semaphore(asyncio.Semaphore(3))

        result = await delegate_task.__wrapped__(prompt="do something")
        assert result.success
        assert "subagent result" in result.output

    async def test_subagent_isolation(self):
        from coding_agent.llm.streaming import StreamEvent, StreamEventType

        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"

        async def fake_stream(messages, tools=None):
            yield StreamEvent(type=StreamEventType.TEXT, data="done")
            yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        parent = _make_agent(llm_client=llm, depth=0)
        parent.context.add_user_message("parent message")
        set_parent_loop(parent)
        set_semaphore(asyncio.Semaphore(3))

        result = await delegate_task.__wrapped__(prompt="test isolation")
        # Parent context should still have only the original message
        user_msgs = [
            m for m in parent.context.messages if m.role == "user"
        ]
        assert len(user_msgs) == 1

    async def test_event_queue_in_metadata(self):
        """Verify the event queue is passed in ToolResult metadata for drain_events."""
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"

        async def fake_stream(messages, tools=None):
            yield StreamEvent(type=StreamEventType.TEXT, data="result")
            yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        parent = _make_agent(llm_client=llm, depth=0)
        set_parent_loop(parent)
        set_semaphore(asyncio.Semaphore(3))

        result = await delegate_task.__wrapped__(prompt="queue test")
        assert result.success
        # Queue reference should be in metadata
        assert result.metadata is not None
        queue = result.metadata.get("_subagent_event_queue")
        assert queue is not None

        # Queue should contain SUBAGENT_STARTED and SUBAGENT_COMPLETED
        events = []
        while not queue.empty():
            ev = queue.get_nowait()
            if ev is not None:
                events.append(ev)
        types = [e.type for e in events]
        assert EventType.SUBAGENT_STARTED in types
        assert EventType.SUBAGENT_COMPLETED in types

    async def test_drain_events_with_explicit_queue(self):
        """Verify drain_events works with an explicitly passed queue."""
        import asyncio as _asyncio
        from coding_agent.tools.subagent import drain_events

        q: _asyncio.Queue = _asyncio.Queue()
        await q.put(AgentEvent(type=EventType.TEXT, data="hello"))
        await q.put(None)  # sentinel

        collected = [e async for e in drain_events(q)]
        assert len(collected) == 1
        assert collected[0].data == "hello"
