"""Tool system — registry, base types, and schema inference."""

from coding_agent.tools import (
    count_tokens,  # noqa: F401 — registers count tokens tool
    file_ops,  # noqa: F401 — registers file tools
    git,  # noqa: F401 — registers git tools
    memory,  # noqa: F401 — registers memory tools
    planning,  # noqa: F401 — registers planning tools
    scratchpad,  # noqa: F401 — registers scratchpad tools
    search,  # noqa: F401 — registers search tools
    shell,  # noqa: F401 — registers shell tools
    subagent,  # noqa: F401 — registers delegate_task tool
    todo,  # noqa: F401 — registers todo tools
    undo,  # noqa: F401 — registers undo tools
    workspace,  # noqa: F401 — registers workspace tools
)
from coding_agent.tools.base import BaseTool, ToolResult
from coding_agent.tools.registry import (
    FunctionTool,
    ToolRegistry,
    tool,
    tool_registry,
)
from coding_agent.tools.schema import infer_schema

__all__ = [
    "BaseTool",
    "FunctionTool",
    "ToolRegistry",
    "ToolResult",
    "count_tokens",
    "file_ops",
    "git",
    "infer_schema",
    "memory",
    "planning",
    "scratchpad",
    "search",
    "shell",
    "subagent",
    "todo",
    "tool",
    "tool_registry",
    "undo",
]
