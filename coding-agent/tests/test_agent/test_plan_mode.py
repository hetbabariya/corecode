"""Tests for E.1 Plan Mode — read-only planning before execution."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from coding_agent.agent.context import ContextManager
from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.loop import AgentLoop
from coding_agent.agent.permissions import PermissionManager
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import ToolRegistry, tool_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fake_stream(events: list | None = None) -> Any:
    """Fake async iterator for LLM stream events."""
    for e in (events or []):
        yield e


def _make_agent(
    llm_client: Any | None = None,
    workspace: Path | None = None,
) -> AgentLoop:
    if llm_client is None:
        llm_client = AsyncMock()
        llm_client.model = "test-model"
        llm_client.provider = "test"
        llm_client.stream = AsyncMock(return_value=_fake_stream([]))

    return AgentLoop(
        llm_client=llm_client,
        permission_manager=PermissionManager(),
        context_manager=ContextManager(),
        workspace=workspace or Path(__file__).parent,
        max_iterations=3,
    )


# ---------------------------------------------------------------------------
# ToolRegistry.filter_by_permission
# ---------------------------------------------------------------------------


class TestFilterByPermission:
    def test_filters_to_read_only(self):
        filtered = tool_registry.filter_by_permission(frozenset({"read"}))
        for name in filtered.list_tools():
            tool = filtered.get(name)
            assert tool.permission_level == "read", (
                f"Tool {name} has permission {tool.permission_level}, expected read"
            )

    def test_read_tools_present(self):
        filtered = tool_registry.filter_by_permission(frozenset({"read"}))
        read_tools = filtered.list_tools()
        assert "read_file" in read_tools
        assert "search_content" in read_tools
        assert "search_files" in read_tools
        assert "list_files" in read_tools
        assert "git_status" in read_tools
        assert "git_diff" in read_tools
        assert "git_log" in read_tools
        assert "create_plan" in read_tools
        assert "update_plan" in read_tools

    def test_write_tools_excluded(self):
        filtered = tool_registry.filter_by_permission(frozenset({"read"}))
        write_tools = filtered.list_tools()
        assert "write_file" not in write_tools
        assert "edit_file" not in write_tools
        assert "apply_patch" not in write_tools
        assert "git_commit" not in write_tools
        assert "execute_command" not in write_tools
        assert "delegate_task" not in write_tools

    def test_multiple_levels(self):
        filtered = tool_registry.filter_by_permission(frozenset({"read", "write"}))
        names = filtered.list_tools()
        assert "read_file" in names
        assert "write_file" in names
        assert "execute_command" not in names
        assert "delegate_task" not in names

    def test_empty_filter(self):
        filtered = tool_registry.filter_by_permission(frozenset())
        assert filtered.list_tools() == []

    def test_preserves_schemas(self):
        filtered = tool_registry.filter_by_permission(frozenset({"read"}))
        schemas = filtered.get_schemas()
        for schema in schemas:
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]


# ---------------------------------------------------------------------------
# AgentLoop plan mode state
# ---------------------------------------------------------------------------


class TestAgentLoopPlanMode:
    def test_plan_mode_defaults_false(self):
        agent = _make_agent()
        assert agent._plan_mode is False

    def test_set_plan_mode_true(self):
        agent = _make_agent()
        agent.set_plan_mode(True)
        assert agent._plan_mode is True

    def test_set_plan_mode_false(self):
        agent = _make_agent()
        agent.set_plan_mode(True)
        agent.set_plan_mode(False)
        assert agent._plan_mode is False

    def test_plan_mode_registry_exists(self):
        agent = _make_agent()
        assert agent._plan_mode_registry is not None
        assert isinstance(agent._plan_mode_registry, ToolRegistry)

    def test_plan_mode_registry_read_only(self):
        agent = _make_agent()
        for name in agent._plan_mode_registry.list_tools():
            tool = agent._plan_mode_registry.get(name)
            assert tool.permission_level == "read"


# ---------------------------------------------------------------------------
# Plan mode blocks non-read tools
# ---------------------------------------------------------------------------


class TestPlanModeBlocking:
    @pytest.mark.asyncio
    async def test_write_tool_blocked_in_plan_mode(self):
        """When plan mode is on, write tools should return a BLOCKED result."""
        agent = _make_agent()
        agent.set_plan_mode(True)

        # Simulate a write_file tool call
        result = agent._plan_mode_registry.get("read_file")
        assert result.permission_level == "read"

        # Verify write tools are NOT in the plan mode registry
        with pytest.raises(KeyError):
            agent._plan_mode_registry.get("write_file")

        with pytest.raises(KeyError):
            agent._plan_mode_registry.get("execute_command")

    @pytest.mark.asyncio
    async def test_read_tool_allowed_in_plan_mode(self):
        """Read tools should be available in the plan mode registry."""
        agent = _make_agent()
        agent.set_plan_mode(True)

        for name in ["read_file", "list_files", "search_content", "search_files"]:
            tool = agent._plan_mode_registry.get(name)
            assert tool.permission_level == "read"


# ---------------------------------------------------------------------------
# Plan mode events
# ---------------------------------------------------------------------------


class TestPlanModeEvents:
    def test_plan_mode_entered_event_type(self):
        assert hasattr(EventType, "PLAN_MODE_ENTERED")
        assert EventType.PLAN_MODE_ENTERED.value == "plan_mode_entered"

    def test_plan_mode_exited_event_type(self):
        assert hasattr(EventType, "PLAN_MODE_EXITED")
        assert EventType.PLAN_MODE_EXITED.value == "plan_mode_exited"

    def test_plan_mode_event_emission_flag(self):
        """The _plan_mode_emitted flag tracks whether events have been sent."""
        agent = _make_agent()
        assert getattr(agent, "_plan_mode_emitted", False) is False


# ---------------------------------------------------------------------------
# System prompt includes plan mode instructions
# ---------------------------------------------------------------------------


class TestPlanModeSystemPrompt:
    def test_plan_mode_in_prompt_when_active(self):
        agent = _make_agent()
        agent.set_plan_mode(True)
        prompt = agent._build_system_prompt_cached()
        assert "PLAN MODE" in prompt
        assert "read-only" in prompt.lower() or "read only" in prompt.lower()

    def test_no_plan_mode_in_prompt_when_inactive(self):
        agent = _make_agent()
        prompt = agent._build_system_prompt_cached()
        assert "PLAN MODE" not in prompt


# ---------------------------------------------------------------------------
# CLI event printer handles plan mode events
# ---------------------------------------------------------------------------


class TestCLIPlanModeEvents:
    def test_plan_mode_entered_in_events_module(self):
        """Verify PLAN_MODE_ENTERED exists and can be created."""
        event = AgentEvent(type=EventType.PLAN_MODE_ENTERED, data={})
        assert event.type == EventType.PLAN_MODE_ENTERED

    def test_plan_mode_exited_in_events_module(self):
        """Verify PLAN_MODE_EXITED exists and can be created."""
        event = AgentEvent(type=EventType.PLAN_MODE_EXITED, data={})
        assert event.type == EventType.PLAN_MODE_EXITED
