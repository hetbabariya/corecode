"""Scratchpad tool — persistent working notes visible in the system prompt.

The scratchpad lets the LLM maintain working notes across turns without
needing to re-read files or remember context. Content is stored in-memory
and injected into the system prompt on every turn.
"""

from __future__ import annotations

from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool

_content: str = ""


def get_scratchpad_content() -> str:
    """Return the current scratchpad content (for prompt injection)."""
    return _content


def set_scratchpad_content(content: str) -> None:
    """Set scratchpad content (used by loop for reset)."""
    global _content
    _content = content


@tool(
    name="read_scratchpad",
    description="Read your current scratchpad notes. The scratchpad is always visible in the system prompt, so you only need this tool if you want a clean copy of the text.",
    permission="read",
)
async def read_scratchpad() -> ToolResult:
    """Read the current scratchpad content."""
    if not _content:
        return ToolResult(success=True, output="Scratchpad is empty.")
    return ToolResult(success=True, output=_content)


@tool(
    name="update_scratchpad",
    description="Replace your entire scratchpad with new content. Use this to write down your current plan, findings, reasoning, or next steps. This overwrites any existing content.",
    permission="read",
)
async def update_scratchpad(content: str) -> ToolResult:
    """Replace scratchpad content.

    Parameters
    ----------
    content:
        The new scratchpad content. This replaces all existing notes.
    """
    global _content
    _content = content
    length = len(content)
    return ToolResult(success=True, output=f"Scratchpad updated ({length} chars).")


@tool(
    name="append_scratchpad",
    description="Append text to your existing scratchpad. Use this to add new findings or notes without losing what's already there.",
    permission="read",
)
async def append_scratchpad(content: str) -> ToolResult:
    """Append to scratchpad content.

    Parameters
    ----------
    content:
        Text to append to existing scratchpad.
    """
    global _content
    if _content and not _content.endswith("\n"):
        _content += "\n"
    _content += content
    length = len(_content)
    return ToolResult(success=True, output=f"Appended. Scratchpad now {length} chars.")


@tool(
    name="clear_scratchpad",
    description="Clear all scratchpad content. Use this to start fresh when switching tasks.",
    permission="read",
)
async def clear_scratchpad() -> ToolResult:
    """Clear all scratchpad content."""
    global _content
    was_empty = not _content
    _content = ""
    if was_empty:
        return ToolResult(success=True, output="Scratchpad was already empty.")
    return ToolResult(success=True, output="Scratchpad cleared.")
