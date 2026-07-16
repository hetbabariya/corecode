"""Cross-session memory system.

Provides episodic (session summaries), semantic (learned facts),
and working (current task state) memory with importance scoring,
consolidation, and pruning.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from coding_agent.logging import logger
from coding_agent.session.manager import MemoryRecord, SessionManager


class MemoryManager:
    """Manages cross-session memory backed by SQLite via SessionManager.

    Three memory types:
    - **episodic**: Session summaries (auto-generated at session end).
    - **semantic**: Learned facts and user preferences (explicit via
      ``remember`` tool or auto-extracted).
    - **working**: Ephemeral current-task state (not persisted to DB).
    """

    def __init__(
        self,
        session_manager: SessionManager,
        *,
        max_memories: int = 200,
        prune_threshold: float = 0.1,
    ) -> None:
        self._session_manager = session_manager
        self._working: dict[str, str] = {}
        self._max_memories = max_memories
        self._prune_threshold = prune_threshold

    # ------------------------------------------------------------------
    # Importance scoring
    # ------------------------------------------------------------------

    @staticmethod
    def score_memory(
        mem: MemoryRecord,
        *,
        now: datetime | None = None,
    ) -> float:
        """Score a memory by importance (0.0–1.0).

        Factors:
        - Base importance field (set by LLM via remember tool)
        - Recency decay (half-life ~1 week = 168h)
        - Access frequency (saturates at 10 accesses)
        - Tag bonus (tagged = more curated)
        """
        base = mem.importance

        # Recency decay
        recency_bonus = 0.0
        if mem.created_at:
            try:
                created = datetime.fromisoformat(mem.created_at)
                if now is None:
                    now = datetime.now(UTC)
                age_hours = max((now - created).total_seconds() / 3600, 0)
                recency_bonus = 0.3 * math.exp(-age_hours / 168)
            except (ValueError, TypeError):
                pass

        # Access frequency (saturates at 10)
        access_bonus = 0.2 * min(mem.access_count / 10, 1.0)

        # Tag bonus
        tag_bonus = 0.1 if mem.tags else 0.0

        return min(base + recency_bonus + access_bonus + tag_bonus, 1.0)

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    async def store(
        self,
        content: str,
        *,
        memory_type: str = "semantic",
        workspace: str = "",
        tags: list[str] | None = None,
        importance: float = 0.5,
        session_id: str | None = None,
    ) -> int:
        """Persist a memory and return its id.

        For ``memory_type="working"`` the record is kept only in memory
        and will *not* survive a restart.
        """
        if memory_type == "working":
            key = (tags or ["default"])[0]
            self._working[key] = content
            logger.debug("memory_stored_working", key=key)
            return -1

        row_id = await self._session_manager.save_memory(
            content,
            memory_type=memory_type,
            workspace=workspace,
            tags=tags,
            importance=importance,
            session_id=session_id,
        )
        logger.debug(
            "memory_stored",
            row_id=row_id,
            memory_type=memory_type,
            tags=tags,
        )
        return row_id

    # ------------------------------------------------------------------
    # Recall
    # ------------------------------------------------------------------

    async def recall(
        self,
        query: str = "",
        *,
        workspace: str = "",
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Search persisted memories, ranked by importance score.

        If *query* is empty, returns the most important memories.
        """
        if query:
            memories = await self._session_manager.search_memories(
                query,
                workspace=workspace,
                memory_type=memory_type,
                limit=limit * 2,  # over-fetch for scoring
            )
        else:
            memories = await self._session_manager.get_memories(
                workspace=workspace,
                memory_type=memory_type,
                limit=limit * 2,
            )

        # Score and rank
        now = datetime.now(UTC)
        scored = [(self.score_memory(m, now=now), m) for m in memories]
        scored.sort(key=lambda x: x[0], reverse=True)

        # Touch accessed memories
        for _, mem in scored[:limit]:
            await self._session_manager.touch_memory(mem.id)

        return [mem for _, mem in scored[:limit]]

    def get_working(self, key: str = "default") -> str | None:
        """Retrieve ephemeral working memory by key."""
        return self._working.get(key)

    def clear_working(self, key: str | None = None) -> None:
        """Clear working memory (all or by key)."""
        if key:
            self._working.pop(key, None)
        else:
            self._working.clear()

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def format_for_prompt(
        self,
        memories: list[MemoryRecord],
        *,
        max_tokens: int = 2000,
    ) -> str:
        """Format memories into a string suitable for the system prompt.

        Semantic memories listed first, followed by episodic.
        Truncates at *max_tokens* characters (rough estimate).
        """
        parts: list[str] = []

        semantic = [m for m in memories if m.memory_type == "semantic"]
        episodic = [m for m in memories if m.memory_type == "episodic"]

        if semantic:
            items = "\n".join(
                f"- {m.content}" for m in semantic[:15]
            )
            parts.append(f"Learned facts:\n{items}")

        if episodic:
            items = "\n".join(
                f"- {m.content}" for m in episodic[:5]
            )
            parts.append(f"Recent sessions:\n{items}")

        result = "\n\n".join(parts)

        # Rough truncation (4 chars per token)
        if len(result) > max_tokens * 4:
            result = result[: max_tokens * 4] + "\n..."

        return result

    async def build_prompt_content(
        self,
        *,
        workspace: str = "",
        max_tokens: int = 2000,
    ) -> str:
        """Load memories ranked by importance and format for the system prompt."""
        memories = await self._session_manager.get_memories(
            workspace=workspace,
            memory_type=None,
            limit=30,
        )
        # Score and rank by importance
        now = datetime.now(UTC)
        scored = [(self.score_memory(m, now=now), m) for m in memories]
        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = [m for _, m in scored]

        # Touch loaded memories
        for mem in ranked[:20]:
            await self._session_manager.touch_memory(mem.id)

        return self.format_for_prompt(ranked, max_tokens=max_tokens)

    # ------------------------------------------------------------------
    # Consolidation (D.1)
    # ------------------------------------------------------------------

    @staticmethod
    def _word_set(text: str) -> set[str]:
        """Extract lowercase word tokens for similarity comparison."""
        return set(re.findall(r"[a-z]+", text.lower()))

    @staticmethod
    def _jaccard(a: set[str], b: set[str]) -> float:
        """Jaccard similarity between two word sets."""
        if not a and not b:
            return 0.0
        return len(a & b) / len(a | b)

    @staticmethod
    def _merge_group(memories: list[MemoryRecord]) -> str:
        """Merge a group of similar memories into one summary."""
        if len(memories) == 1:
            return memories[0].content
        # Take the longest content as base, append unique points
        sorted_mems = sorted(memories, key=lambda m: len(m.content), reverse=True)
        base = sorted_mems[0].content
        base_words = MemoryManager._word_set(base)
        extras: list[str] = []
        for mem in sorted_mems[1:]:
            new_words = MemoryManager._word_set(mem.content) - base_words
            if new_words:
                extras.append(mem.content)
                base_words.update(new_words)
        if extras:
            return base + " | " + " | ".join(extras)
        return base

    async def consolidate_memories(
        self,
        workspace: str = "",
        threshold: int = 50,
    ) -> int:
        """Merge similar semantic memories when count exceeds *threshold*.

        Returns the number of original memories deleted.
        """
        memories = await self._session_manager.get_memories(
            workspace=workspace,
            memory_type="semantic",
            limit=500,
        )
        if len(memories) <= threshold:
            return 0

        # Group by tag overlap and content similarity
        groups: list[list[MemoryRecord]] = []
        used: set[int] = set()

        for i, mem_a in enumerate(memories):
            if mem_a.id in used:
                continue
            group = [mem_a]
            words_a = self._word_set(mem_a.content)
            tags_a = set(mem_a.tags)

            for mem_b in memories[i + 1:]:
                if mem_b.id in used:
                    continue
                # Tag overlap check
                tags_b = set(mem_b.tags)
                tag_overlap = bool(tags_a & tags_b) if tags_a and tags_b else False
                # Content similarity check
                words_b = self._word_set(mem_b.content)
                content_sim = self._jaccard(words_a, words_b)

                if tag_overlap or content_sim > 0.4:
                    group.append(mem_b)
                    used.add(mem_b.id)

            if len(group) >= 2:
                groups.append(group)
                used.add(mem_a.id)

        if not groups:
            return 0

        deleted = 0
        for group in groups:
            merged = self._merge_group(group)
            # Store merged memory
            all_tags: list[str] = []
            for m in group:
                all_tags.extend(m.tags)
            unique_tags = list(dict.fromkeys(all_tags))  # dedupe preserving order

            await self.store(
                merged,
                memory_type="semantic",
                workspace=workspace,
                tags=unique_tags[:5],
                importance=max(m.importance for m in group),
            )
            # Delete originals
            ids = [m.id for m in group]
            deleted += await self._session_manager.delete_memories(ids)

        logger.info(
            "memories_consolidated",
            workspace=workspace,
            groups=len(groups),
            deleted=deleted,
        )
        return deleted

    # ------------------------------------------------------------------
    # Pruning (D.4)
    # ------------------------------------------------------------------

    async def prune_memories(self, workspace: str = "") -> int:
        """Drop old, low-value memories to prevent unbounded growth.

        Returns the number of memories deleted.
        """
        count = await self._session_manager.count_memories(
            workspace=workspace, memory_type="semantic"
        )
        if count <= self._max_memories:
            return 0

        memories = await self._session_manager.get_memories(
            workspace=workspace,
            memory_type="semantic",
            limit=count,
        )

        # Score all memories
        now = datetime.now(UTC)
        scored = [(self.score_memory(m, now=now), m) for m in memories]
        scored.sort(key=lambda x: x[0])

        # Determine how many to delete
        to_delete = count - self._max_memories
        deleted_ids: list[int] = []

        for score, mem in scored:
            if len(deleted_ids) >= to_delete:
                break
            # Never delete explicitly important memories
            if mem.importance >= 0.8:
                continue
            # Never delete below threshold if already under limit
            if score < self._prune_threshold:
                deleted_ids.append(mem.id)
            elif len(deleted_ids) < to_delete:
                deleted_ids.append(mem.id)

        if deleted_ids:
            deleted = await self._session_manager.delete_memories(deleted_ids)
            logger.info(
                "memories_pruned",
                workspace=workspace,
                deleted=deleted,
                remaining=count - deleted,
            )
            return deleted

        return 0

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def save_episodic(
        self,
        summary: str,
        *,
        workspace: str = "",
        session_id: str | None = None,
    ) -> int:
        """Save an episodic memory (session summary) at session end."""
        return await self.store(
            summary,
            memory_type="episodic",
            workspace=workspace,
            tags=["session_summary"],
            session_id=session_id,
        )

    async def delete(self, memory_id: int) -> bool:
        """Delete a memory by id."""
        return await self._session_manager.delete_memory(memory_id)

    async def update(self, memory_id: int, content: str) -> bool:
        """Update memory content."""
        return await self._session_manager.update_memory(memory_id, content)
