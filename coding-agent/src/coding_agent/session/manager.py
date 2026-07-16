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


_SCHEMA_VERSION = 3

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
    importance REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed TEXT NOT NULL DEFAULT '',
    session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '[]',
    current_step INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'planning',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_operations_session ON operations(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_workspace ON memory(workspace);
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(memory_type);
CREATE INDEX IF NOT EXISTS idx_plans_workspace ON plans(workspace);
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


@dataclass
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
    importance: float = 0.5
    access_count: int = 0
    last_accessed: str = ""


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
        await self._migrate_db()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _migrate_db(self) -> None:
        """Detect schema version and apply incremental migrations."""
        assert self._db is not None
        cursor = await self._db.execute("SELECT version FROM schema_version")
        row = await cursor.fetchone()
        current = row[0] if row else 1

        if current < 2:
            await self._add_column_if_missing("memory", "importance", "REAL NOT NULL DEFAULT 0.5")
            await self._add_column_if_missing("memory", "access_count", "INTEGER NOT NULL DEFAULT 0")
            await self._add_column_if_missing("memory", "last_accessed", "TEXT NOT NULL DEFAULT ''")

        if current < 3:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace TEXT NOT NULL DEFAULT '',
                    goal TEXT NOT NULL DEFAULT '',
                    steps TEXT NOT NULL DEFAULT '[]',
                    current_step INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'planning',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plans_workspace ON plans(workspace);
            """)

        await self._db.execute("DELETE FROM schema_version")
        await self._db.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
        await self._db.commit()

    async def _add_column_if_missing(self, table: str, column: str, col_def: str) -> None:
        """Add a column to *table* only if it doesn't already exist."""
        assert self._db is not None
        cursor = await self._db.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in await cursor.fetchall()]
        if column not in cols:
            await self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")

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
        importance: float = 0.5,
        session_id: str | None = None,
    ) -> int:
        """Insert a memory record and return its id."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        cursor = await self._db.execute(
            "INSERT INTO memory "
            "(workspace, memory_type, content, tags, importance, "
            "session_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                workspace,
                memory_type,
                content,
                _json_dumps(tags or []),
                importance,
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
            "session_id, created_at, updated_at, "
            "importance, access_count, last_accessed "
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
                importance=r[8] if r[8] is not None else 0.5,
                access_count=r[9] if r[9] is not None else 0,
                last_accessed=r[10] or "",
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
            "session_id, created_at, updated_at, "
            "importance, access_count, last_accessed "
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
                importance=r[8] if r[8] is not None else 0.5,
                access_count=r[9] if r[9] is not None else 0,
                last_accessed=r[10] or "",
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

    async def touch_memory(self, memory_id: int) -> None:
        """Increment access_count and update last_accessed."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE memory SET access_count = access_count + 1, "
            "last_accessed = ? WHERE id = ?",
            (now, memory_id),
        )
        await self._db.commit()

    async def count_memories(
        self, *, workspace: str = "", memory_type: str | None = None
    ) -> int:
        """Count memory records."""
        assert self._db is not None
        query = "SELECT COUNT(*) FROM memory WHERE 1=1"
        params: list[str] = []
        if workspace:
            query += " AND workspace = ?"
            params.append(workspace)
        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type)
        cursor = await self._db.execute(query, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def delete_memories(self, ids: list[int]) -> int:
        """Delete multiple memories by id. Returns count deleted."""
        if not ids:
            return 0
        assert self._db is not None
        placeholders = ",".join("?" for _ in ids)
        cursor = await self._db.execute(
            f"DELETE FROM memory WHERE id IN ({placeholders})",
            ids,
        )
        await self._db.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Plan CRUD
    # ------------------------------------------------------------------

    async def save_plan(
        self,
        workspace: str,
        goal: str,
        steps: list[dict[str, Any]],
        current_step: int,
        status: str,
    ) -> int:
        """Upsert a plan for a workspace. Returns plan id."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        cursor = await self._db.execute(
            "SELECT id FROM plans WHERE workspace = ? AND status NOT IN ('completed', 'failed')",
            (workspace,),
        )
        existing = await cursor.fetchone()
        if existing:
            plan_id = existing[0]
            await self._db.execute(
                "UPDATE plans SET goal=?, steps=?, current_step=?, status=?, updated_at=? "
                "WHERE id=?",
                (goal, _json_dumps(steps), current_step, status, now, plan_id),
            )
        else:
            cursor = await self._db.execute(
                "INSERT INTO plans (workspace, goal, steps, current_step, status, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (workspace, goal, _json_dumps(steps), current_step, status, now, now),
            )
            plan_id = cursor.lastrowid or 0
        await self._db.commit()
        return plan_id

    async def load_active_plan(
        self, workspace: str
    ) -> dict[str, Any] | None:
        """Load the active (non-completed/failed) plan for a workspace."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, goal, steps, current_step, status "
            "FROM plans WHERE workspace = ? AND status NOT IN ('completed', 'failed') "
            "ORDER BY updated_at DESC LIMIT 1",
            (workspace,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "goal": row[1],
            "steps": json.loads(row[2]) if row[2] else [],
            "current_step": row[3],
            "status": row[4],
        }

    async def complete_plan(self, plan_id: int) -> None:
        """Mark a plan as completed."""
        assert self._db is not None
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE plans SET status = 'completed', updated_at = ? WHERE id = ?",
            (now, plan_id),
        )
        await self._db.commit()
