"""Tool system — registry, base types, and schema inference."""

from coding_agent.tools import (
    file_ops,  # noqa: F401 — registers file tools
    git,  # noqa: F401 — registers git tools
    search,  # noqa: F401 — registers search tools
    shell,  # noqa: F401 — registers shell tools
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
    "file_ops",
    "git",
    "infer_schema",
    "search",
    "shell",
    "tool",
    "tool_registry",
]
