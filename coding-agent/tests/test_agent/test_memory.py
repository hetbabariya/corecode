"""Tests for MemoryManager — importance scoring, consolidation, pruning."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from coding_agent.agent.memory import MemoryManager
from coding_agent.session.manager import MemoryRecord, SessionManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_mgr(tmp_path: Path) -> SessionManager:
    mgr = SessionManager(tmp_path / "test.db")
    await mgr.initialize()
    return mgr


@pytest_asyncio.fixture
async def memory_mgr(session_mgr: SessionManager) -> MemoryManager:
    return MemoryManager(session_mgr, max_memories=10, prune_threshold=0.1)


# ---------------------------------------------------------------------------
# Importance scoring
# ---------------------------------------------------------------------------


class TestImportanceScoring:
    """Tests for MemoryManager.score_memory()."""

    def _make_mem(
        self,
        content: str = "test",
        *,
        importance: float = 0.5,
        tags: list[str] | None = None,
        created_hours_ago: float = 0,
        access_count: int = 0,
    ) -> MemoryRecord:
        now = datetime.now(UTC)
        created = now - timedelta(hours=created_hours_ago)
        return MemoryRecord(
            id=1,
            workspace="test",
            memory_type="semantic",
            content=content,
            tags=tags or [],
            session_id=None,
            created_at=created.isoformat(),
            updated_at=now.isoformat(),
            importance=importance,
            access_count=access_count,
        )

    def test_base_importance(self):
        mem = self._make_mem(importance=0.8)
        score = MemoryManager.score_memory(mem)
        assert score >= 0.8

    def test_recency_bonus(self):
        fresh = self._make_mem(importance=0.5, created_hours_ago=0)
        old = self._make_mem(importance=0.5, created_hours_ago=168 * 4)  # 4 weeks
        assert MemoryManager.score_memory(fresh) > MemoryManager.score_memory(old)

    def test_access_bonus(self):
        never = self._make_mem(importance=0.5, access_count=0)
        frequent = self._make_mem(importance=0.5, access_count=10)
        assert MemoryManager.score_memory(frequent) > MemoryManager.score_memory(never)

    def test_tag_bonus(self):
        untagged = self._make_mem(importance=0.5, tags=[])
        tagged = self._make_mem(importance=0.5, tags=["python"])
        assert MemoryManager.score_memory(tagged) > MemoryManager.score_memory(untagged)

    def test_score_capped_at_one(self):
        mem = self._make_mem(importance=1.0, tags=["x"], access_count=100)
        score = MemoryManager.score_memory(mem)
        assert score <= 1.0

    def test_low_importance_old_memory(self):
        mem = self._make_mem(importance=0.0, created_hours_ago=168 * 8)
        score = MemoryManager.score_memory(mem)
        assert score < 0.3


# ---------------------------------------------------------------------------
# Consolidation
# ---------------------------------------------------------------------------


class TestConsolidation:
    """Tests for MemoryManager.consolidate_memories()."""

    @pytest.mark.asyncio
    async def test_no_consolidation_under_threshold(self, memory_mgr: MemoryManager):
        for i in range(5):
            await memory_mgr.store(f"Memory {i}", workspace="w")
        deleted = await memory_mgr.consolidate_memories(workspace="w", threshold=10)
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_consolidation_merges_similar(self, memory_mgr: MemoryManager):
        # Store similar memories (share tags)
        for i in range(12):
            await memory_mgr.store(
                f"Python uses indentation for blocks",
                workspace="w",
                tags=["python", "style"],
            )
        deleted = await memory_mgr.consolidate_memories(workspace="w", threshold=5)
        assert deleted > 0
        # Should have fewer memories after consolidation
        remaining = await memory_mgr._session_manager.count_memories(workspace="w")
        assert remaining < 12

    @pytest.mark.asyncio
    async def test_consolidation_preserves_truly_unique(self, memory_mgr: MemoryManager):
        # Store truly unique memories with no word overlap
        unique_texts = [
            "User prefers dark mode theme for IDE",
            "Cerebras API uses gpt-oss-120b model for completions",
            "Database files stored in ~/.local/share/agent/",
            "Always run linter before committing changes",
            "OpenRouter key expires December 2025",
            "Project uses TypeScript strict mode throughout",
            "Deployment requires SSH access to remote server",
            "Package manager is npm not yarn for this project",
            "Test framework uses pytest with async fixtures",
            "Build output goes to dist/ directory automatically",
            "Git hooks enforce commit message format rules",
            "Code style uses 4-space indentation for Python",
        ]
        for i, text in enumerate(unique_texts):
            await memory_mgr.store(text, workspace="w", tags=[f"topic_{i}"])
        deleted = await memory_mgr.consolidate_memories(workspace="w", threshold=5)
        # Truly unique memories should NOT be heavily consolidated
        remaining = await memory_mgr._session_manager.count_memories(workspace="w")
        assert remaining >= 8, f"Expected >= 8 remaining, got {remaining}"


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


class TestPruning:
    """Tests for MemoryManager.prune_memories()."""

    @pytest.mark.asyncio
    async def test_no_pruning_under_limit(self, memory_mgr: MemoryManager):
        for i in range(5):
            await memory_mgr.store(f"Memory {i}", workspace="w")
        deleted = await memory_mgr.prune_memories(workspace="w")
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_pruning_drops_lowest(self, memory_mgr: MemoryManager):
        # Fill beyond max_memories (10)
        for i in range(15):
            await memory_mgr.store(
                f"Memory {i}",
                workspace="w",
                importance=0.1 if i < 5 else 0.9,
            )
        deleted = await memory_mgr.prune_memories(workspace="w")
        assert deleted > 0

    @pytest.mark.asyncio
    async def test_pruning_preserves_important(self, memory_mgr: MemoryManager):
        # Store an important memory
        important_id = await memory_mgr.store(
            "Critical fact",
            workspace="w",
            importance=0.9,
        )
        # Fill beyond limit with low-importance memories
        for i in range(15):
            await memory_mgr.store(
                f"Low importance {i}",
                workspace="w",
                importance=0.05,
            )
        await memory_mgr.prune_memories(workspace="w")
        # Important memory should still exist
        remaining = await memory_mgr._session_manager.get_memories(workspace="w")
        remaining_ids = [m.id for m in remaining]
        assert important_id in remaining_ids


# ---------------------------------------------------------------------------
# Store with importance
# ---------------------------------------------------------------------------


class TestStoreWithImportance:
    """Tests for MemoryManager.store() with importance parameter."""

    @pytest.mark.asyncio
    async def test_store_with_importance(self, memory_mgr: MemoryManager):
        row_id = await memory_mgr.store(
            "Important fact",
            workspace="w",
            importance=0.9,
        )
        assert row_id > 0
        memories = await memory_mgr._session_manager.get_memories(workspace="w")
        assert len(memories) == 1
        assert memories[0].importance == 0.9

    @pytest.mark.asyncio
    async def test_store_working_not_persisted(self, memory_mgr: MemoryManager):
        row_id = await memory_mgr.store(
            "Working memory",
            memory_type="working",
            tags=["temp"],
        )
        assert row_id == -1
        assert memory_mgr.get_working("temp") == "Working memory"

    @pytest.mark.asyncio
    async def test_recall_returns_scored(self, memory_mgr: MemoryManager):
        await memory_mgr.store("Old fact", workspace="w", importance=0.3)
        await memory_mgr.store("New fact", workspace="w", importance=0.9)
        results = await memory_mgr.recall(workspace="w")
        assert len(results) >= 1
        # Most important should be first
        assert results[0].importance >= results[-1].importance


# ---------------------------------------------------------------------------
# Plan persistence
# ---------------------------------------------------------------------------


class TestPlanPersistence:
    """Tests for SessionManager plan CRUD."""

    @pytest.mark.asyncio
    async def test_save_and_load_plan(self, session_mgr: SessionManager):
        steps = [
            {"description": "Step 1", "status": "completed", "result": "done"},
            {"description": "Step 2", "status": "in_progress", "result": ""},
        ]
        plan_id = await session_mgr.save_plan(
            workspace="w",
            goal="Test goal",
            steps=steps,
            current_step=1,
            status="executing",
        )
        assert plan_id > 0

        loaded = await session_mgr.load_active_plan("w")
        assert loaded is not None
        assert loaded["goal"] == "Test goal"
        assert loaded["current_step"] == 1
        assert len(loaded["steps"]) == 2

    @pytest.mark.asyncio
    async def test_upsert_plan(self, session_mgr: SessionManager):
        await session_mgr.save_plan(
            workspace="w", goal="V1", steps=[], current_step=0, status="executing"
        )
        await session_mgr.save_plan(
            workspace="w", goal="V2", steps=[], current_step=1, status="executing"
        )
        loaded = await session_mgr.load_active_plan("w")
        assert loaded is not None
        assert loaded["goal"] == "V2"

    @pytest.mark.asyncio
    async def test_complete_plan(self, session_mgr: SessionManager):
        plan_id = await session_mgr.save_plan(
            workspace="w", goal="Done", steps=[], current_step=0, status="executing"
        )
        await session_mgr.complete_plan(plan_id)
        loaded = await session_mgr.load_active_plan("w")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_no_plan(self, session_mgr: SessionManager):
        loaded = await session_mgr.load_active_plan("nonexistent")
        assert loaded is None
