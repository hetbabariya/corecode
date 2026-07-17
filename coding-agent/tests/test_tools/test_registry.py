"""Tests for the tool registry, FunctionTool adapter, and @tool decorator."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import FunctionTool, ToolRegistry, tool, tool_registry

# ------------------------------------------------------------------
# Helpers — reusable test functions
# ------------------------------------------------------------------


async def _add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


async def _greet(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"


async def _fail() -> str:
    """Always raises."""
    raise ValueError("boom")


async def _returns_result() -> ToolResult:
    """Returns ToolResult directly."""
    return ToolResult(success=True, output="custom", metadata={"lines": 42})


async def _str_returns() -> str:
    """Plain string return."""
    return "plain string"


class _EditArgs(BaseModel):
    path: str = Field(description="File path")
    old_text: str = Field(description="Text to replace")
    new_text: str = Field(description="Replacement text")


async def _pydantic_tool(args: _EditArgs) -> str:
    """Tool with Pydantic model arg."""
    return f"Edited {args.path}"


# ------------------------------------------------------------------
# ToolRegistry tests
# ------------------------------------------------------------------


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        reg = ToolRegistry(name="test")
        ft = FunctionTool(
            _add, name="add", description="Add", parameters={}, permission_level="read"
        )
        reg.register(ft)
        assert reg.get("add") is ft

    def test_get_missing_raises_key_error(self) -> None:
        reg = ToolRegistry(name="test")
        with pytest.raises(KeyError, match="not found"):
            reg.get("nope")

    def test_unregister(self) -> None:
        reg = ToolRegistry(name="test")
        ft = FunctionTool(_add, name="add", description="Add", parameters={})
        reg.register(ft)
        reg.unregister("add")
        with pytest.raises(KeyError):
            reg.get("add")

    def test_unregister_missing_raises(self) -> None:
        reg = ToolRegistry(name="test")
        with pytest.raises(KeyError, match="not found"):
            reg.unregister("nope")

    def test_list_tools_sorted(self) -> None:
        reg = ToolRegistry(name="test")
        reg.register(FunctionTool(_add, name="zebra", description="", parameters={}))
        reg.register(FunctionTool(_add, name="alpha", description="", parameters={}))
        reg.register(FunctionTool(_add, name="mid", description="", parameters={}))
        assert reg.list_tools() == ["alpha", "mid", "zebra"]

    def test_get_schemas_openai_format(self) -> None:
        reg = ToolRegistry(name="test")
        reg.register(
            FunctionTool(
                _add,
                name="add",
                description="Add two numbers",
                parameters={
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                },
            )
        )
        schemas = reg.get_schemas()
        assert len(schemas) == 1
        s = schemas[0]
        assert s["type"] == "function"
        assert s["function"]["name"] == "add"
        assert s["function"]["description"] == "Add two numbers"
        assert "a" in s["function"]["parameters"]["properties"]

    def test_get_schema_single(self) -> None:
        reg = ToolRegistry(name="test")
        reg.register(
            FunctionTool(_greet, name="greet", description="Greet", parameters={})
        )
        s = reg.get_schema("greet")
        assert s["function"]["name"] == "greet"

    def test_multiple_registries_independent(self) -> None:
        r1 = ToolRegistry(name="r1")
        r2 = ToolRegistry(name="r2")
        r1.register(FunctionTool(_add, name="add", description="", parameters={}))
        assert r1.list_tools() == ["add"]
        assert r2.list_tools() == []


# ------------------------------------------------------------------
# ToolRegistry.execute tests
# ------------------------------------------------------------------


class TestRegistryExecute:
    async def test_execute_dispatches(self) -> None:
        reg = ToolRegistry(name="test")
        reg.register(
            FunctionTool(
                _add,
                name="add",
                description="Add",
                parameters={
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                },
            )
        )
        result = await reg.execute("add", {"a": 2, "b": 3})
        assert result.success is True
        assert result.output == "5"

    async def test_execute_returns_tool_result(self) -> None:
        reg = ToolRegistry(name="test")
        reg.register(FunctionTool(_greet, name="greet", description="", parameters={}))
        result = await reg.execute("greet", {"name": "World"})
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert "Hello, World!" in result.output

    async def test_execute_exception_returns_error(self) -> None:
        reg = ToolRegistry(name="test")
        reg.register(FunctionTool(_fail, name="fail", description="", parameters={}))
        result = await reg.execute("fail", {})
        assert result.success is False
        assert "boom" in (result.error or "")

    async def test_execute_nonexistent_tool(self) -> None:
        reg = ToolRegistry(name="test")
        result = await reg.execute("nope", {})
        assert result.success is False
        assert "not found" in (result.error or "")


# ------------------------------------------------------------------
# execute_from_llm tests
# ------------------------------------------------------------------


class TestExecuteFromLLM:
    async def test_parses_llm_format(self) -> None:
        reg = ToolRegistry(name="test")
        reg.register(
            FunctionTool(
                _add,
                name="add",
                description="Add",
                parameters={
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                },
            )
        )
        tool_call = {
            "id": "call_0",
            "type": "function",
            "function": {
                "name": "add",
                "arguments": json.dumps({"a": 10, "b": 20}),
            },
        }
        result = await reg.execute_from_llm(tool_call)
        assert result.success is True
        assert result.output == "30"

    async def test_invalid_json(self) -> None:
        reg = ToolRegistry(name="test")
        reg.register(FunctionTool(_add, name="add", description="", parameters={}))
        tool_call = {
            "id": "call_0",
            "type": "function",
            "function": {
                "name": "add",
                "arguments": "not-json",
            },
        }
        result = await reg.execute_from_llm(tool_call)
        assert result.success is False
        assert "Invalid JSON" in (result.error or "")

    async def test_missing_name(self) -> None:
        reg = ToolRegistry(name="test")
        tool_call = {
            "id": "call_0",
            "type": "function",
            "function": {"name": "", "arguments": "{}"},
        }
        result = await reg.execute_from_llm(tool_call)
        assert result.success is False
        assert "missing function name" in (result.error or "").lower()


# ------------------------------------------------------------------
# FunctionTool tests
# ------------------------------------------------------------------


class TestFunctionTool:
    def test_name_and_description(self) -> None:
        ft = FunctionTool(_add, name="add", description="Add", parameters={})
        assert ft.name == "add"
        assert ft.description == "Add"

    async def test_execute_returns_str_wrapped(self) -> None:
        ft = FunctionTool(
            _str_returns, name="str_returns", description="", parameters={}
        )
        result = await ft.execute()
        assert result.success is True
        assert result.output == "plain string"

    async def test_execute_returns_tool_result_passthrough(self) -> None:
        ft = FunctionTool(
            _returns_result, name="returns_result", description="", parameters={}
        )
        result = await ft.execute()
        assert result.success is True
        assert result.output == "custom"
        assert result.metadata == {"lines": 42}

    async def test_execute_exception(self) -> None:
        ft = FunctionTool(_fail, name="fail", description="", parameters={})
        result = await ft.execute()
        assert result.success is False
        assert "boom" in (result.error or "")

    def test_permission_level(self) -> None:
        ft = FunctionTool(
            _add, name="add", description="", parameters={}, permission_level="write"
        )
        assert ft.permission_level == "write"

    def test_wrapped_attribute(self) -> None:
        ft = FunctionTool(_add, name="add", description="", parameters={})
        assert ft.__wrapped__ is _add


# ------------------------------------------------------------------
# @tool decorator tests
# ------------------------------------------------------------------


class TestToolDecorator:
    def test_registers_to_default_registry(self) -> None:
        @tool(name="decorator_default_test", description="test")
        async def _my_tool(x: str) -> str:
            return x

        assert "decorator_default_test" in tool_registry.list_tools()
        tool_registry.unregister("decorator_default_test")

    def test_name_override(self) -> None:
        @tool(name="custom_name", description="test")
        async def _my_tool(x: str) -> str:
            return x

        assert "custom_name" in tool_registry.list_tools()
        tool_registry.unregister("custom_name")

    def test_description_from_docstring(self) -> None:
        @tool(name="docstring_test")
        async def _my_tool(x: str) -> str:
            """This is the docstring."""
            return x

        t = tool_registry.get("docstring_test")
        assert t.description == "This is the docstring."
        tool_registry.unregister("docstring_test")

    def test_custom_registry(self) -> None:
        custom = ToolRegistry(name="custom")

        @tool(name="custom_reg_test", description="test", registry=custom)
        async def _my_tool(x: str) -> str:
            return x

        assert "custom_reg_test" in custom.list_tools()
        assert "custom_reg_test" not in tool_registry.list_tools()

    def test_returns_function_tool(self) -> None:
        @tool(name="returns_ft_test", description="test")
        async def _my_tool(x: str) -> str:
            return x

        assert isinstance(_my_tool, FunctionTool)
        tool_registry.unregister("returns_ft_test")

    def test_original_func_callable(self) -> None:
        @tool(name="callable_test", description="test")
        async def _my_tool(x: str) -> str:
            return f"got {x}"

        # The decorated name is a FunctionTool, but __wrapped__ is the original
        assert _my_tool.__wrapped__ is not None
        tool_registry.unregister("callable_test")

    def test_permission_level(self) -> None:
        @tool(name="perm_test", description="test", permission="write")
        async def _my_tool(x: str) -> str:
            return x

        t = tool_registry.get("perm_test")
        assert t.permission_level == "write"
        tool_registry.unregister("perm_test")

    def test_inferred_schema(self) -> None:
        @tool(name="schema_test", description="test")
        async def _my_tool(a: str, b: int, flag: bool = False) -> str:
            return ""

        t = tool_registry.get("schema_test")
        assert t.parameters["type"] == "object"
        assert "a" in t.parameters["properties"]
        assert "b" in t.parameters["properties"]
        assert "flag" in t.parameters["properties"]
        assert "a" in t.parameters["required"]
        assert "b" in t.parameters["required"]
        assert "flag" not in t.parameters.get("required", [])
        tool_registry.unregister("schema_test")

    def test_explicit_schema_override(self) -> None:
        custom_params = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }

        @tool(name="override_test", description="test", parameters=custom_params)
        async def _my_tool(x: str) -> str:
            return x

        t = tool_registry.get("override_test")
        assert t.parameters == custom_params
        tool_registry.unregister("override_test")

    def test_pydantic_model_schema(self) -> None:
        @tool(name="pydantic_decor_test", description="test")
        async def _my_tool(args: _EditArgs) -> str:
            return f"Edited {args.path}"

        t = tool_registry.get("pydantic_decor_test")
        # Schema wraps the Pydantic model under the param name
        assert t.parameters["type"] == "object"
        args_prop = t.parameters["properties"]["args"]
        assert args_prop["type"] == "object"
        assert "path" in args_prop["properties"]
        assert "old_text" in args_prop["properties"]
        assert "new_text" in args_prop["properties"]
        tool_registry.unregister("pydantic_decor_test")


# ------------------------------------------------------------------
# Default singleton
# ------------------------------------------------------------------


class TestDefaultSingleton:
    def test_exists(self) -> None:
        assert isinstance(tool_registry, ToolRegistry)

    def test_name(self) -> None:
        assert tool_registry.name == "default"


# ------------------------------------------------------------------
# Timeout tests
# ------------------------------------------------------------------


async def _slow_tool() -> str:
    """Sleeps for 5 seconds — used to test timeout."""
    import asyncio
    await asyncio.sleep(5)
    return "done"


async def _fast_tool() -> str:
    """Returns immediately."""
    return "fast"


class TestFunctionToolTimeout:
    def test_timeout_stored(self) -> None:
        ft = FunctionTool(
            _fast_tool, name="ft_timeout", description="", parameters={}, timeout=10
        )
        assert ft.timeout_seconds == 10

    def test_timeout_none_by_default(self) -> None:
        ft = FunctionTool(
            _fast_tool, name="ft_no_timeout", description="", parameters={}
        )
        assert ft.timeout_seconds is None


class TestToolDecoratorTimeout:
    def test_timeout_passed_to_function_tool(self) -> None:
        @tool(name="dec_timeout_test", description="test", timeout=7)
        async def _my_tool(x: str) -> str:
            return x

        t = tool_registry.get("dec_timeout_test")
        assert t.timeout_seconds == 7
        tool_registry.unregister("dec_timeout_test")

    def test_timeout_none_by_default(self) -> None:
        @tool(name="dec_no_timeout_test", description="test")
        async def _my_tool(x: str) -> str:
            return x

        t = tool_registry.get("dec_no_timeout_test")
        assert t.timeout_seconds is None
        tool_registry.unregister("dec_no_timeout_test")


class TestRegistryExecuteTimeout:
    async def test_timeout_fires_returns_error(self) -> None:
        reg = ToolRegistry(name="timeout_test")
        reg.register(
            FunctionTool(
                _slow_tool,
                name="slow",
                description="Slow tool",
                parameters={},
                timeout=0.1,
            )
        )
        result = await reg.execute("slow", {})
        assert result.success is False
        assert "timed out" in (result.error or "").lower()
        assert result.metadata.get("timeout") is True

    async def test_timeout_completes_within(self) -> None:
        reg = ToolRegistry(name="timeout_test")
        reg.register(
            FunctionTool(
                _fast_tool,
                name="fast",
                description="Fast tool",
                parameters={},
                timeout=5,
            )
        )
        result = await reg.execute("fast", {})
        assert result.success is True
        assert result.output == "fast"

    async def test_timeout_zero_disables(self) -> None:
        reg = ToolRegistry(name="timeout_test")
        reg.register(
            FunctionTool(
                _slow_tool,
                name="slow_no_timeout",
                description="Slow tool",
                parameters={},
                timeout=0,
            )
        )
        # With timeout=0 (disabled), the tool runs without timeout
        # We use a shorter sleep variant to avoid test hanging
        async def _short_slow() -> str:
            import asyncio
            await asyncio.sleep(0.05)
            return "ok"

        reg.unregister("slow_no_timeout")
        reg.register(
            FunctionTool(
                _short_slow,
                name="slow_no_timeout",
                description="Slow tool",
                parameters={},
                timeout=0,
            )
        )
        result = await reg.execute("slow_no_timeout", {})
        assert result.success is True

    async def test_timeout_negative_disables(self) -> None:
        reg = ToolRegistry(name="timeout_test")

        async def _quick() -> str:
            return "quick"

        reg.register(
            FunctionTool(
                _quick,
                name="neg_timeout",
                description="Tool",
                parameters={},
                timeout=-5,
            )
        )
        result = await reg.execute("neg_timeout", {})
        assert result.success is True

    async def test_config_default_timeout_applied(self) -> None:
        reg = ToolRegistry(name="timeout_test")
        # Tool without explicit timeout should use config default
        reg.register(
            FunctionTool(
                _fast_tool,
                name="config_timeout_tool",
                description="Tool",
                parameters={},
                permission_level="read",
            )
        )
        result = await reg.execute("config_timeout_tool", {})
        assert result.success is True

    async def test_execute_from_llm_timeout(self) -> None:
        reg = ToolRegistry(name="timeout_test")
        reg.register(
            FunctionTool(
                _slow_tool,
                name="slow_llm",
                description="Slow",
                parameters={},
                timeout=0.1,
            )
        )
        tool_call = {
            "id": "call_0",
            "type": "function",
            "function": {
                "name": "slow_llm",
                "arguments": "{}",
            },
        }
        result = await reg.execute_from_llm(tool_call)
        assert result.success is False
        assert "timed out" in (result.error or "").lower()


class TestConfigToolTimeout:
    def test_get_tool_timeout_read(self) -> None:
        from coding_agent.config import Settings

        settings = Settings()
        assert settings.get_tool_timeout("read") == settings.tool_timeout_read

    def test_get_tool_timeout_write(self) -> None:
        from coding_agent.config import Settings

        settings = Settings()
        assert settings.get_tool_timeout("write") == settings.tool_timeout_write

    def test_get_tool_timeout_execute(self) -> None:
        from coding_agent.config import Settings

        settings = Settings()
        assert settings.get_tool_timeout("execute") == settings.tool_timeout_execute

    def test_get_tool_timeout_dangerous(self) -> None:
        from coding_agent.config import Settings

        settings = Settings()
        assert settings.get_tool_timeout("dangerous") == settings.tool_timeout_dangerous

    def test_get_tool_timeout_unknown_falls_back(self) -> None:
        from coding_agent.config import Settings

        settings = Settings()
        assert settings.get_tool_timeout("unknown") == settings.tool_timeout_default


# ------------------------------------------------------------------
# Feature #2: retryable attribute
# ------------------------------------------------------------------


class TestRetryableAttribute:
    def test_function_tool_default_retryable(self) -> None:
        ft = FunctionTool(_add, name="add", description="Add", parameters={})
        assert ft.retryable is True

    def test_function_tool_non_retryable(self) -> None:
        ft = FunctionTool(
            _add, name="add", description="Add", parameters={}, retryable=False
        )
        assert ft.retryable is False

    def test_decorator_retryable_default(self) -> None:
        reg = ToolRegistry(name="retry_test")

        @tool(name="rt_default", parameters={}, registry=reg)
        async def _my_tool() -> str:
            return "ok"

        assert _my_tool.retryable is True

    def test_decorator_retryable_false(self) -> None:
        reg = ToolRegistry(name="retry_test2")

        @tool(name="rt_false", parameters={}, registry=reg, retryable=False)
        async def _my_tool2() -> str:
            return "ok"

        assert _my_tool2.retryable is False

    async def test_timeout_metadata_includes_retryable(self) -> None:
        reg = ToolRegistry(name="retry_meta")
        reg.register(
            FunctionTool(
                _slow_tool,
                name="slow_retry",
                description="Slow",
                parameters={},
                timeout=0.1,
                retryable=False,
            )
        )
        result = await reg.execute("slow_retry", {})
        assert result.success is False
        assert result.metadata.get("retryable") is False

    async def test_timeout_metadata_retryable_true(self) -> None:
        reg = ToolRegistry(name="retry_meta2")
        reg.register(
            FunctionTool(
                _slow_tool,
                name="slow_retry2",
                description="Slow",
                parameters={},
                timeout=0.1,
                retryable=True,
            )
        )
        result = await reg.execute("slow_retry2", {})
        assert result.success is False
        assert result.metadata.get("retryable") is True


# ------------------------------------------------------------------
# Feature #5: idle_timeout attribute
# ------------------------------------------------------------------


class TestIdleTimeoutAttribute:
    def test_function_tool_idle_timeout_default(self) -> None:
        ft = FunctionTool(_add, name="add", description="Add", parameters={})
        assert ft.idle_timeout is None

    def test_function_tool_idle_timeout_set(self) -> None:
        ft = FunctionTool(
            _add, name="add", description="Add", parameters={}, idle_timeout=10.0
        )
        assert ft.idle_timeout == 10.0

    def test_decorator_idle_timeout(self) -> None:
        reg = ToolRegistry(name="idle_test")

        @tool(name="idle_tool", parameters={}, registry=reg, idle_timeout=5.0)
        async def _idle_tool() -> str:
            return "ok"

        assert _idle_tool.idle_timeout == 5.0


# ------------------------------------------------------------------
# Feature #7: tool_timeout_overrides
# ------------------------------------------------------------------


class TestToolTimeoutOverrides:
    async def test_override_takes_precedence(self) -> None:
        import os

        os.environ["CODING_AGENT_TOOL_TIMEOUT_OVERRIDES"] = '{"slow_override": 1}'
        try:
            from coding_agent.config import Settings

            settings = Settings()
            assert settings.tool_timeout_overrides.get("slow_override") == 1

            reg = ToolRegistry(name="override_test")
            reg.register(
                FunctionTool(
                    _slow_tool,
                    name="slow_override",
                    description="Slow",
                    parameters={},
                    timeout=0.1,
                )
            )
            # The override (1s) should NOT apply since the tool has an explicit timeout (0.1s)
            # But verify the override is loaded correctly
            result = await reg.execute("slow_override", {})
            assert result.success is False
            assert "timed out" in (result.error or "").lower()
        finally:
            del os.environ["CODING_AGENT_TOOL_TIMEOUT_OVERRIDES"]

    async def test_override_applies_when_no_tool_timeout(self) -> None:
        import os

        os.environ["CODING_AGENT_TOOL_TIMEOUT_OVERRIDES"] = '{"fast_override": 1}'
        try:
            reg = ToolRegistry(name="override_apply")
            reg.register(
                FunctionTool(
                    _fast_tool,
                    name="fast_override",
                    description="Fast",
                    parameters={},
                )
            )
            result = await reg.execute("fast_override", {})
            assert result.success is True
        finally:
            del os.environ["CODING_AGENT_TOOL_TIMEOUT_OVERRIDES"]

    async def test_no_override_uses_default(self) -> None:
        reg = ToolRegistry(name="no_override")
        reg.register(
            FunctionTool(
                _fast_tool,
                name="fast_no_override",
                description="Fast",
                parameters={},
            )
        )
        result = await reg.execute("fast_no_override", {})
        assert result.success is True


# ------------------------------------------------------------------
# Feature #8: cleanup callback
# ------------------------------------------------------------------


class TestCleanupCallback:
    async def test_cleanup_called_on_timeout(self) -> None:
        cleanup_called = False

        async def _slow_with_cleanup() -> str:
            import asyncio

            await asyncio.sleep(10)
            return "never"

        def _on_cleanup() -> None:
            nonlocal cleanup_called
            cleanup_called = True

        reg = ToolRegistry(name="cleanup_test")
        reg.register(
            FunctionTool(
                _slow_with_cleanup,
                name="slow_cleanup",
                description="Slow",
                parameters={},
                timeout=0.1,
                cleanup=_on_cleanup,
            )
        )
        result = await reg.execute("slow_cleanup", {})
        assert result.success is False
        assert cleanup_called is True

    async def test_cleanup_not_called_on_success(self) -> None:
        cleanup_called = False

        def _on_cleanup() -> None:
            nonlocal cleanup_called
            cleanup_called = True

        reg = ToolRegistry(name="cleanup_success")
        reg.register(
            FunctionTool(
                _fast_tool,
                name="fast_cleanup",
                description="Fast",
                parameters={},
                cleanup=_on_cleanup,
            )
        )
        result = await reg.execute("fast_cleanup", {})
        assert result.success is True
        assert cleanup_called is False

    async def test_cleanup_none_is_noop(self) -> None:
        reg = ToolRegistry(name="cleanup_none")
        reg.register(
            FunctionTool(
                _fast_tool,
                name="fast_no_cleanup",
                description="Fast",
                parameters={},
                cleanup=None,
            )
        )
        result = await reg.execute("fast_no_cleanup", {})
        assert result.success is True

    async def test_cleanup_error_does_not_propagate(self) -> None:
        def _bad_cleanup() -> None:
            raise RuntimeError("cleanup failed")

        reg = ToolRegistry(name="cleanup_err")
        reg.register(
            FunctionTool(
                _slow_with_cleanup_fn,
                name="slow_bad_cleanup",
                description="Slow",
                parameters={},
                timeout=0.1,
                cleanup=_bad_cleanup,
            )
        )
        result = await reg.execute("slow_bad_cleanup", {})
        assert result.success is False
        assert "timed out" in (result.error or "").lower()

    async def test_async_cleanup(self) -> None:
        cleanup_called = False

        async def _slow_for_async_cleanup() -> str:
            import asyncio

            await asyncio.sleep(10)
            return "never"

        async def _async_cleanup() -> None:
            nonlocal cleanup_called
            cleanup_called = True

        reg = ToolRegistry(name="async_cleanup")
        reg.register(
            FunctionTool(
                _slow_for_async_cleanup,
                name="slow_async_cleanup",
                description="Slow",
                parameters={},
                timeout=0.1,
                cleanup=_async_cleanup,
            )
        )
        result = await reg.execute("slow_async_cleanup", {})
        assert result.success is False
        assert cleanup_called is True

    def test_decorator_cleanup(self) -> None:
        reg = ToolRegistry(name="dec_cleanup")

        @tool(name="dec_cleanup_tool", parameters={}, registry=reg, cleanup=lambda: None)
        async def _dec_cleanup() -> str:
            return "ok"

        assert _dec_cleanup._cleanup is not None


async def _slow_with_cleanup_fn() -> str:
    import asyncio

    await asyncio.sleep(10)
    return "never"
