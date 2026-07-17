"""Disk persistence for the undo system.

Stores undo entries and stack state on disk so undo/redo survives crashes
and restarts.  Uses atomic writes (temp-file + rename) for crash safety.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from coding_agent.logging import logger

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StoredEntry:
    """A persisted undo entry."""

    id: str
    tool_name: str
    file_path: str
    before: str
    after: str
    description: str
    timestamp: float


@dataclass
class StoredStack:
    """The persisted undo/redo stack metadata."""

    session_id: str
    created_at: float
    undo_ids: list[str]
    redo_ids: list[str]


# ---------------------------------------------------------------------------
# DiskStore
# ---------------------------------------------------------------------------

class DiskStore:
    """Atomic, file-backed persistence for undo entries and stack state.

    Directory layout::

        .coding-agent/undo/
        ├── stack.json            # session id + ordered entry IDs
        └── entries/
            ├── {id}.json         # individual entry data
            └── ...

    All writes go through a temp-file-then-rename path so that a crash
    mid-write never leaves a corrupt file on disk.
    """

    UNDO_DIR = ".coding-agent/undo"
    STACK_FILE = "stack.json"
    ENTRIES_DIR = "entries"

    def __init__(self, workspace: Path | str = ".") -> None:
        self._root = Path(workspace) / self.UNDO_DIR
        self._entries_dir = self._root / self.ENTRIES_DIR
        self._stack_path = self._root / self.STACK_FILE
        self._ensure_dirs()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._entries_dir.mkdir(exist_ok=True)

    def _atomic_write(self, path: Path, data: dict) -> None:
        """Write *data* as JSON to *path* atomically."""
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Stack operations
    # ------------------------------------------------------------------

    def load_stack(self) -> Optional[StoredStack]:
        """Load the stack metadata, or ``None`` if not found."""
        if not self._stack_path.exists():
            return None
        try:
            raw = json.loads(self._stack_path.read_text(encoding="utf-8"))
            return StoredStack(
                session_id=raw["session_id"],
                created_at=raw["created_at"],
                undo_ids=raw.get("undo_ids", []),
                redo_ids=raw.get("redo_ids", []),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("undo_stack_load_failed", error=str(exc))
            return None

    def save_stack(self, stack: StoredStack) -> None:
        """Persist the stack metadata."""
        self._atomic_write(
            self._stack_path,
            asdict(stack),
        )

    def new_session_id(self) -> str:
        """Generate a new unique session ID."""
        return uuid.uuid4().hex[:12]

    # ------------------------------------------------------------------
    # Entry operations
    # ------------------------------------------------------------------

    def save_entry(self, entry: StoredEntry) -> None:
        """Persist a single undo entry."""
        path = self._entries_dir / f"{entry.id}.json"
        self._atomic_write(path, asdict(entry))

    def load_entry(self, entry_id: str) -> Optional[StoredEntry]:
        """Load an entry by ID."""
        path = self._entries_dir / f"{entry_id}.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return StoredEntry(**raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("undo_entry_load_failed", entry_id=entry_id, error=str(exc))
            return None

    def delete_entry(self, entry_id: str) -> None:
        """Remove an entry file."""
        path = self._entries_dir / f"{entry_id}.json"
        if path.exists():
            path.unlink()

    def list_entry_ids(self) -> list[str]:
        """Return all entry IDs currently on disk."""
        return [
            p.stem
            for p in self._entries_dir.iterdir()
            if p.suffix == ".json"
        ]

    def cleanup_old_entries(self, max_age_seconds: float = 86400 * 30) -> int:
        """Delete entries older than *max_age_seconds*.  Returns count removed."""
        cutoff = time.time() - max_age_seconds
        removed = 0
        for path in self._entries_dir.iterdir():
            if path.suffix != ".json":
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if raw.get("timestamp", 0) < cutoff:
                    path.unlink()
                    removed += 1
            except (json.JSONDecodeError, OSError):
                continue
        return removed
