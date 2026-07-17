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
    """Interface every tool must satisfy.

    Attributes
    ----------
    name:
        Unique tool identifier used in function-calling schemas.
    description:
        Human-readable description shown to the LLM.
    parameters:
        JSON Schema describing the tool's parameters.
    permission_level:
        Access tier (``"read"``, ``"write"``, ``"execute"``, ``"dangerous"``).
    timeout:
        Optional per-tool timeout in seconds.  Overrides the global default
        for the tool's permission level.  ``None`` uses the config default.
    retryable:
        Whether the tool can be retried after a timeout or transient error.
        Write-destructive tools (``write_file``, ``edit_file``, etc.) should
        set this to ``False``.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    permission_level: str

    async def execute(self, **kwargs: Any) -> ToolResult: ...
