"""Undo and redo tools.

These tools let the LLM reverse or re-apply file mutations.
"""

from __future__ import annotations

from typing import Any

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool
from coding_agent.agent.undo import UndoStack


_undo_stack: UndoStack | None = None


def set_undo_stack(stack: Any) -> None:
    """Set the global undo stack reference (called by AgentLoop)."""
    global _undo_stack
    _undo_stack = stack


def get_undo_stack() -> UndoStack | None:
    """Return the current undo stack."""
    return _undo_stack


@tool(
    name="undo",
    description=(
        "Undo the last file mutation (write, edit, multi_edit, apply_patch). "
        "Restores the file to its state before that change."
    ),
    permission="write",
)
async def undo() -> ToolResult:
    """Undo the most recent file change."""
    if _undo_stack is None:
        return ToolResult(output="Undo system not initialised.", error=True)

    entry = _undo_stack.undo()
    if entry is None:
        return ToolResult(output="Nothing to undo.")

    try:
        UndoStack.apply_entry(entry, redo=False)
        desc = entry.description or f"{entry.tool_name} on {entry.file_path}"
        return ToolResult(output=f"Undone: {desc}")
    except Exception as e:
        logger.error("undo_apply_failed", error=str(e), file=entry.file_path)
        return ToolResult(output=f"Undo failed: {e}", error=True)


@tool(
    name="redo",
    description=(
        "Redo the last undone file mutation. "
        "Re-applies the change that was just undone."
    ),
    permission="write",
)
async def redo() -> ToolResult:
    """Re-apply the most recently undone change."""
    if _undo_stack is None:
        return ToolResult(output="Undo system not initialised.", error=True)

    entry = _undo_stack.redo()
    if entry is None:
        return ToolResult(output="Nothing to redo.")

    try:
        UndoStack.apply_entry(entry, redo=True)
        desc = entry.description or f"{entry.tool_name} on {entry.file_path}"
        return ToolResult(output=f"Redone: {desc}")
    except Exception as e:
        logger.error("redo_apply_failed", error=str(e), file=entry.file_path)
        return ToolResult(output=f"Redo failed: {e}", error=True)
