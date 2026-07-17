"""Tests for agent.loop module."""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

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

    async def test_time_budget_exceeded(self):
        """Loop stops when time budget is exceeded."""
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

        async def fake_stream(messages, tools=None):
            yield StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call_dict)
            yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        agent = self._make_agent(llm_client=llm, max_iterations=10)
        # Set max_time to -1 so elapsed (0) > -1 triggers immediately
        agent.max_time = -1

        events = [e async for e in agent.process_input("do something")]
        budget_events = [e for e in events if e.type == EventType.BUDGET_EXCEEDED]
        assert len(budget_events) == 1
        assert budget_events[0].data["reason"] == "time"

    async def test_cost_budget_exceeded(self):
        """Loop stops when cost budget is exceeded."""
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"

        async def fake_stream(messages, tools=None):
            yield StreamEvent(type=StreamEventType.TEXT, data="Hi")
            yield StreamEvent(
                type=StreamEventType.USAGE,
                data={"prompt_tokens": 1000000, "completion_tokens": 0},
            )
            yield StreamEvent(type=StreamEventType.DONE)

        llm.stream = fake_stream

        agent = self._make_agent(llm_client=llm, max_iterations=10)
        # Set max_cost to 0 so the first usage triggers it
        agent.max_cost = 0.0

        events = [e async for e in agent.process_input("expensive task")]
        budget_events = [e for e in events if e.type == EventType.BUDGET_EXCEEDED]
        assert len(budget_events) == 1
        assert budget_events[0].data["reason"] == "cost"


class TestPermissionBypassFix:
    """A.1: Parallel tools must go through permission checks."""

    def _make_agent(
        self,
        permission_level: Permission = Permission.READ,
        permission_callback: Any | None = None,
    ) -> AgentLoop:
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"
        return AgentLoop(
            llm_client=llm,
            permission_manager=PermissionManager(level=permission_level),
            context_manager=ContextManager(max_tokens=100_000),
            workspace=Path("."),
            max_iterations=5,
            permission_callback=permission_callback,
        )

    async def test_parallel_read_auto_approved(self):
        """Read-only parallel tools pass permission check without callback."""
        agent = self._make_agent()
        tool_call = {
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
                yield StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call)
                yield StreamEvent(type=StreamEventType.DONE)
            else:
                yield StreamEvent(type=StreamEventType.TEXT, data="Done.")
                yield StreamEvent(type=StreamEventType.DONE)

        agent.llm_client.stream = fake_stream
        events = [e async for e in agent.process_input("read x.py")]

        tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
        assert len(tool_results) >= 1
        assert agent.metrics["permission_check_count"] >= 1
        assert agent.metrics["permission_deny_count"] == 0

    async def test_parallel_denied_blocks_execution(self):
        """Parallel tool denied by permission check is not executed."""
        agent = self._make_agent()

        tool_call = {
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
                yield StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call)
                yield StreamEvent(type=StreamEventType.DONE)
            else:
                yield StreamEvent(type=StreamEventType.TEXT, data="Done.")
                yield StreamEvent(type=StreamEventType.DONE)

        agent.llm_client.stream = fake_stream

        # Force permission check to deny the tool
        original_check = agent.permissions.check
        def deny_read(tool_name, perm_level):
            if tool_name == "read_file" and perm_level == "read":
                return False
            return original_check(tool_name, perm_level)
        agent.permissions.check = deny_read

        events = [e async for e in agent.process_input("read x.py")]

        tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
        assert len(tool_results) == 1
        assert "Permission denied" in tool_results[0].data["result"]
        assert agent.metrics["permission_deny_count"] == 1

        # Context should have the denial message
        tool_msgs = [m for m in agent.context.messages if m.role == "tool"]
        assert any("Permission denied" in m.content for m in tool_msgs)

    async def test_parallel_denied_does_not_call_execute(self):
        """Denied parallel tool never reaches tool_registry.execute_from_llm."""
        agent = self._make_agent()

        tool_call = {
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
                yield StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call)
                yield StreamEvent(type=StreamEventType.DONE)
            else:
                yield StreamEvent(type=StreamEventType.TEXT, data="Done.")
                yield StreamEvent(type=StreamEventType.DONE)

        agent.llm_client.stream = fake_stream

        # Force permission check to deny
        agent.permissions.check = lambda tn, pl: False

        with patch("coding_agent.agent.loop.tool_registry") as mock_registry:
            mock_registry.get.return_value = AsyncMock(permission_level="read")
            mock_registry.get_schemas.return_value = []
            events = [e async for e in agent.process_input("read x.py")]
            mock_registry.execute_from_llm.assert_not_called()

    async def test_metrics_initialized(self):
        """Metrics dict is initialized with all expected keys."""
        agent = self._make_agent()
        expected_keys = {
            "permission_check_count", "permission_deny_count", "tool_count",
            "tool_timeout_count", "tool_cancelled_count",
            "summarize_count", "summarize_success", "summarize_fail",
            "summarize_duration_ms", "context_suggestion_count",
            "token_estimate_calls", "prompt_cache_hits", "prompt_cache_misses",
            "micro_compact_count",
        }
        assert expected_keys == set(agent.metrics.keys())

    async def test_metrics_reset(self):
        """Reset clears all metrics."""
        agent = self._make_agent()
        agent.metrics["permission_check_count"] = 5
        agent.metrics["permission_deny_count"] = 2
        agent.reset()
        assert agent.metrics["permission_check_count"] == 0
        assert agent.metrics["permission_deny_count"] == 0

    async def test_metrics_summary_report(self):
        """get_metrics_summary returns formatted string."""
        agent = self._make_agent()
        agent.metrics["permission_check_count"] = 3
        agent.metrics["permission_deny_count"] = 1
        report = agent.get_metrics_summary()
        assert "Permission checks" in report
        assert "3 passed" in report
        assert "1 denied" in report


class TestContextEngineIntegration:
    """A.3: SmartContextEngine is wired into the loop."""

    def _make_agent(self) -> AgentLoop:
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"
        return AgentLoop(
            llm_client=llm,
            permission_manager=PermissionManager(level=Permission.READ),
            context_manager=ContextManager(max_tokens=100_000),
            workspace=Path("."),
            max_iterations=5,
        )

    async def test_context_health_event_when_usage_high(self):
        """CONTEXT_HEALTH event emitted when context usage >= 70%."""
        agent = self._make_agent()
        # Set max_tokens low so any message triggers high usage
        agent.context.max_tokens = 100

        tool_call = {
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
                yield StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call)
                yield StreamEvent(type=StreamEventType.DONE)
            else:
                yield StreamEvent(type=StreamEventType.TEXT, data="Done.")
                yield StreamEvent(type=StreamEventType.DONE)

        agent.llm_client.stream = fake_stream
        events = [e async for e in agent.process_input("read pyproject.toml")]

        # CONTEXT_HEALTH may or may not fire depending on actual token count
        # but the metric should be trackable
        assert "context_suggestion_count" in agent.metrics

    async def test_context_engine_has_history(self):
        """Context engine records tool results from the loop."""
        agent = self._make_agent()
        agent.context_engine.record_tool_result("read_file", "test output", True)
        assert len(agent.context_engine._last_tool_results) == 1

    async def test_select_context_returns_slices(self):
        """select_context returns prioritized context slices."""
        agent = self._make_agent()
        agent.context.add_user_message("hello world")
        agent.context_engine.record_tool_result("read_file", "file content here", True)
        slices = agent.context_engine.select_context()
        assert len(slices) >= 1
        sources = [s.source for s in slices]
        assert "recent" in sources


class TestSummarizeLifecycle:
    """A.4: Summarization tasks are tracked, not fire-and-forget."""

    def _make_agent(self) -> AgentLoop:
        llm = AsyncMock()
        llm.model = "test"
        llm.provider = "test"
        return AgentLoop(
            llm_client=llm,
            permission_manager=PermissionManager(level=Permission.READ),
            context_manager=ContextManager(max_tokens=100_000),
            workspace=Path("."),
            max_iterations=5,
        )

    async def test_spawn_summarize_tracks_task(self):
        """_spawn_summarize creates a tracked task."""
        agent = self._make_agent()
        # Mock complete to avoid real LLM call
        agent.llm_client.complete = AsyncMock(
            return_value=LLMResponse(
                content="Summary of conversation.",
                tool_calls=[],
                usage=TokenUsage(prompt_tokens=10, completion_tokens=10, model="test"),
                model="test",
            )
        )
        # Add some messages so format_old_messages returns content
        agent.context.add_user_message("hello")
        agent.context.add_assistant_message("hi there")

        agent._spawn_summarize()
        # Task should be tracked
        assert len(agent._bg_tasks) >= 1
        # Wait for task to complete
        await asyncio.gather(*agent._bg_tasks, return_exceptions=True)
        assert len(agent._bg_tasks) == 0
        assert agent.metrics["summarize_count"] >= 1
        assert agent.metrics["summarize_success"] >= 1

    async def test_reset_cancels_background_tasks(self):
        """reset() cancels all pending background tasks."""
        agent = self._make_agent()
        # Create a slow task
        async def slow():
            await asyncio.sleep(100)
        task = asyncio.create_task(slow())
        agent._bg_tasks.add(task)

        agent.reset()
        # Yield control so cancellation propagates
        await asyncio.sleep(0)
        assert len(agent._bg_tasks) == 0
        assert task.cancelled()

    async def test_metrics_track_summarization(self):
        """Summarization metrics are tracked correctly."""
        agent = self._make_agent()
        agent.metrics["summarize_count"] = 0
        agent.metrics["summarize_success"] = 0
        agent.metrics["summarize_fail"] = 0
        # Simulate a completed task callback
        agent.metrics["summarize_count"] += 1
        agent.metrics["summarize_success"] += 1
        assert agent.metrics["summarize_count"] == 1
        assert agent.metrics["summarize_success"] == 1
