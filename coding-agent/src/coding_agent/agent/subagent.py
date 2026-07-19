"""Subagent delegation — spawn child agents for bounded subtasks.

Subagents run with isolated context, filtered tools, and tight budgets.
They cannot spawn sub-subagents (depth limit enforced).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coding_agent.agent.context import ContextManager
from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.permissions import Permission, PermissionManager
from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from coding_agent.agent.loop import AgentLoop

# Default tools available to subagents (read-only + planning).
_SUBAGENT_DEFAULT_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "list_files",
    "search_content",
    "search_files",
    "git_status",
    "git_diff",
    "git_log",
    "create_plan",
    "update_plan",
    "refresh_index",
    "count_tokens",
})


def _create_filtered_registry(
    allowed_tools: list[str] | None,
    source_registry: ToolRegistry,
) -> ToolRegistry:
    """Create a new ToolRegistry containing only the allowed tools.

    If *allowed_tools* is ``None``, returns the source registry unchanged.
    Raises ``KeyError`` if a requested tool doesn't exist in the source.
    """
    if allowed_tools is None:
        return source_registry

    filtered = ToolRegistry(name="subagent")
    for name in allowed_tools:
        tool = source_registry.get(name)  # raises KeyError if missing
        filtered.register(tool)
    return filtered


# Maps parent event types to subagent-specific event types.
_SUBAGENT_EVENT_MAP: dict[EventType, EventType] = {
    EventType.TOOL_START: EventType.SUBAGENT_TOOL_START,
    EventType.TOOL_RESULT: EventType.SUBAGENT_TOOL_RESULT,
}


class SubAgent:
    """A child agent that runs a bounded subtask with isolated context.

    Usage::

        sub = SubAgent(parent_loop=agent, prompt="Find all TODO comments")
        async for event in sub.run():
            # event.depth == 1 for subagent events
            ...
    """

    def __init__(
        self,
        parent_loop: AgentLoop,
        prompt: str,
        allowed_tools: list[str] | None = None,
        max_iterations: int = 20,
        depth: int = 0,
    ) -> None:
        from coding_agent.config import Settings

        self._prompt = prompt
        self._depth = depth

        # Fresh context — isolated from parent
        config = Settings()
        self._context = ContextManager(max_tokens=config.max_tokens)

        # Filtered tool registry
        self._tool_registry = _create_filtered_registry(
            allowed_tools, parent_loop.tool_registry
        )

        # Read-only permissions by default
        self._permissions = PermissionManager(level=Permission.READ)

        # Import here to avoid circular imports at module level
        from coding_agent.agent.loop import AgentLoop

        self._loop = AgentLoop(
            llm_client=parent_loop.llm_client,
            permission_manager=self._permissions,
            context_manager=self._context,
            workspace=parent_loop.workspace,
            max_iterations=max_iterations,
            max_cost=config.subagent_max_cost,
            max_time=config.subagent_max_time,
            verify_after_edit=False,
            tool_registry=self._tool_registry,
            depth=depth,
        )

        logger.debug(
            "subagent_created",
            depth=depth,
            tools=allowed_tools,
            max_iterations=max_iterations,
        )

    async def run(self) -> AsyncIterator[AgentEvent]:
        """Run the subagent, yielding events with depth for TUI visibility.

        Yields ``SUBAGENT_STARTED``, ``SUBAGENT_TOOL_START``,
        ``SUBAGENT_TOOL_RESULT``, ``TEXT``, and ``SUBAGENT_COMPLETED`` events.
        """
        yield AgentEvent(
            type=EventType.SUBAGENT_STARTED,
            data={"prompt": self._prompt[:200]},
            depth=self._depth,
        )

        final_text = ""
        try:
            async for event in self._loop.process_input(self._prompt):
                # Map tool events to subagent-specific types
                mapped_type = _SUBAGENT_EVENT_MAP.get(event.type)
                if mapped_type is not None:
                    yield AgentEvent(
                        type=mapped_type,
                        data=event.data,
                        error=getattr(event, "error", None),
                        depth=self._depth,
                    )
                elif event.type == EventType.TEXT:
                    final_text += event.data
                    yield AgentEvent(
                        type=EventType.TEXT,
                        data=event.data,
                        depth=self._depth,
                    )
                elif event.type == EventType.DONE:
                    break
        except Exception as exc:
            logger.error("subagent_failed", error=str(exc))
            yield AgentEvent(
                type=EventType.ERROR,
                data=f"[Subagent error: {exc}]",
                error=str(exc),
                depth=self._depth,
            )

        logger.debug(
            "subagent_completed",
            depth=self._depth,
            response_length=len(final_text),
        )
        yield AgentEvent(
            type=EventType.SUBAGENT_COMPLETED,
            data={"response_length": len(final_text)},
            depth=self._depth,
        )
