"""Tests for session persistence (SQLite-backed SessionManager)."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.session.manager import (
    SessionManager,
)


@pytest.fixture
async def manager(tmp_path: Path) -> SessionManager:
    """Create a SessionManager with a temporary database."""
    db_path = tmp_path / "test_sessions.db"
    mgr = SessionManager(db_path=db_path)
    await mgr.initialize()
    yield mgr  # type: ignore[misc]
    await mgr.close()


# ===================================================================
# Session CRUD tests
# ===================================================================


class TestSessionCreate:
    async def test_create_session_returns_id(self, manager: SessionManager) -> None:
        session_id = await manager.create_session(model="test-model")
        assert isinstance(session_id, str)
        assert len(session_id) == 12

    async def test_create_session_with_metadata(
        self, manager: SessionManager
    ) -> None:
        session_id = await manager.create_session(
            model="gemini-2.5-flash",
            provider="gemini",
            workspace="/tmp/project",
        )
        info = await manager.get_session(session_id)
        assert info is not None
        assert info.model == "gemini-2.5-flash"
        assert info.provider == "gemini"


class TestSessionList:
    async def test_list_empty(self, manager: SessionManager) -> None:
        sessions = await manager.list_sessions()
        assert sessions == []

    async def test_list_returns_sessions(self, manager: SessionManager) -> None:
        await manager.create_session(model="m1")
        await manager.create_session(model="m2")
        sessions = await manager.list_sessions()
        assert len(sessions) == 2
        # Most recent first
        assert sessions[0].model == "m2"
        assert sessions[1].model == "m1"

    async def test_list_respects_limit(self, manager: SessionManager) -> None:
        for i in range(10):
            await manager.create_session(model=f"m{i}")
        sessions = await manager.list_sessions(limit=3)
        assert len(sessions) == 3


class TestSessionUpdate:
    async def test_update_summary(self, manager: SessionManager) -> None:
        session_id = await manager.create_session()
        await manager.update_session_summary(session_id, "Fixed the parser bug")
        info = await manager.get_session(session_id)
        assert info is not None
        assert info.summary == "Fixed the parser bug"

    async def test_update_stats(self, manager: SessionManager) -> None:
        session_id = await manager.create_session()
        await manager.update_session_stats(session_id, tokens=1000, cost=0.05)
        await manager.update_session_stats(session_id, tokens=500, cost=0.02)
        info = await manager.get_session(session_id)
        assert info is not None
        assert info.total_tokens == 1500
        assert info.total_cost == pytest.approx(0.07)


# ===================================================================
# Messages tests
# ===================================================================


class TestMessages:
    async def test_save_and_load_messages(self, manager: SessionManager) -> None:
        session_id = await manager.create_session()
        await manager.save_message(session_id, "user", "Hello")
        await manager.save_message(session_id, "assistant", "Hi there!")
        await manager.save_message(session_id, "user", "How are you?")

        messages = await manager.load_session(session_id)
        assert len(messages) == 3
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there!"
        assert messages[2].role == "user"
        assert messages[2].content == "How are you?"

    async def test_save_message_with_tool_calls(
        self, manager: SessionManager
    ) -> None:
        session_id = await manager.create_session()
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"x.py"}'},
            }
        ]
        msg_id = await manager.save_message(
            session_id, "assistant", "", tool_calls=tool_calls
        )
        assert msg_id > 0

        messages = await manager.load_session(session_id)
        assert len(messages) == 1
        assert messages[0].tool_calls is not None
        assert messages[0].tool_calls[0]["function"]["name"] == "read_file"

    async def test_save_tool_result(self, manager: SessionManager) -> None:
        session_id = await manager.create_session()
        msg_id = await manager.save_message(
            session_id,
            "tool",
            "file contents here",
            tool_call_id="call_1",
            name="read_file",
        )
        assert msg_id > 0

        messages = await manager.load_session(session_id)
        assert messages[0].tool_call_id == "call_1"
        assert messages[0].name == "read_file"

    async def test_empty_session_has_no_messages(
        self, manager: SessionManager
    ) -> None:
        session_id = await manager.create_session()
        messages = await manager.load_session(session_id)
        assert messages == []


# ===================================================================
# Operations tests
# ===================================================================


class TestOperations:
    async def test_save_and_get_operations(
        self, manager: SessionManager
    ) -> None:
        session_id = await manager.create_session()
        await manager.save_operation(
            session_id, "edit_file", {"path": "a.py"}, "OK"
        )
        await manager.save_operation(
            session_id, "write_file", {"path": "b.py"}, "Created"
        )

        ops = await manager.get_operations(session_id)
        assert len(ops) == 2
        assert ops[0].tool_name == "edit_file"
        assert ops[0].tool_args == {"path": "a.py"}
        assert ops[0].success is True
        assert ops[1].tool_name == "write_file"

    async def test_save_failed_operation(self, manager: SessionManager) -> None:
        session_id = await manager.create_session()
        await manager.save_operation(
            session_id, "execute_command", {"cmd": "bad"}, "Error", success=False
        )
        ops = await manager.get_operations(session_id)
        assert len(ops) == 1
        assert ops[0].success is False

    async def test_get_operations_respects_limit(
        self, manager: SessionManager
    ) -> None:
        session_id = await manager.create_session()
        for i in range(20):
            await manager.save_operation(
                session_id, f"tool_{i}", {}, f"result_{i}"
            )
        ops = await manager.get_operations(session_id, limit=5)
        assert len(ops) == 5


# ===================================================================
# Schema migration tests
# ===================================================================


class TestSchemaMigration:
    async def test_initialize_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        mgr1 = SessionManager(db_path=db_path)
        await mgr1.initialize()
        await mgr1.create_session()
        await mgr1.close()

        # Re-initialize — should not fail
        mgr2 = SessionManager(db_path=db_path)
        await mgr2.initialize()
        sessions = await mgr2.list_sessions()
        assert len(sessions) == 1
        await mgr2.close()

    async def test_migration_v2_to_v3(self, tmp_path: Path) -> None:
        """Simulate a v2 database and verify migration adds new columns."""
        import aiosqlite

        db_path = tmp_path / "old.db"
        # Create a v2 schema manually (no importance/access_count/last_accessed, no plans)
        async with aiosqlite.connect(str(db_path)) as db:
            await db.executescript("""
                CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
                INSERT INTO schema_version (version) VALUES (1);
                CREATE TABLE memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace TEXT NOT NULL DEFAULT '',
                    memory_type TEXT NOT NULL DEFAULT 'semantic',
                    content TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    session_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE sessions (
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
                INSERT INTO memory (workspace, content, created_at, updated_at)
                VALUES ('w', 'old memory', '2025-01-01', '2025-01-01');
            """)

        # Open with new SessionManager — should migrate and preserve data
        mgr = SessionManager(db_path=db_path)
        await mgr.initialize()

        # Old memory should still exist
        memories = await mgr.get_memories(workspace="w")
        assert len(memories) == 1
        assert memories[0].content == "old memory"
        assert memories[0].importance == 0.5  # default from migration

        # Plans table should exist
        await mgr.save_plan(workspace="w", goal="Test", steps=[], current_step=0, status="planning")
        loaded = await mgr.load_active_plan("w")
        assert loaded is not None

        await mgr.close()


# ===================================================================
# Memory CRUD tests
# ===================================================================


class TestMemoryCRUD:
    async def test_save_and_get_memory(self, manager: SessionManager) -> None:
        row_id = await manager.save_memory(
            "User prefers dark mode",
            memory_type="semantic",
            workspace="test",
            tags=["preference"],
            importance=0.8,
        )
        assert row_id > 0
        memories = await manager.get_memories(workspace="test")
        assert len(memories) == 1
        assert memories[0].content == "User prefers dark mode"
        assert memories[0].importance == 0.8
        assert memories[0].tags == ["preference"]

    async def test_search_memories(self, manager: SessionManager) -> None:
        await manager.save_memory("Python style guide", workspace="w")
        await manager.save_memory("JavaScript conventions", workspace="w")
        results = await manager.search_memories("Python", workspace="w")
        assert len(results) == 1
        assert "Python" in results[0].content

    async def test_delete_memory(self, manager: SessionManager) -> None:
        row_id = await manager.save_memory("To delete", workspace="w")
        deleted = await manager.delete_memory(row_id)
        assert deleted is True
        memories = await manager.get_memories(workspace="w")
        assert len(memories) == 0

    async def test_update_memory(self, manager: SessionManager) -> None:
        row_id = await manager.save_memory("Old content", workspace="w")
        updated = await manager.update_memory(row_id, "New content")
        assert updated is True
        memories = await manager.get_memories(workspace="w")
        assert memories[0].content == "New content"

    async def test_touch_memory(self, manager: SessionManager) -> None:
        row_id = await manager.save_memory("Touch me", workspace="w")
        await manager.touch_memory(row_id)
        await manager.touch_memory(row_id)
        memories = await manager.get_memories(workspace="w")
        assert memories[0].access_count == 2

    async def test_count_memories(self, manager: SessionManager) -> None:
        for i in range(5):
            await manager.save_memory(f"Memory {i}", workspace="w")
        count = await manager.count_memories(workspace="w")
        assert count == 5

    async def test_delete_memories_batch(self, manager: SessionManager) -> None:
        ids = []
        for i in range(5):
            row_id = await manager.save_memory(f"Mem {i}", workspace="w")
            ids.append(row_id)
        deleted = await manager.delete_memories(ids[:3])
        assert deleted == 3
        remaining = await manager.get_memories(workspace="w")
        assert len(remaining) == 2
