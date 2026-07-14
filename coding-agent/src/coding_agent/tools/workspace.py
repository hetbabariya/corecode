"""Workspace tools: refresh_index.

Lets the agent re-scan the workspace when needed.
"""

from __future__ import annotations

from typing import Any

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool

# Module-level reference set by the agent loop on initialization.
_workspace_index: Any = None


def set_workspace_index(index: Any) -> None:
    """Set the global workspace index reference (called by AgentLoop)."""
    global _workspace_index
    _workspace_index = index


def get_workspace_index() -> Any:
    """Return the current workspace index."""
    return _workspace_index


@tool(
    name="refresh_index",
    description=(
        "Re-scan the workspace to get an updated file tree. "
        "Use this after creating or deleting many files, or if the "
        "file tree in the system prompt seems outdated."
    ),
    permission="read",
)
async def refresh_index() -> ToolResult:
    """Re-scan the workspace and return updated stats."""
    from pathlib import Path

    index = get_workspace_index()
    if index is None:
        return ToolResult(
            success=False,
            error="Workspace index not available. This is an internal error.",
        )

    index.scan(Path("."))
    stats = index.get_language_stats()
    top_langs = ", ".join(f"{lang}({count})" for lang, count in list(stats.items())[:5])

    logger.debug("refresh_index_done", files=index.total_files, dirs=index.get_dir_count())
    return ToolResult(
        success=True,
        output=(
            f"Workspace re-scanned.\n"
            f"Files: {index.total_files}\n"
            f"Directories: {index.get_dir_count()}\n"
            f"Languages: {top_langs}\n"
            f"Approximate lines: {index.total_lines}"
        ),
        metadata=index.to_dict(),
    )
