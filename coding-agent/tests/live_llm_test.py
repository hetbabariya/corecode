"""Live LLM tests — run manually with a real API key.

Usage:
    uv run python tests/live_llm_test.py

Requires:
    - CODING_AGENT_LLM_PROVIDER set to gemini or openrouter
    - For gemini: CODING_AGENT_LLM_API_KEY or CODING_AGENT_LLM_API_KEYS in .env
    - For openrouter: CODING_AGENT_OPENROUTER_API_KEY or CODING_AGENT_OPENROUTER_API_KEYS in .env
"""

from __future__ import annotations

import asyncio
import time

import pytest

from coding_agent.config import Settings
from coding_agent.llm.client import LLMClient
from coding_agent.llm.streaming import StreamEventType

# Skip all tests in this file during `pytest` — run manually only
pytestmark = pytest.mark.skip(
    reason="Live test — run with: uv run python tests/live_llm_test.py"
)

_settings = Settings()
PROVIDER = _settings.llm_provider

if PROVIDER == "openrouter":
    _api_keys = _settings.get_openrouter_api_keys()
    MODEL = _settings.openrouter_model
else:
    _api_keys = _settings.get_api_keys()
    MODEL = _settings.llm_model


def _make_client() -> LLMClient:
    """Create an LLMClient backed by the key pool for the active provider."""
    return LLMClient(model=MODEL, api_keys=_api_keys, provider=PROVIDER)


async def test_complete() -> None:
    """Test non-streaming completion."""
    print("=" * 60)
    print("TEST 1: Non-streaming completion")
    print("=" * 60)

    client = _make_client()
    start = time.perf_counter()

    response = await client.complete(
        messages=[{"role": "user", "content": "Say hello in exactly 3 words."}]
    )

    elapsed = time.perf_counter() - start
    print(f"Response:    {response.content}")
    print(f"Finish:      {response.finish_reason}")
    print(f"Tokens:      {response.usage.total_tokens}")
    print(f"Cost:        ${response.usage.estimated_cost:.6f}")
    print(f"Time:        {elapsed:.2f}s")
    assert response.content, "Response should not be empty"
    assert response.finish_reason == "stop"
    print("PASSED\n")


async def test_stream() -> None:
    """Test streaming completion."""
    print("=" * 60)
    print("TEST 2: Streaming completion")
    print("=" * 60)

    client = _make_client()
    start = time.perf_counter()
    token_count = 0

    print("Response:    ", end="")
    async for event in client.stream(
        messages=[
            {
                "role": "user",
                "content": "Write a 3-line haiku about Python programming.",
            }
        ]
    ):
        if event.type == StreamEventType.TEXT:
            print(event.data, end="", flush=True)
            token_count += 1
        elif event.type == StreamEventType.DONE:
            pass

    elapsed = time.perf_counter() - start
    print()
    print(f"Text chunks: {token_count}")
    print(f"Time:        {elapsed:.2f}s")
    assert token_count > 0, "Should have received text tokens"
    print("PASSED\n")


async def test_tool_use() -> None:
    """Test tool calling."""
    print("=" * 60)
    print("TEST 3: Tool use")
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
                        "path": {
                            "type": "string",
                            "description": "File path to read",
                        }
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
                        "path": {
                            "type": "string",
                            "description": "Directory path",
                        }
                    },
                    "required": ["path"],
                },
            },
        },
    ]

    start = time.perf_counter()
    response = await client.complete(
        messages=[
            {
                "role": "user",
                "content": "List the files in the src/ directory.",
            }
        ],
        tools=tools,
    )
    elapsed = time.perf_counter() - start

    print(f"Finish:      {response.finish_reason}")
    print(f"Tool calls:  {len(response.tool_calls)}")
    for i, tc in enumerate(response.tool_calls):
        fn = tc["function"]
        print(f"  [{i}] {fn['name']}({fn['arguments']})")
    print(f"Content:     {response.content}")
    print(f"Tokens:      {response.usage.total_tokens}")
    print(f"Time:        {elapsed:.2f}s")
    assert response.finish_reason == "tool_calls", (
        f"Expected tool_calls, got {response.finish_reason}"
    )
    assert len(response.tool_calls) > 0, "Should have at least 1 tool call"
    print("PASSED\n")


async def test_multi_turn() -> None:
    """Test multi-turn conversation with context."""
    print("=" * 60)
    print("TEST 4: Multi-turn conversation")
    print("=" * 60)

    client = _make_client()
    messages: list[dict[str, object]] = []

    # Turn 1
    messages.append({"role": "user", "content": "My name is Alice."})
    r1 = await client.complete(messages=messages)
    messages.append({"role": "assistant", "content": r1.content})
    print(f"Turn 1 (Alice): {r1.content}")

    # Turn 2
    messages.append({"role": "user", "content": "What is my name?"})
    r2 = await client.complete(messages=messages)
    print(f"Turn 2 (Name?): {r2.content}")

    print(f"Total tokens:   {client.total_usage.total_tokens}")
    print(f"Total cost:     ${client.total_usage.estimated_cost:.6f}")
    assert "Alice" in r2.content, f"LLM should remember name, got: {r2.content}"
    print("PASSED\n")


async def test_stream_with_tool() -> None:
    """Test streaming that triggers a tool call."""
    print("=" * 60)
    print("TEST 5: Stream with tool call")
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
                        "command": {
                            "type": "string",
                            "description": "The command to run",
                        }
                    },
                    "required": ["command"],
                },
            },
        },
    ]

    start = time.perf_counter()
    text_parts: list[str] = []
    tool_calls: list[dict] = []

    async for event in client.stream(
        messages=[{"role": "user", "content": "Run 'echo hello world' for me."}],
        tools=tools,
    ):
        if event.type == StreamEventType.TEXT:
            text_parts.append(str(event.data))
            print(event.data, end="", flush=True)
        elif event.type == StreamEventType.TOOL_CALL:
            tool_calls.append(event.data)  # type: ignore[arg-type]
        elif event.type == StreamEventType.DONE:
            pass

    elapsed = time.perf_counter() - start
    print()
    print(f"Text tokens: {len(text_parts)}")
    print(f"Tool calls:  {len(tool_calls)}")
    for tc in tool_calls:
        print(f"  -> {tc['function']['name']}({tc['function']['arguments']})")
    print(f"Time:        {elapsed:.2f}s")
    assert len(tool_calls) > 0, "Should have a tool call"
    print("PASSED\n")


async def test_usage_tracking() -> None:
    """Test that usage accumulates across calls."""
    print("=" * 60)
    print("TEST 6: Usage tracking across calls")
    print("=" * 60)

    client = _make_client()

    for i in range(3):
        response = await client.complete(
            messages=[{"role": "user", "content": f"Say the number {i}."}]
        )
        print(
            f"  Call {i}: {response.usage.prompt_tokens}+{response.usage.completion_tokens} tokens"
        )

    print()
    print(f"Accumulated prompt tokens:     {client.total_usage.prompt_tokens}")
    print(f"Accumulated completion tokens: {client.total_usage.completion_tokens}")
    print(f"Accumulated total tokens:      {client.total_usage.total_tokens}")
    print(f"Accumulated cost:              ${client.total_usage.estimated_cost:.6f}")
    assert client.total_usage.total_tokens > 0
    print("PASSED\n")


async def test_key_pool() -> None:
    """Test key pool rotation with multiple API keys."""
    print("=" * 60)
    print("TEST 7: Key pool rotation")
    print("=" * 60)

    if len(_api_keys) < 2:
        print("SKIPPED — need 2+ keys in CODING_AGENT_LLM_API_KEYS\n")
        return

    client = LLMClient(model=MODEL, api_keys=_api_keys)
    print(f"Pool size: {client._key_pool.size if client._key_pool else 0}")

    # Fire 5 rapid requests to exercise rotation
    for i in range(5):
        response = await client.complete(
            messages=[{"role": "user", "content": f"Say the number {i}."}]
        )
        pool_idx = client._key_pool.current_index if client._key_pool else -1
        print(
            f"  Call {i}: pool_index={pool_idx}, tokens={response.usage.total_tokens}"
        )

    print()
    print(f"Accumulated total tokens: {client.total_usage.total_tokens}")
    print(
        f"Pool exhausted: {client._key_pool.is_exhausted if client._key_pool else 'N/A'}"
    )
    assert client.total_usage.total_tokens > 0
    print("PASSED\n")


async def main() -> None:
    """Run all live tests."""
    print(f"Provider: {PROVIDER}")
    print(f"Model:    {MODEL}")
    print(f"Keys:     {len(_api_keys)}")
    print()

    tests = [
        test_complete,
        test_stream,
        test_tool_use,
        test_multi_turn,
        test_stream_with_tool,
        test_usage_tracking,
        test_key_pool,
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
