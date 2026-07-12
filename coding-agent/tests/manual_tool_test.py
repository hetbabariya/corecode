"""Manual smoke test for the tool system.

Run:  uv run python tests/manual_tool_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from typing import Literal

from pydantic import BaseModel, Field

from coding_agent.tools import (
    ToolRegistry,
    ToolResult,
    infer_schema,
    tool,
    tool_registry,
)

DIVIDER = "-" * 60

# Module-level Pydantic model so typing.get_type_hints() can resolve it
class EditArgs(BaseModel):
    path: str = Field(description="File to edit")
    old_text: str = Field(description="Text to replace")
    new_text: str = Field(description="Replacement")


# Module-level ToolResult-returning function for testing passthrough
async def _result_tool_func(msg: str) -> ToolResult:
    return ToolResult(success=True, output=f"custom: {msg}", metadata={"custom": True})


# Force stdout to utf-8 on Windows so we can print non-ASCII
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ------------------------------------------------------------------
# 1. Schema inference
# ------------------------------------------------------------------


def test_schema_inference() -> None:
    print(f"\n{DIVIDER}")
    print("1. SCHEMA INFERENCE")
    print(DIVIDER)

    def read_file(path: str, line_count: int = 10) -> None: ...

    def search(
        pattern: str,
        file_type: str | None = None,
        max_results: Literal[10, 50, 100] = 10,
    ) -> None: ...

    def edit(args: EditArgs) -> None: ...

    for fn, label in [
        (read_file, "read_file(path: str, line_count: int = 10)"),
        (search, "search(pattern, file_type | None, Literal[10,50,100])"),
        (edit, "edit(args: EditArgs) -- Pydantic model"),
    ]:
        schema = infer_schema(fn)
        print(f"\n  {label}")
        print(f"  {json.dumps(schema, indent=4)}")


# ------------------------------------------------------------------
# 2. Tool registration + @tool decorator
# ------------------------------------------------------------------


def test_tool_registration() -> None:
    print(f"\n{DIVIDER}")
    print("2. TOOL REGISTRATION + @tool DECORATOR")
    print(DIVIDER)

    # Clean up any leftovers from previous runs
    for name in ["greet", "deploy", "search"]:
        try:
            tool_registry.unregister(name)
        except KeyError:
            pass

    @tool(name="greet", description="Greet someone by name", permission="read")
    async def greet(name: str) -> str:
        """Say hello to a person."""
        return f"Hello, {name}!"

    @tool(name="deploy", description="Deploy to an environment", permission="execute")
    async def deploy(env: Literal["staging", "production"], dry_run: bool = False) -> str:
        if dry_run:
            return f"[DRY RUN] Would deploy to {env}"
        return f"Deployed to {env}"

    # Custom registry
    custom = ToolRegistry(name="plugins")

    @tool(name="search", description="Search files", permission="read", registry=custom)
    async def search(pattern: str) -> str:
        return f"Results for: {pattern}"

    print("\n  Default registry tools:", tool_registry.list_tools())
    print("  Custom registry tools:", custom.list_tools())

    print("\n  Default registry schemas:")
    for s in tool_registry.get_schemas():
        print(f"    - {s['function']['name']}: {s['function']['description']}")

    print("\n  Custom registry schema:")
    print(f"    {json.dumps(custom.get_schemas(), indent=4)}")

    # Cleanup
    tool_registry.unregister("greet")
    tool_registry.unregister("deploy")
    custom.unregister("search")


# ------------------------------------------------------------------
# 3. Execution
# ------------------------------------------------------------------


async def test_execution() -> None:
    print(f"\n{DIVIDER}")
    print("3. TOOL EXECUTION")
    print(DIVIDER)

    @tool(name="add", description="Add two numbers", permission="read")
    async def add(a: int, b: int) -> int:
        return a + b

    @tool(name="fail_tool", description="Always fails", permission="read")
    async def fail_tool() -> str:
        raise ValueError("something went wrong")

    from coding_agent.tools.registry import FunctionTool
    manual_tool = FunctionTool(
        _result_tool_func,
        name="result_tool",
        description="Returns ToolResult directly",
        parameters={"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
        permission_level="read",
    )
    tool_registry.register(manual_tool)

    # Successful execution
    result = await tool_registry.execute("add", {"a": 10, "b": 20})
    print(f"\n  add(10, 20) -> success={result.success}, output={result.output}")

    # Execution that raises
    result = await tool_registry.execute("fail_tool", {})
    print(f"  fail_tool() -> success={result.success}, error={result.error}")

    # ToolResult passthrough
    result = await tool_registry.execute("result_tool", {"msg": "hello"})
    print(f"  result_tool('hello') -> output={result.output}, metadata={result.metadata}")

    # Nonexistent tool
    result = await tool_registry.execute("nope", {})
    print(f"  nonexistent -> success={result.success}, error={result.error}")

    # Cleanup
    tool_registry.unregister("add")
    tool_registry.unregister("fail_tool")
    tool_registry.unregister("result_tool")


# ------------------------------------------------------------------
# 4. LLM format dispatch (execute_from_llm)
# ------------------------------------------------------------------


async def test_llm_dispatch() -> None:
    print(f"\n{DIVIDER}")
    print("4. LLM FORMAT DISPATCH (execute_from_llm)")
    print(DIVIDER)

    @tool(name="read_file", description="Read a file", permission="read")
    async def read_file(path: str) -> str:
        return f"<contents of {path}>"

    # Simulate what the LLM returns
    tool_call = {
        "id": "call_0",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": json.dumps({"path": "src/main.py"}),
        },
    }
    print(f"\n  LLM tool_call: {json.dumps(tool_call, indent=4)}")

    result = await tool_registry.execute_from_llm(tool_call)
    print(f"  Result: success={result.success}, output={result.output}")

    # Invalid JSON
    bad_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "read_file", "arguments": "not-json"},
    }
    result = await tool_registry.execute_from_llm(bad_call)
    print(f"  Bad JSON: success={result.success}, error={result.error}")

    # Missing name
    no_name = {
        "id": "call_2",
        "type": "function",
        "function": {"name": "", "arguments": "{}"},
    }
    result = await tool_registry.execute_from_llm(no_name)
    print(f"  Missing name: success={result.success}, error={result.error}")

    tool_registry.unregister("read_file")


# ------------------------------------------------------------------
# 5. LLM integration (requires API key)
# ------------------------------------------------------------------


async def test_llm_integration() -> None:
    print(f"\n{DIVIDER}")
    print("5. LLM INTEGRATION (requires API key)")
    print(DIVIDER)

    try:
        from coding_agent.config import Settings
        from coding_agent.llm.client import LLMClient

        settings = Settings()
        api_keys = (
            settings.get_api_keys()
            if settings.llm_provider == "gemini"
            else settings.get_openrouter_api_keys()
        )
        if not api_keys:
            print("  [SKIP] No API key configured in .env")
            return

        @tool(name="calculate", description="Calculate the result of a math expression", permission="read")
        async def calculate(expression: str) -> str:
            """Evaluate a math expression safely."""
            allowed = set("0123456789+-*/.() ")
            if not all(c in allowed for c in expression):
                return "Error: invalid characters in expression"
            return str(eval(expression))  # noqa: S307

        model = settings.get_active_model()

        client = LLMClient(
            provider=settings.llm_provider,
            api_keys=api_keys,
            model=model,
        )

        print(f"\n  Using: {settings.llm_provider} / {model}")
        print("  Sending: 'What is 12 * 7? Use the calculate tool.'")

        response = await client.complete(
            messages=[{"role": "user", "content": "What is 12 * 7? Use the calculate tool."}],
            tools=tool_registry.get_schemas(),
        )

        print(f"  LLM content: {response.content!r}")
        print(f"  Tool calls: {len(response.tool_calls)}")

        for tc in response.tool_calls:
            fn = tc["function"]
            print(f"    -> {fn['name']}({fn['arguments']})")
            result = await tool_registry.execute_from_llm(tc)
            print(f"    <- success={result.success}, output={result.output}")

        # Feed result back to LLM
        if response.tool_calls:
            messages = [
                {"role": "user", "content": "What is 12 * 7? Use the calculate tool."},
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": response.tool_calls,
                },
                {
                    "role": "tool",
                    "tool_call_id": response.tool_calls[0].get("id", "call_0"),
                    "content": result.output,
                    "name": "calculate",
                },
            ]
            final = await client.complete(messages=messages)
            print(f"  Final answer: {final.content}")

        tool_registry.unregister("calculate")

    except Exception as exc:
        print(f"  [SKIP] {type(exc).__name__}: {exc}")
        traceback.print_exc()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("  TOOL SYSTEM SMOKE TEST")
    print("=" * 60)

    test_schema_inference()
    test_tool_registration()
    await test_execution()
    await test_llm_dispatch()
    await test_llm_integration()

    print(f"\n{DIVIDER}")
    print("ALL DONE")
    print(DIVIDER)


if __name__ == "__main__":
    asyncio.run(main())
