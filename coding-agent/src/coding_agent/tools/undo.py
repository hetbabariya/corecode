"""Undo and redo tools.

These tools let the LLM reverse or re-apply file mutations.
"""

from __future__ import annotations

from typing import Any

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool
from coding_agent.agent.undo import UndoManager


_manager: UndoManager | None = None


def set_undo_manager(manager: Any) -> None:
    """Set the global undo manager reference (called by AgentLoop)."""
    global _manager
    _manager = manager


def get_undo_manager() -> UndoManager | None:
    """Return the current undo manager."""
    return _manager


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
    if _manager is None:
        return ToolResult(success=False, output="Undo system not initialised.", error="Undo system not initialised.")

    entry = _manager.undo()
    if entry is None:
        return ToolResult(success=True, output="Nothing to undo.")

    try:
        UndoManager.apply_entry(entry, redo=False)
        desc = entry.description or f"{entry.tool_name} on {entry.file_path}"
        return ToolResult(success=True, output=f"Undone: {desc}")
    except Exception as e:
        logger.error("undo_apply_failed", error=str(e), file=entry.file_path)
        return ToolResult(success=False, output=f"Undo failed: {e}", error=f"Undo failed: {e}")


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
    if _manager is None:
        return ToolResult(success=False, output="Undo system not initialised.", error="Undo system not initialised.")

    entry = _manager.redo()
    if entry is None:
        return ToolResult(success=True, output="Nothing to redo.")

    try:
        UndoManager.apply_entry(entry, redo=True)
        desc = entry.description or f"{entry.tool_name} on {entry.file_path}"
        return ToolResult(success=True, output=f"Redone: {desc}")
    except Exception as e:
        logger.error("redo_apply_failed", error=str(e), file=entry.file_path)
        return ToolResult(success=False, output=f"Redo failed: {e}", error=f"Redo failed: {e}")


@tool(
    name="undo_history",
    description=(
        "List recent undo/redo history. Shows what changes are available "
        "to undo or redo."
    ),
    permission="read",
)
async def undo_history(limit: int = 10) -> ToolResult:
    """Show recent undo history."""
    if _manager is None:
        return ToolResult(success=False, output="Undo system not initialised.", error="Undo system not initialised.")

    entries = _manager.list_entries(limit=limit)
    if not entries:
        return ToolResult(success=True, output="No undo history.")

    lines = []
    for i, entry in enumerate(entries):
        from datetime import datetime
        ts = datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")
        desc = entry.description or f"{entry.tool_name} on {entry.file_path}"
        lines.append(f"  {i+1}. [{ts}] {desc}")

    header = f"Undo history ({_manager.undo_count} undoable, {_manager.redo_count} redoable):"
    return ToolResult(success=True, output=header + "\n" + "\n".join(lines))
