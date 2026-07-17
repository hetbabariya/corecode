"""Tool registry, function adapter, and ``@tool`` decorator."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
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

        Applies a timeout based on the tool's explicit ``timeout_seconds``
        (if set), falling back to the config default for the tool's permission
        level, then to a global 30 s fallback.
        """
        exec_start = time.monotonic()
        try:
            tool = self.get(name)
        except KeyError as exc:
            logger.warning("tool_not_found", tool=name, available=self.list_tools())
            return ToolResult(
                success=False,
                error=str(exc),
            )

        # Resolve timeout: overrides → tool-level → config default for permission level
        from coding_agent.config import Settings

        settings = Settings()
        tool_timeout: float | None = None

        # 1. Per-tool name override from config
        if name in settings.tool_timeout_overrides:
            tool_timeout = settings.tool_timeout_overrides[name]
        else:
            # 2. Tool-level explicit timeout
            tool_timeout_attr = getattr(tool, "timeout_seconds", None)
            if tool_timeout_attr is not None:
                tool_timeout = tool_timeout_attr
            else:
                # 3. Config default for permission level
                tool_timeout = settings.get_tool_timeout(
                    getattr(tool, "permission_level", "read")
                )

        # Timeout <= 0 disables the timeout
        use_timeout = tool_timeout if tool_timeout and tool_timeout > 0 else None

        try:
            result = await asyncio.wait_for(
                tool.execute(**arguments),
                timeout=use_timeout,
            )
            duration_ms = (time.monotonic() - exec_start) * 1000
            logger.info(
                "tool_executed",
                registry=self.name,
                tool=name,
                success=result.success,
                duration_ms=round(duration_ms, 1),
                output_length=len(result.output) if result.output else 0,
                error=result.error[:200] if result.error else "",
            )
            return result
        except TimeoutError:
            duration_ms = (time.monotonic() - exec_start) * 1000
            retryable = getattr(tool, "retryable", True)
            logger.warning(
                "tool_timeout",
                registry=self.name,
                tool=name,
                timeout_s=tool_timeout,
                duration_ms=round(duration_ms, 1),
                retryable=retryable,
            )
            if isinstance(tool, FunctionTool):
                await tool.run_cleanup()
            return ToolResult(
                success=False,
                error=f"Tool '{name}' timed out after {tool_timeout}s",
                metadata={
                    "timeout": True,
                    "timeout_s": tool_timeout,
                    "actual_duration_ms": round(duration_ms, 1),
                    "retryable": retryable,
                },
            )
        except asyncio.CancelledError:
            duration_ms = (time.monotonic() - exec_start) * 1000
            logger.info(
                "tool_cancelled",
                registry=self.name,
                tool=name,
                duration_ms=round(duration_ms, 1),
            )
            if isinstance(tool, FunctionTool):
                await tool.run_cleanup()
            raise
        except Exception as exc:
            duration_ms = (time.monotonic() - exec_start) * 1000
            logger.error(
                "tool_failed",
                registry=self.name,
                tool=name,
                error=str(exc),
                duration_ms=round(duration_ms, 1),
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
            logger.warning("tool_args_parse_failed", tool=name, raw_args=raw_args[:200])
            return ToolResult(
                success=False,
                error=f"Invalid JSON in tool arguments: {raw_args!r}",
            )

        if not name:
            logger.warning("tool_name_missing", raw_args=raw_args[:200])
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
        timeout: float | None = None,
        retryable: bool = True,
        idle_timeout: float | None = None,
        cleanup: Callable[[], Any] | None = None,
    ) -> None:
        self._func = func
        self.name = name
        self.description = description
        self.parameters = parameters
        self.permission_level = permission_level
        self.timeout_seconds = timeout
        self.retryable = retryable
        self.idle_timeout = idle_timeout
        self._cleanup = cleanup

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

    async def run_cleanup(self) -> None:
        """Run the cleanup callback if one was provided.

        Called by the registry on timeout or cancellation.  Errors are
        logged but not propagated.
        """
        if self._cleanup is None:
            return
        try:
            result = self._cleanup()
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            logger.warning("tool_cleanup_error", tool=self.name, error=str(exc))

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
    timeout: float | None = None,
    retryable: bool = True,
    idle_timeout: float | None = None,
    cleanup: Callable[[], Any] | None = None,
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
    timeout:
        Maximum execution time in seconds.  ``None`` = use config default
        for the permission level.
    retryable:
        Whether the tool is safe to retry after timeout.  Defaults to True.
    idle_timeout:
        Max seconds the tool can run without producing output.  ``None`` =
        no idle monitoring.  Stored on the :class:`FunctionTool` for
        consumers to use.
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
            timeout=timeout,
            retryable=retryable,
            idle_timeout=idle_timeout,
            cleanup=cleanup,
        )

        target = registry if registry is not None else tool_registry
        target.register(ft)
        return ft

    return decorator


# ------------------------------------------------------------------
# Default singleton
# ------------------------------------------------------------------

tool_registry = ToolRegistry(name="default")
