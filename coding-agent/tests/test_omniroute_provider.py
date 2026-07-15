"""Standalone OmniRoute gateway validation — run before integrating into core.

OmniRoute is a free AI gateway that aggregates 50+ providers (1.6B tokens/month)
into a single OpenAI-compatible endpoint at http://localhost:20128/v1.

IMPORTANT: OmniRoute returns SSE (text/event-stream) for ALL chat completions,
even non-streaming ones. This test parses SSE to extract the final completion.

Usage:
    uv run python tests/test_omniroute_provider.py

Requires:
    - OMNIROUTE_API_KEY in environment or .env (from Dashboard -> Endpoints)
    - OmniRoute running locally: npm install -g omniroute && omniroute
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import httpx

BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "http://localhost:20128/v1")
DEFAULT_MODEL = os.environ.get("OMNIROUTE_MODEL", "auto")


def _get_api_key() -> str:
    key = os.environ.get("OMNIROUTE_API_KEY", "")
    if not key:
        try:
            from dotenv import load_dotenv

            load_dotenv()
            key = os.environ.get("OMNIROUTE_API_KEY", "")
        except ImportError:
            pass
    if not key:
        print("ERROR: Set OMNIROUTE_API_KEY in env or .env file")
        print("  1. Install OmniRoute: npm install -g omniroute && omniroute")
        print("  2. Open Dashboard: http://localhost:20128")
        print("  3. Copy key from Dashboard -> Endpoints")
        raise SystemExit(1)
    return key


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={
            "Authorization": f"Bearer {_get_api_key()}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(120.0),
    )


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _parse_sse_response(body: str) -> dict[str, Any]:
    """Parse OmniRoute SSE response into an OpenAI-format dict.

    OmniRoute returns text/event-stream for ALL chat completions (even
    non-streaming). This function reassembles the chunks into a single
    response dict compatible with the OpenAI format.
    """
    content_parts: list[str] = []
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    finish_reason: str = "stop"
    usage: dict[str, Any] = {}
    model: str = ""

    for line in body.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue

        if not model and chunk.get("model"):
            model = chunk["model"]

        choices = chunk.get("choices", [])
        if not choices:
            if chunk.get("usage"):
                usage = chunk["usage"]
            continue

        delta = choices[0].get("delta", {})
        fr = choices[0].get("finish_reason")
        if fr:
            finish_reason = fr

        if delta.get("content"):
            content_parts.append(delta["content"])

        if delta.get("tool_calls"):
            for tc in delta["tool_calls"]:
                idx = tc.get("index", 0)
                if idx not in tool_calls_by_index:
                    tool_calls_by_index[idx] = {
                        "id": tc.get("id", f"call_{idx}"),
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                entry = tool_calls_by_index[idx]
                fn_delta = tc.get("function", {})
                if fn_delta.get("name"):
                    entry["function"]["name"] = fn_delta["name"]
                if fn_delta.get("arguments"):
                    entry["function"]["arguments"] += fn_delta["arguments"]

        if choices[0].get("usage"):
            usage = choices[0]["usage"]

    content = "".join(content_parts) if content_parts else None
    tool_calls = list(tool_calls_by_index.values()) if tool_calls_by_index else None

    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
        "model": model,
    }


async def _post_chat(client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to /chat/completions and parse the SSE response into a dict."""
    response = await client.post("/chat/completions", json=payload)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")

    if "text/event-stream" in content_type:
        return _parse_sse_response(response.text)

    return response.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_connection() -> None:
    """Test 1: Verify OmniRoute is running and reachable."""
    print("=" * 60)
    print("TEST 1: Connection")
    print("=" * 60)
    client = _make_client()
    response = await client.get("/models")
    response.raise_for_status()
    data = response.json()
    models = data.get("data", [])
    print(f"Endpoint:    {BASE_URL}")
    print(f"Models:      {len(models)} available")
    assert len(models) > 0, "OmniRoute should expose at least one model"
    print("PASSED\n")


async def test_auto_completion() -> None:
    """Test 2: Non-streaming completion with auto-routing."""
    print("=" * 60)
    print("TEST 2: Auto-routing completion (model=auto)")
    print("=" * 60)
    client = _make_client()
    start = time.perf_counter()

    data = await _post_chat(
        client,
        {
            "model": "auto",
            "messages": [{"role": "user", "content": "Say hello in exactly 3 words."}],
        },
    )

    elapsed = time.perf_counter() - start
    choice = data["choices"][0]
    content = choice["message"]["content"] or ""
    finish = choice.get("finish_reason", "")
    usage = data.get("usage", {})
    routed_model = data.get("model", "unknown")

    print(f"Routed to:   {routed_model}")
    print(f"Response:    {content}")
    print(f"Finish:      {finish}")
    print(f"Tokens:      {usage.get('total_tokens', 'N/A')}")
    print(f"Time:        {elapsed:.2f}s")
    assert content, "Response should not be empty"
    print("PASSED\n")


async def test_oc_big_pickle() -> None:
    """Test 3: Your configured model (oc/big-pickle)."""
    print("=" * 60)
    print("TEST 3: Your model (oc/big-pickle)")
    print("=" * 60)
    client = _make_client()
    start = time.perf_counter()

    data = await _post_chat(
        client,
        {
            "model": "oc/big-pickle",
            "messages": [{"role": "user", "content": "What is 2+2? Reply with just the number."}],
        },
    )

    elapsed = time.perf_counter() - start
    choice = data["choices"][0]
    content = choice["message"]["content"] or ""
    routed_model = data.get("model", "unknown")

    print(f"Routed to:   {routed_model}")
    print(f"Response:    {content}")
    print(f"Time:        {elapsed:.2f}s")
    assert content, "Response should not be empty"
    assert "4" in content, f"Expected '4' in response, got: {content}"
    print("PASSED\n")


async def test_free_model() -> None:
    """Test 4: Free model (oc/deepseek-v4-flash-free)."""
    print("=" * 60)
    print("TEST 4: Free model (oc/deepseek-v4-flash-free)")
    print("=" * 60)
    client = _make_client()
    start = time.perf_counter()

    data = await _post_chat(
        client,
        {
            "model": "oc/deepseek-v4-flash-free",
            "messages": [{"role": "user", "content": "What is 3+5? Reply with just the number."}],
        },
    )

    elapsed = time.perf_counter() - start
    choice = data["choices"][0]
    content = choice["message"]["content"] or ""
    routed_model = data.get("model", "unknown")

    print(f"Routed to:   {routed_model}")
    print(f"Response:    {content}")
    print(f"Time:        {elapsed:.2f}s")
    assert content, "Response should not be empty"
    assert "8" in content, f"Expected '8' in response, got: {content}"
    print("PASSED\n")


async def test_streaming() -> None:
    """Test 5: Streaming completion."""
    print("=" * 60)
    print("TEST 5: Streaming completion")
    print("=" * 60)
    client = _make_client()
    start = time.perf_counter()
    chunks = 0

    async with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "Write a 3-line haiku about fast inference."}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    ) as response:
        response.raise_for_status()
        print("Response:    ", end="")
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    print(content, end="", flush=True)
                    chunks += 1
            except Exception:
                continue

    elapsed = time.perf_counter() - start
    print()
    print(f"Text chunks: {chunks}")
    print(f"Time:        {elapsed:.2f}s")
    assert chunks > 0, "Should have received text chunks"
    print("PASSED\n")


async def test_tool_use() -> None:
    """Test 6: Tool calling."""
    print("=" * 60)
    print("TEST 6: Tool calling")
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
    data = await _post_chat(
        client,
        {
            "model": "auto",
            "messages": [{"role": "user", "content": "List the files in the src/ directory."}],
            "tools": tools,
        },
    )
    elapsed = time.perf_counter() - start

    choice = data["choices"][0]
    msg = choice.get("message", {})
    tool_calls = msg.get("tool_calls") or []
    finish = choice.get("finish_reason", "")

    print(f"Finish:      {finish}")
    print(f"Tool calls:  {len(tool_calls)}")
    for i, tc in enumerate(tool_calls):
        fn = tc.get("function", {})
        print(f"  [{i}] {fn.get('name', '?')}({fn.get('arguments', '{}')})")
    print(f"Content:     {msg.get('content', '')}")
    print(f"Tokens:      {data.get('usage', {}).get('total_tokens', 'N/A')}")
    print(f"Time:        {elapsed:.2f}s")
    assert len(tool_calls) > 0, "Should have at least 1 tool call"
    print("PASSED\n")


async def test_multi_turn() -> None:
    """Test 7: Multi-turn conversation with memory."""
    print("=" * 60)
    print("TEST 7: Multi-turn conversation")
    print("=" * 60)
    client = _make_client()
    messages: list[dict[str, str]] = []

    messages.append({"role": "user", "content": "My name is Alice."})
    d1 = await _post_chat(client, {"model": "auto", "messages": messages})
    messages.append({"role": "assistant", "content": d1["choices"][0]["message"]["content"] or ""})
    print(f"Turn 1 (Alice): {d1['choices'][0]['message']['content']}")

    messages.append({"role": "user", "content": "What is my name?"})
    d2 = await _post_chat(client, {"model": "auto", "messages": messages})
    content2 = d2["choices"][0]["message"]["content"] or ""
    print(f"Turn 2 (Name?): {content2}")

    assert "Alice" in content2, f"LLM should remember name, got: {content2}"
    print("PASSED\n")


async def test_stream_with_tool() -> None:
    """Test 8: Stream with tool call."""
    print("=" * 60)
    print("TEST 8: Stream with tool call")
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
    tool_calls_seen = 0

    async with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "Run 'echo hello world' for me."}],
            "tools": tools,
            "stream": True,
        },
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    text_parts.append(delta["content"])
                    print(delta["content"], end="", flush=True)
                if delta.get("tool_calls"):
                    tool_calls_seen += len(delta["tool_calls"])
            except Exception:
                continue

    elapsed = time.perf_counter() - start
    print()
    print(f"Text parts:  {len(text_parts)}")
    print(f"Tool calls:  {tool_calls_seen}")
    print(f"Time:        {elapsed:.2f}s")
    assert tool_calls_seen > 0, "Should have a tool call"
    print("PASSED\n")


async def test_coding_model() -> None:
    """Test 9: Auto-coding mode for code generation."""
    print("=" * 60)
    print("TEST 9: Auto-coding mode")
    print("=" * 60)
    client = _make_client()
    start = time.perf_counter()

    data = await _post_chat(
        client,
        {
            "model": "auto/coding",
            "messages": [
                {
                    "role": "user",
                    "content": "Write a Python function called `fibonacci` that returns the nth Fibonacci number. Just the function, no explanation.",
                }
            ],
        },
    )

    elapsed = time.perf_counter() - start
    content = data["choices"][0]["message"]["content"] or ""
    routed_model = data.get("model", "unknown")

    print(f"Routed to:   {routed_model}")
    print(f"Response:\n{content}")
    print(f"Time:        {elapsed:.2f}s")
    assert content, "Response should not be empty"
    assert "fibonacci" in content.lower(), f"Expected 'fibonacci' in response"
    print("PASSED\n")


async def test_model_listing() -> None:
    """Test 10: List all available models."""
    print("=" * 60)
    print("TEST 10: Model listing")
    print("=" * 60)
    client = _make_client()
    response = await client.get("/models")
    response.raise_for_status()
    data = response.json()
    models = data.get("data", [])

    providers: dict[str, list[str]] = {}
    for m in models:
        model_id = m.get("id", "")
        prefix = model_id.split("/")[0] if "/" in model_id else "other"
        providers.setdefault(prefix, []).append(model_id)

    print(f"Total models:  {len(models)}")
    print("By provider:")
    for prefix, model_ids in sorted(providers.items()):
        print(f"  {prefix:12s}  {len(model_ids)} models")

    assert len(models) > 0, "Should have models"
    print("PASSED\n")


async def main() -> None:
    print(f"Provider:  OmniRoute (free AI gateway)")
    print(f"Endpoint:  {BASE_URL}")
    print(f"Key:       {_get_api_key()[:8]}...")
    print(f"Model:     {DEFAULT_MODEL}")
    print()

    tests = [
        test_connection,
        test_auto_completion,
        test_oc_big_pickle,
        test_free_model,
        test_streaming,
        test_tool_use,
        test_multi_turn,
        test_stream_with_tool,
        test_coding_model,
        test_model_listing,
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