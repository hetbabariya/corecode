"""Delegate task tool — spawn child agents for bounded subtasks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool

# Module-level state injected by AgentLoop (same pattern as undo/memory)
_current_loop: Any = None
_semaphore: asyncio.Semaphore | None = None

# Event queue for subagent visibility — drained by parent loop after tool execution
_event_queue: asyncio.Queue[AgentEvent | None] | None = None


def set_parent_loop(loop: Any) -> None:
    """Inject the parent AgentLoop so delegate_task can spawn subagents."""
    global _current_loop
    _current_loop = loop


def set_semaphore(sem: asyncio.Semaphore) -> None:
    """Inject the concurrency semaphore for subagent spawning."""
    global _semaphore
    _semaphore = sem


async def drain_events(
    queue: asyncio.Queue[AgentEvent | None] | None = None,
) -> AsyncIterator[AgentEvent]:
    """Drain all queued subagent events. Called by parent loop after tool execution."""
    q = queue or _event_queue
    if q is None:
        return
    while True:
        event = await q.get()
        if event is None:
            break
        yield event


@tool(
    name="delegate_task",
    description=(
        "Spawn a child agent to work on a subtask with isolated context. "
        "The child runs in parallel and returns its final text response. "
        "Use for bounded exploration, research, or subtasks that don't "
        "need write access to the workspace."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Task description for the child agent",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional tool names the child can use. "
                    "Defaults to read-only tools."
                ),
            },
            "max_iterations": {
                "type": "integer",
                "description": "Max loop iterations (default: 20)",
            },
        },
        "required": ["prompt"],
    },
    permission="execute",
)
async def delegate_task(
    prompt: str,
    tools: list[str] | None = None,
    max_iterations: int = 20,
) -> ToolResult:
    """Spawn a child agent to work on a bounded subtask."""
    global _event_queue

    if _current_loop is None:
        return ToolResult(
            success=False,
            error="delegate_task not initialized: no parent loop",
        )

    from coding_agent.agent.subagent import SubAgent
    from coding_agent.config import Settings

    config = Settings()
    depth_limit = config.subagent_depth_limit

    # Enforce depth limit
    if _current_loop._depth >= depth_limit:
        return ToolResult(
            success=False,
            error=(
                f"Subagent depth limit reached ({depth_limit}). "
                "Cannot spawn sub-subagents."
            ),
        )

    # Enforce iteration limit from config
    max_iterations = min(max_iterations, config.subagent_max_iterations)

    # Acquire concurrency slot
    sem = _semaphore or asyncio.Semaphore(config.subagent_max_concurrent)
    if sem.locked():
        logger.debug("subagent_queued", depth=_current_loop._depth)

    async with sem:
        sub = SubAgent(
            parent_loop=_current_loop,
            prompt=prompt,
            allowed_tools=tools,
            max_iterations=max_iterations,
            depth=_current_loop._depth + 1,
        )

        # Set up event queue for subagent visibility
        _event_queue = asyncio.Queue()

        # Track the task in the parent loop
        task = asyncio.create_task(_run_and_collect(sub))
        _current_loop._subagent_tasks.add(task)

        try:
            final_text = await task
        except asyncio.CancelledError:
            logger.warning("subagent_cancelled", depth=_current_loop._depth)
            return ToolResult(success=False, error="Subagent cancelled")
        finally:
            _current_loop._subagent_tasks.discard(task)
            # Save queue reference before clearing module-level state
            saved_queue = _event_queue
            # Send sentinel so drain_events() stops
            if saved_queue is not None:
                await saved_queue.put(None)
            _event_queue = None

    logger.info(
        "subagent_delegated",
        prompt_length=len(prompt),
        result_length=len(final_text),
        depth=_current_loop._depth,
    )
    return ToolResult(
        success=True,
        output=final_text,
        metadata={"_subagent_event_queue": saved_queue},
    )


async def _run_and_collect(sub: SubAgent) -> str:
    """Run subagent, forwarding events to queue and collecting final text."""
    final_text = ""
    async for event in sub.run():
        if event.type == EventType.TEXT:
            final_text += event.data
        # Forward all events to the queue (except plain TEXT — we collect that)
        if _event_queue is not None and event.type != EventType.TEXT:
            await _event_queue.put(event)
    return final_text
