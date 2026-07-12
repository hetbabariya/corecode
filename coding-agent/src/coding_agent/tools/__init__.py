"""Tool system — registry, base types, and schema inference."""

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
    "infer_schema",
    "tool",
    "tool_registry",
]
