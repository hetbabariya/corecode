"""Memory tools: remember and recall.

These tools let the LLM store and retrieve cross-session memories.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool

if TYPE_CHECKING:
    from coding_agent.agent.memory import MemoryManager


_memory_manager: MemoryManager | None = None


def set_memory_manager(manager: Any) -> None:
    """Set the global memory manager reference (called by AgentLoop)."""
    global _memory_manager
    _memory_manager = manager


def get_memory_manager() -> Any:
    """Return the current memory manager."""
    return _memory_manager


@tool(
    name="remember",
    description=(
        "Store a fact, preference, or lesson for future sessions. "
        "Use this to remember user preferences, project conventions, "
        "solutions to recurring problems, or anything useful across sessions."
    ),
    permission="read",
)
async def remember(
    content: str,
    tags: list[str] | None = None,
) -> ToolResult:
    """Store a memory for future recall.

    Parameters
    ----------
    content:
        The fact, preference, or lesson to remember.
    tags:
        Optional tags to categorise the memory (e.g. ["python", "style"]).
    """
    if _memory_manager is None:
        return ToolResult(success=False, output="Memory system not initialised.", error="Memory system not initialised.")

    if not content.strip():
        return ToolResult(success=False, output="Content cannot be empty.", error="Content cannot be empty.")

    row_id = await _memory_manager.store(
        content.strip(),
        memory_type="semantic",
        tags=tags,
    )

    tag_str = ", ".join(tags) if tags else "none"
    logger.info("memory_tool_remember", row_id=row_id, tags=tag_str)
    return ToolResult(success=True, output=f"Remembered (id={row_id}): {content.strip()[:120]}")


@tool(
    name="recall",
    description=(
        "Search past memories for relevant context. "
        "Use this before starting work to recall project conventions, "
        "previous solutions, or user preferences from earlier sessions."
    ),
    permission="read",
)
async def recall(
    query: str = "",
    limit: int = 10,
) -> ToolResult:
    """Search stored memories.

    Parameters
    ----------
    query:
        Search query (matches against memory content). Empty returns recent.
    limit:
        Maximum number of results to return (default 10).
    """
    if _memory_manager is None:
        return ToolResult(success=False, output="Memory system not initialised.", error="Memory system not initialised.")

    memories = await _memory_manager.recall(query, limit=limit)

    if not memories:
        return ToolResult(success=True, output="No memories found.")

    lines: list[str] = []
    for m in memories:
        tag_str = f" [{', '.join(m.tags)}]" if m.tags else ""
        lines.append(f"[{m.memory_type}] id={m.id}{tag_str}: {m.content}")

    output = "\n".join(lines)
    logger.info("memory_tool_recall", query=query, count=len(memories))
    return ToolResult(success=True, output=output)
