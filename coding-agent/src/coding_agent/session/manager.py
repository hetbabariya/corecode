"""Session persistence using SQLite.

Provides CRUD operations for sessions, messages, tool operations,
and cross-session memory.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite


_SCHEMA_VERSION = 2

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    workspace TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,
    tool_call_id TEXT,
    name TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_args TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace TEXT NOT NULL DEFAULT '',
    memory_type TEXT NOT NULL DEFAULT 'semantic',
    content TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_operations_session ON operations(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_workspace ON memory(workspace);
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(memory_type);
"""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SessionInfo:
    """Summary of a session for listing."""

    id: str
    created_at: str
    updated_at: str
    model: str
    provider: str
    summary: str
    total_tokens: int
    total_cost: float


@dataclass
class MessageRecord:
    """A persisted message."""

    id: int
    session_id: str
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    created_at: str = ""


@dataclass
class OperationRecord:
    """A persisted tool operation for undo/history."""

    id: int
    session_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    success: bool = True
    created_at: str = ""


@dataclass(frozen=True)
class MemoryRecord:
    """A single memory entry."""

    id: int
    workspace: str
    memory_type: str
    content: str
    tags: list[str]
    session_id: str | None
    created_at: str
    updated_at: str


def _json_dumps(obj: object) -> str:
    """Shortcut to JSON-serialise a value."""
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Session Manager
# ---------------------------------------------------------------------------


class SessionManager:
    """Async SQLite-backed session persistence.

    Usage::

        manager = SessionManager(db_path=Path("~/.coding-agent/sessions.db"))
        await manager.initialize()

        session_id = await manager.create_session(model="gemini-2.5-flash")
        await manager.save_message(session_id, "user", "Fix the bug")
        await manager.save_message(session_id, "assistant", "I found the issue...")
        await manager.save_operation(session_id, "edit_file", {"path": "x.py"}, "OK")

        sessions = await manager.list_sessions()
        messages = await manager.load_session(session_id)
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open the database and run schema migrations."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript(_SCHEMA_SQL)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    async def create_session(
        self,
        model: str = "",
        provider: str = "",
        workspace: str = "",
    ) -> str:
        """Create a new session and return its ID."""
        session_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO sessions (id, created_at, updated_at, model, provider, workspace) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, now, now, model, provider, workspace),
        )
        await self._db.commit()
        return session_id

    async def list_sessions(self, limit: int = 50) -> list[SessionInfo]:
        """List recent sessions, most recent first."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, created_at, updated_at, model, provider, summary, "
            "total_tokens, total_cost "
            "FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            SessionInfo(
                id=r[0],
                created_at=r[1],
                updated_at=r[2],
                model=r[3],
                provider=r[4],
                summary=r[5],
                total_tokens=r[6],
                total_cost=r[7],
            )
            for r in rows
        ]

    async def get_session(self, session_id: str) -> SessionInfo | None:
        """Get a single session by ID."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, created_at, updated_at, model, provider, summary, "
            "total_tokens, total_cost "
            "FROM sessions WHERE id = ?",
            (session_id,),
        )
        r = await cursor.fetchone()
        if not r:
            return None
        return SessionInfo(
            id=r[0],
            created_at=r[1],
            updated_at=r[2],
            model=r[3],
            provider=r[4],
            summary=r[5],
            total_tokens=r[6],
            total_cost=r[7],
        )

    async def update_session_summary(
        self, session_id: str, summary: str
    ) -> None:
        """Update the session summary (generated at session end)."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE sessions SET summary = ?, updated_at = ? WHERE id = ?",
            (summary, now, session_id),
        )
        await self._db.commit()

    async def update_session_stats(
        self, session_id: str, tokens: int, cost: float
    ) -> None:
        """Accumulate token and cost stats for a session."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE sessions SET total_tokens = total_tokens + ?, "
            "total_cost = total_cost + ?, updated_at = ? WHERE id = ?",
            (tokens, cost, now, session_id),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> int:
        """Persist a message and return its ID."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        cursor = await self._db.execute(
            "INSERT INTO messages "
            "(session_id, role, content, tool_calls, tool_call_id, name, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, role, content, tool_calls_json, tool_call_id, name, now),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def load_session(self, session_id: str) -> list[MessageRecord]:
        """Load all messages for a session in chronological order."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, session_id, role, content, tool_calls, tool_call_id, "
            "name, created_at "
            "FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )
        rows = await cursor.fetchall()
        records: list[MessageRecord] = []
        for r in rows:
            tool_calls = json.loads(r[4]) if r[4] else None
            records.append(
                MessageRecord(
                    id=r[0],
                    session_id=r[1],
                    role=r[2],
                    content=r[3],
                    tool_calls=tool_calls,
                    tool_call_id=r[5],
                    name=r[6],
                    created_at=r[7],
                )
            )
        return records

    # ------------------------------------------------------------------
    # Operations (for undo / history)
    # ------------------------------------------------------------------

    async def save_operation(
        self,
        session_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        result: str,
        success: bool = True,
    ) -> int:
        """Persist a tool operation and return its ID."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        cursor = await self._db.execute(
            "INSERT INTO operations "
            "(session_id, tool_name, tool_args, result, success, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, tool_name, json.dumps(tool_args), result, int(success), now),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_operations(
        self, session_id: str, limit: int = 100
    ) -> list[OperationRecord]:
        """Get recent operations for a session (most recent last)."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, session_id, tool_name, tool_args, result, success, created_at "
            "FROM operations WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            OperationRecord(
                id=r[0],
                session_id=r[1],
                tool_name=r[2],
                tool_args=json.loads(r[3]) if r[3] else {},
                result=r[4],
                success=bool(r[5]),
                created_at=r[6],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Memory CRUD
    # ------------------------------------------------------------------

    async def save_memory(
        self,
        content: str,
        *,
        memory_type: str = "semantic",
        workspace: str = "",
        tags: list[str] | None = None,
        session_id: str | None = None,
    ) -> int:
        """Insert a memory record and return its id."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        cursor = await self._db.execute(
            "INSERT INTO memory "
            "(workspace, memory_type, content, tags, session_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                workspace,
                memory_type,
                content,
                _json_dumps(tags or []),
                session_id,
                now,
                now,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_memories(
        self,
        *,
        workspace: str = "",
        memory_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """Return memory records, newest first."""
        assert self._db is not None
        query = (
            "SELECT id, workspace, memory_type, content, tags, "
            "session_id, created_at, updated_at "
            "FROM memory WHERE 1=1"
        )
        params: list[str | int] = []
        if workspace:
            query += " AND workspace = ?"
            params.append(workspace)
        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            MemoryRecord(
                id=r[0],
                workspace=r[1],
                memory_type=r[2],
                content=r[3],
                tags=json.loads(r[4]) if r[4] else [],
                session_id=r[5],
                created_at=r[6],
                updated_at=r[7],
            )
            for r in rows
        ]

    async def search_memories(
        self,
        query: str,
        *,
        workspace: str = "",
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Simple LIKE-based search across memory content."""
        assert self._db is not None
        sql = (
            "SELECT id, workspace, memory_type, content, tags, "
            "session_id, created_at, updated_at "
            "FROM memory WHERE content LIKE ?"
        )
        params: list[str | int] = [f"%{query}%"]
        if workspace:
            sql += " AND workspace = ?"
            params.append(workspace)
        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [
            MemoryRecord(
                id=r[0],
                workspace=r[1],
                memory_type=r[2],
                content=r[3],
                tags=json.loads(r[4]) if r[4] else [],
                session_id=r[5],
                created_at=r[6],
                updated_at=r[7],
            )
            for r in rows
        ]

    async def delete_memory(self, memory_id: int) -> bool:
        """Delete a memory record by id. Returns True if deleted."""
        assert self._db is not None
        cursor = await self._db.execute(
            "DELETE FROM memory WHERE id = ?",
            (memory_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def update_memory(self, memory_id: int, content: str) -> bool:
        """Update a memory's content and updated_at timestamp."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        cursor = await self._db.execute(
            "UPDATE memory SET content = ?, updated_at = ? WHERE id = ?",
            (content, now, memory_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0
