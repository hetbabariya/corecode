"""Tool registry, function adapter, and ``@tool`` decorator."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

from coding_agent.logging import logger
from coding_agent.tools.base import BaseTool, ToolResult
from coding_agent.tools.schema import infer_schema


class ToolRegistry:
    """Registry that holds and dispatches tools.

    Create custom registries for testing, plugins, or multi-agent setups::

        my_registry = ToolRegistry(name="plugins")

    Or use the module-level ``tool_registry`` singleton for convenience.
    """

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._tools: dict[str, BaseTool] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, tool: BaseTool) -> None:
        """Register a tool.  Overwrites if the name already exists."""
        self._tools[tool.name] = tool
        logger.debug(
            "tool_registered",
            registry=self.name,
            tool=tool.name,
        )

    def unregister(self, name: str) -> None:
        """Remove a tool by name.  Raises ``KeyError`` if not found."""
        if name not in self._tools:
            raise KeyError(f"Tool {name!r} not found in registry {self.name!r}")
        del self._tools[name]
        logger.debug("tool_unregistered", registry=self.name, tool=name)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> BaseTool:
        """Return a tool by name.  Raises ``KeyError`` if not found."""
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(
                f"Tool {name!r} not found. Available: {sorted(self._tools.keys())}"
            ) from None

    def list_tools(self) -> list[str]:
        """Return sorted tool names."""
        return sorted(self._tools.keys())

    # ------------------------------------------------------------------
    # Schema generation (for LLM consumption)
    # ------------------------------------------------------------------

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return all tool schemas in OpenAI function-calling format."""
        return [self.get_schema(name) for name in self.list_tools()]

    def get_schema(self, name: str) -> dict[str, Any]:
        """Return a single tool's schema in OpenAI function-calling format."""
        t = self.get(name)
        return {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Dispatch *arguments* to the tool named *name*.

        Returns ``ToolResult(success=False, ...)`` on error instead of raising,
        so the agent loop can feed the error back to the LLM.
        """
        try:
            tool = self.get(name)
        except KeyError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
            )

        try:
            result = await tool.execute(**arguments)
            logger.info(
                "tool_executed",
                registry=self.name,
                tool=name,
                success=result.success,
            )
            return result
        except Exception as exc:
            logger.error(
                "tool_failed",
                registry=self.name,
                tool=name,
                error=str(exc),
            )
            return ToolResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def execute_from_llm(
        self,
        tool_call: dict[str, Any],
    ) -> ToolResult:
        """Execute from an LLM tool-call dict.

        Accepts the standard OpenAI format::

            {
                "id": "call_0",
                "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": "{\"path\": \"main.py\"}"
                }
            }
        """
        fn: dict[str, Any] = tool_call.get("function", {})
        name: str = fn.get("name", "")
        raw_args: str = fn.get("arguments", "{}")

        try:
            arguments: dict[str, Any] = json.loads(raw_args)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                error=f"Invalid JSON in tool arguments: {raw_args!r}",
            )

        if not name:
            return ToolResult(
                success=False,
                error="Tool call missing function name",
            )

        return await self.execute(name, arguments)


class FunctionTool:
    """Adapter that wraps a plain async function as a :class:`BaseTool`."""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        permission_level: str = "read",
    ) -> None:
        self._func = func
        self.name = name
        self.description = description
        self.parameters = parameters
        self.permission_level = permission_level

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Call the wrapped function and wrap the result in :class:`ToolResult`."""
        try:
            result = await self._func(**kwargs)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        if isinstance(result, ToolResult):
            return result
        return ToolResult(success=True, output=str(result))

    @property
    def __wrapped__(self) -> Callable[..., Any]:
        """Return the original function (useful for direct calls in tests)."""
        return self._func


# ------------------------------------------------------------------
# @tool decorator
# ------------------------------------------------------------------


def tool(
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
    permission: str = "read",
    registry: ToolRegistry | None = None,
) -> Callable[[Callable[..., Any]], FunctionTool]:
    """Decorator that registers an async function as a tool.

    ::

        @tool(name="read_file", description="Read a file", permission="read")
        async def read_file(path: str) -> str:
            ...

    Parameters
    ----------
    name:
        Tool name shown to the LLM.  Defaults to ``func.__name__``.
    description:
        Tool description.  Defaults to ``func.__doc__`` (stripped).
    parameters:
        Explicit JSON Schema for parameters.  ``None`` = auto-infer from
        type hints (the common case).
    permission:
        Permission level: ``"read"`` | ``"write"`` | ``"execute"`` | ``"dangerous"``.
    registry:
        Which registry to register with.  ``None`` = the default singleton.
    """

    def decorator(func: Callable[..., Any]) -> FunctionTool:
        tool_name = name or func.__name__
        tool_desc = description or (inspect.getdoc(func) or "").strip()
        tool_params = parameters if parameters is not None else infer_schema(func)

        ft = FunctionTool(
            func,
            name=tool_name,
            description=tool_desc,
            parameters=tool_params,
            permission_level=permission,
        )

        target = registry if registry is not None else tool_registry
        target.register(ft)
        return ft

    return decorator


# ------------------------------------------------------------------
# Default singleton
# ------------------------------------------------------------------

tool_registry = ToolRegistry(name="default")
