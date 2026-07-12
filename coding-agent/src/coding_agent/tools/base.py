"""Base types for the tool system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolResult:
    """Structured result returned by every tool execution."""

    success: bool
    output: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]


@runtime_checkable
class BaseTool(Protocol):
    """Interface every tool must satisfy."""

    name: str
    description: str
    parameters: dict[str, Any]
    permission_level: str

    async def execute(self, **kwargs: Any) -> ToolResult: ...
