"""In-memory undo / redo stack.

Tracks file mutations so the LLM (or user via TUI) can undo/redo
write, edit, multi_edit, and apply_patch operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from coding_agent.logging import logger


@dataclass
class UndoEntry:
    """A single undoable mutation."""

    tool_name: str
    file_path: str
    before: str  # file contents before the mutation (empty = newly created)
    after: str  # file contents after the mutation (empty = file was deleted)
    description: str = ""


class UndoStack:
    """Fixed-capacity undo/redo stack.

    Every file mutation should call :meth:`push` with the before/after
    snapshot.  ``undo()`` restores the *before* state; ``redo()``
    re-applies the *after* state.
    """

    def __init__(self, max_entries: int = 50) -> None:
        self._undo_stack: list[UndoEntry] = []
        self._redo_stack: list[UndoEntry] = []
        self._max = max_entries

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def push(self, entry: UndoEntry) -> None:
        """Record a new mutation (clears the redo stack)."""
        self._undo_stack.append(entry)
        if len(self._undo_stack) > self._max:
            self._undo_stack.pop(0)
        # Any new mutation invalidates the redo history
        self._redo_stack.clear()
        logger.debug(
            "undo_push",
            tool=entry.tool_name,
            file=entry.file_path,
            stack_size=len(self._undo_stack),
        )

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------

    def undo(self) -> UndoEntry | None:
        """Pop the most recent mutation and return it (or ``None``)."""
        if not self._undo_stack:
            return None
        entry = self._undo_stack.pop()
        self._redo_stack.append(entry)
        logger.info(
            "undo_performed",
            tool=entry.tool_name,
            file=entry.file_path,
            remaining=len(self._undo_stack),
        )
        return entry

    # ------------------------------------------------------------------
    # Redo
    # ------------------------------------------------------------------

    def redo(self) -> UndoEntry | None:
        """Re-apply the most recently undone mutation (or ``None``)."""
        if not self._redo_stack:
            return None
        entry = self._redo_stack.pop()
        self._undo_stack.append(entry)
        logger.info(
            "redo_performed",
            tool=entry.tool_name,
            file=entry.file_path,
            remaining=len(self._undo_stack),
        )
        return entry

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def peek_undo(self) -> UndoEntry | None:
        """Preview the next undo entry without popping."""
        return self._undo_stack[-1] if self._undo_stack else None

    def peek_redo(self) -> UndoEntry | None:
        """Preview the next redo entry without popping."""
        return self._redo_stack[-1] if self._redo_stack else None

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    @property
    def undo_count(self) -> int:
        return len(self._undo_stack)

    @property
    def redo_count(self) -> int:
        return len(self._redo_stack)

    def clear(self) -> None:
        """Reset both stacks."""
        self._undo_stack.clear()
        self._redo_stack.clear()

    # ------------------------------------------------------------------
    # Apply helpers
    # ------------------------------------------------------------------

    @staticmethod
    def apply_entry(entry: UndoEntry, *, redo: bool = False) -> None:
        """Write the file system to reflect an undo or redo.

        * ``redo=False`` (undo): writes ``entry.before``.
        * ``redo=True``  (redo): writes ``entry.after``.

        If the snapshot is empty the file was either newly created
        (before is empty → undo deletes) or deleted (after is empty
        → redo deletes).
        """
        path = Path(entry.file_path)
        content = entry.after if redo else entry.before

        if not content:
            # File didn't exist before / was deleted after → remove it
            if path.exists():
                path.unlink()
                logger.debug(
                    "undo_file_deleted" if not redo else "redo_file_deleted",
                    file=entry.file_path,
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            logger.debug(
                "undo_file_restored" if not redo else "redo_file_applied",
                file=entry.file_path,
                length=len(content),
            )
