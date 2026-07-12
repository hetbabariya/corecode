"""Tests for the tool registry, FunctionTool adapter, and @tool decorator."""

from __future__ import annotations

import json
from typing import Any

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
        ft = FunctionTool(_add, name="add", description="Add", parameters={}, permission_level="read")
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
        reg.register(FunctionTool(_greet, name="greet", description="Greet", parameters={}))
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
        ft = FunctionTool(_str_returns, name="str_returns", description="", parameters={})
        result = await ft.execute()
        assert result.success is True
        assert result.output == "plain string"

    async def test_execute_returns_tool_result_passthrough(self) -> None:
        ft = FunctionTool(_returns_result, name="returns_result", description="", parameters={})
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
        ft = FunctionTool(_add, name="add", description="", parameters={}, permission_level="write")
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
