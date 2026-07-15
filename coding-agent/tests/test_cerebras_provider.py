"""Standalone Cerebras SDK validation — run before integrating into core.

Usage:
    uv run python tests/test_cerebras_provider.py

Requires:
    - CEREBRAS_API_KEY in environment or .env
    - cerebras-cloud-sdk installed
"""

from __future__ import annotations

import asyncio
import os
import time

from cerebras.cloud.sdk import AsyncCerebras

MODEL = "gpt-oss-120b"


def _get_api_key() -> str:
    key = os.environ.get("CEREBRAS_API_KEY", "")
    if not key:
        try:
            from dotenv import load_dotenv

            load_dotenv()
            key = os.environ.get("CEREBRAS_API_KEY", "")
        except ImportError:
            pass
    if not key:
        print("ERROR: Set CEREBRAS_API_KEY in env or .env file")
        raise SystemExit(1)
    return key


def _make_client() -> AsyncCerebras:
    return AsyncCerebras(api_key=_get_api_key())


async def test_client_init() -> None:
    print("=" * 60)
    print("TEST 1: Client init")
    print("=" * 60)
    client = _make_client()
    assert client is not None
    print("Client created successfully")
    print("PASSED\n")


async def test_basic_completion() -> None:
    print("=" * 60)
    print("TEST 2: Non-streaming completion")
    print("=" * 60)
    client = _make_client()
    start = time.perf_counter()

    response = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Say hello in exactly 3 words."}],
    )

    elapsed = time.perf_counter() - start
    content = response.choices[0].message.content or ""
    finish = response.choices[0].finish_reason or ""
    usage = response.usage

    print(f"Response:    {content}")
    print(f"Finish:      {finish}")
    print(f"Tokens:      {usage.total_tokens if usage else 'N/A'}")
    print(f"Time:        {elapsed:.2f}s")
    assert content, "Response should not be empty"
    assert finish == "stop"
    print("PASSED\n")


async def test_streaming() -> None:
    print("=" * 60)
    print("TEST 3: Streaming completion")
    print("=" * 60)
    client = _make_client()
    start = time.perf_counter()
    chunks = 0

    stream = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Write a 3-line haiku about fast inference."}],
        stream=True,
    )

    print("Response:    ", end="")
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)
            chunks += 1

    elapsed = time.perf_counter() - start
    print()
    print(f"Text chunks: {chunks}")
    print(f"Time:        {elapsed:.2f}s")
    assert chunks > 0, "Should have received text chunks"
    print("PASSED\n")


async def test_tool_use() -> None:
    print("=" * 60)
    print("TEST 4: Tool calling")
    print("=" * 60)
    client = _make_client()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to read"}
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files in a directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"}
                    },
                    "required": ["path"],
                },
            },
        },
    ]

    start = time.perf_counter()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "List the files in the src/ directory."}],
        tools=tools,
    )
    elapsed = time.perf_counter() - start

    choice = response.choices[0]
    msg = choice.message
    tool_calls = msg.tool_calls or []

    print(f"Finish:      {choice.finish_reason}")
    print(f"Tool calls:  {len(tool_calls)}")
    for i, tc in enumerate(tool_calls):
        print(f"  [{i}] {tc.function.name}({tc.function.arguments})")
    print(f"Content:     {msg.content}")
    print(f"Tokens:      {response.usage.total_tokens if response.usage else 'N/A'}")
    print(f"Time:        {elapsed:.2f}s")
    assert len(tool_calls) > 0, "Should have at least 1 tool call"
    print("PASSED\n")


async def test_multi_turn() -> None:
    print("=" * 60)
    print("TEST 5: Multi-turn conversation")
    print("=" * 60)
    client = _make_client()
    messages: list[dict[str, object]] = []

    messages.append({"role": "user", "content": "My name is Alice."})
    r1 = await client.chat.completions.create(model=MODEL, messages=messages)
    messages.append({"role": "assistant", "content": r1.choices[0].message.content or ""})
    print(f"Turn 1 (Alice): {r1.choices[0].message.content}")

    messages.append({"role": "user", "content": "What is my name?"})
    r2 = await client.chat.completions.create(model=MODEL, messages=messages)
    content2 = r2.choices[0].message.content or ""
    print(f"Turn 2 (Name?): {content2}")

    assert "Alice" in content2, f"LLM should remember name, got: {content2}"
    print("PASSED\n")


async def test_stream_with_tool() -> None:
    print("=" * 60)
    print("TEST 6: Stream with tool call")
    print("=" * 60)
    client = _make_client()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command to run"}
                    },
                    "required": ["command"],
                },
            },
        },
    ]

    start = time.perf_counter()
    text_parts: list[str] = []
    tool_calls: list[object] = []

    stream = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Run 'echo hello world' for me."}],
        tools=tools,
        stream=True,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            text_parts.append(delta.content)
            print(delta.content, end="", flush=True)
        if delta.tool_calls:
            tool_calls.extend(delta.tool_calls)

    elapsed = time.perf_counter() - start
    print()
    print(f"Text tokens: {len(text_parts)}")
    print(f"Tool calls:  {len(tool_calls)}")
    print(f"Time:        {elapsed:.2f}s")
    assert len(tool_calls) > 0, "Should have a tool call"
    print("PASSED\n")


async def main() -> None:
    print(f"Provider: Cerebras (fast inference)")
    print(f"Model:    {MODEL}")
    print(f"Key:      {_get_api_key()[:8]}...")
    print()

    tests = [
        test_client_init,
        test_basic_completion,
        test_streaming,
        test_tool_use,
        test_multi_turn,
        test_stream_with_tool,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"FAILED: {e}\n")
            failed += 1

    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
