"""In-memory undo/redo stack with disk persistence.

Tracks file mutations so the LLM (or user via TUI) can undo/redo
write, edit, multi_edit, and apply_patch operations.

Inspired by Claude Code's file-snapshot approach: each mutation stores
the full before/after content of the affected file.  Undo restores the
before state; redo re-applies the after state.

Stack state is persisted to ``.coding-agent/undo/`` so that undo/redo
survives crashes and session restarts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from coding_agent.logging import logger


# ---------------------------------------------------------------------------
# Entry data class
# ---------------------------------------------------------------------------

@dataclass
class UndoEntry:
    """A single undoable mutation."""

    tool_name: str
    file_path: str
    before: str  # file contents before the mutation (empty = newly created)
    after: str  # file contents after the mutation (empty = file was deleted)
    description: str = ""
    id: str = ""
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:8]
        if not self.timestamp:
            self.timestamp = time.time()


# ---------------------------------------------------------------------------
# UndoManager
# ---------------------------------------------------------------------------

class UndoManager:
    """Fixed-capacity undo/redo stack with disk persistence.

    Every file mutation should call :meth:`push` with the before/after
    snapshot.  ``undo()`` restores the *before* state; ``redo()``
    re-applies the *after* state.

    Parameters
    ----------
    workspace:
        The project root (used for disk persistence).
    max_entries:
        Maximum number of entries kept in the undo stack.
    """

    def __init__(self, workspace: Path | str = ".", max_entries: int = 50) -> None:
        self._workspace = Path(workspace)
        self._max = max_entries
        self._undo_stack: list[UndoEntry] = []
        self._redo_stack: list[UndoEntry] = []
        self._session_id: str = ""
        self._store: _LazyStore | None = None

    # ------------------------------------------------------------------
    # Lazy store initialisation (avoids import at module level)
    # ------------------------------------------------------------------

    def _get_store(self) -> _LazyStore:
        if self._store is None:
            from coding_agent.agent.disk_store import DiskStore
            self._store = _LazyStore(DiskStore(self._workspace))
        return self._store

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    def init_session(self) -> str:
        """Initialise or resume a session.  Returns the session ID."""
        store = self._get_store()
        saved = store.load_stack()

        if saved is not None:
            # Resume existing session
            self._session_id = saved.session_id
            for eid in saved.undo_ids:
                entry = store.load_entry(eid)
                if entry is not None:
                    self._undo_stack.append(self._stored_to_entry(entry))
            for eid in saved.redo_ids:
                entry = store.load_entry(eid)
                if entry is not None:
                    self._redo_stack.append(self._stored_to_entry(entry))
            logger.info(
                "undo_session_resumed",
                session_id=self._session_id,
                undo_count=len(self._undo_stack),
                redo_count=len(self._redo_stack),
            )
        else:
            # New session
            self._session_id = store.new_session_id()
            self._save()
            logger.info("undo_session_new", session_id=self._session_id)

        return self._session_id

    def _save(self) -> None:
        """Persist current stack state to disk."""
        store = self._get_store()
        from coding_agent.agent.disk_store import StoredStack, StoredEntry

        # Save all entries
        for entry in self._undo_stack:
            store.save_entry(StoredEntry(
                id=entry.id,
                tool_name=entry.tool_name,
                file_path=entry.file_path,
                before=entry.before,
                after=entry.after,
                description=entry.description,
                timestamp=entry.timestamp,
            ))
        for entry in self._redo_stack:
            store.save_entry(StoredEntry(
                id=entry.id,
                tool_name=entry.tool_name,
                file_path=entry.file_path,
                before=entry.before,
                after=entry.after,
                description=entry.description,
                timestamp=entry.timestamp,
            ))

        # Save stack metadata
        store.save_stack(StoredStack(
            session_id=self._session_id,
            created_at=time.time(),
            undo_ids=[e.id for e in self._undo_stack],
            redo_ids=[e.id for e in self._redo_stack],
        ))

    @staticmethod
    def _stored_to_entry(stored: object) -> UndoEntry:
        """Convert a ``StoredEntry`` to an ``UndoEntry``."""
        return UndoEntry(
            id=stored.id,
            tool_name=stored.tool_name,
            file_path=stored.file_path,
            before=stored.before,
            after=stored.after,
            description=stored.description,
            timestamp=stored.timestamp,
        )

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
        self._save()
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
        self._save()
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
        self._save()
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

    def list_entries(self, limit: int = 20) -> list[UndoEntry]:
        """Return the most recent *limit* undo entries (newest first)."""
        return list(reversed(self._undo_stack[-limit:]))

    def clear(self) -> None:
        """Reset both stacks and persist."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._save()

    # ------------------------------------------------------------------
    # Apply helpers
    # ------------------------------------------------------------------

    @staticmethod
    def apply_entry(entry: UndoEntry, *, redo: bool = False) -> None:
        """Write the file system to reflect an undo or redo.

        * ``redo=False`` (undo): writes ``entry.before``.
        * ``redo=True``  (redo): writes ``entry.after``.

        If the snapshot is empty the file was either newly created
        (before is empty -> undo deletes) or deleted (after is empty
        -> redo deletes).
        """
        path = Path(entry.file_path)
        content = entry.after if redo else entry.before

        if not content:
            # File didn't exist before / was deleted after -> remove it
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


# ---------------------------------------------------------------------------
# Lazy store wrapper (avoids circular import)
# ---------------------------------------------------------------------------

class _LazyStore:
    """Thin wrapper around DiskStore for lazy initialisation."""

    def __init__(self, store: object) -> None:
        self._store = store

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)


# ---------------------------------------------------------------------------
# Module-level singleton (set by AgentLoop)
# ---------------------------------------------------------------------------

_manager: UndoManager | None = None


def set_undo_manager(manager: UndoManager) -> None:
    """Register the global undo manager (called by AgentLoop)."""
    global _manager
    _manager = manager


def get_undo_manager() -> UndoManager | None:
    """Return the current undo manager, or ``None``."""
    return _manager
