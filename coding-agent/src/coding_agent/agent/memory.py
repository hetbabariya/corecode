"""Cross-session memory system.

Provides episodic (session summaries), semantic (learned facts),
and working (current task state) memory.
"""

from __future__ import annotations

from pathlib import Path

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

    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager
        self._working: dict[str, str] = {}

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
        """Search persisted memories.

        If *query* is empty, returns the most recent memories.
        """
        if query:
            return await self._session_manager.search_memories(
                query,
                workspace=workspace,
                memory_type=memory_type,
                limit=limit,
            )
        return await self._session_manager.get_memories(
            workspace=workspace,
            memory_type=memory_type,
            limit=limit,
        )

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

        Recent semantic memories are listed first, followed by episodic.
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
        """Load recent memories and format them for the system prompt."""
        memories = await self._session_manager.get_memories(
            workspace=workspace,
            memory_type=None,
            limit=20,
        )
        return self.format_for_prompt(memories, max_tokens=max_tokens)

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
