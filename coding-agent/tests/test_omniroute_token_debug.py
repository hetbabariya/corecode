"""Debug test for OmniRoute token tracking.

Run this file to analyze OmniRoute's streaming response and find
where usage data appears (or doesn't).

Usage:
    python tests/test_omniroute_token_debug.py

This will:
1. Make a non-streaming call and check response for usage
2. Make a streaming call and capture raw SSE lines
3. Parse each line and check for usage data
4. Feed chunks to StreamParser and check for USAGE events
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def test_nonstreaming_usage():
    """Test 1: Non-streaming call — check if usage is in response."""
    print("\n" + "=" * 60)
    print("TEST 1: Non-streaming usage check")
    print("=" * 60)

    from coding_agent.config import Settings
    settings = Settings()

    api_keys = settings.get_omniroute_api_keys()
    if not api_keys:
        print("SKIP: No OmniRoute API keys configured")
        return

    import httpx

    base_url = settings.omniroute_base_url or "http://localhost:20128/v1"
    model = settings.omniroute_model or "auto"
    api_key = api_keys[0]

    print(f"  Base URL: {base_url}")
    print(f"  Model:    {model}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Say hello in 5 words."}],
                "stream": False,
                "max_tokens": 50,
            },
        )

        print(f"  Status:   {response.status_code}")

        if response.status_code != 200:
            print(f"  Error:    {response.text[:500]}")
            return

        data = response.json()

        # Check top-level usage
        usage = data.get("usage")
        print(f"\n  Top-level usage: {usage}")

        # Check choices
        choices = data.get("choices", [])
        print(f"  Choices count:   {len(choices)}")

        if choices:
            choice = choices[0]
            message = choice.get("message", {})
            print(f"  Finish reason:   {choice.get('finish_reason')}")
            print(f"  Content preview: {(message.get('content') or '')[:100]}")

            # Check if usage is inside choice (some providers do this)
            choice_usage = choice.get("usage")
            if choice_usage:
                print(f"  Choice-level usage: {choice_usage}")

        # Print full response keys
        print(f"\n  Response top-level keys: {list(data.keys())}")

        if usage:
            print(f"\n  ✓ USAGE FOUND in non-streaming response!")
            print(f"    prompt_tokens:     {usage.get('prompt_tokens', 'MISSING')}")
            print(f"    completion_tokens: {usage.get('completion_tokens', 'MISSING')}")
        else:
            print(f"\n  ✗ NO USAGE in non-streaming response")
            print(f"    Full response (first 1000 chars):")
            print(f"    {json.dumps(data, indent=2)[:1000]}")


async def test_streaming_usage():
    """Test 2: Streaming call — capture and analyze raw SSE lines."""
    print("\n" + "=" * 60)
    print("TEST 2: Streaming usage check")
    print("=" * 60)

    from coding_agent.config import Settings
    settings = Settings()

    api_keys = settings.get_omniroute_api_keys()
    if not api_keys:
        print("SKIP: No OmniRoute API keys configured")
        return

    import httpx

    base_url = settings.omniroute_base_url or "http://localhost:20128/v1"
    model = settings.omniroute_model or "auto"
    api_key = api_keys[0]

    print(f"  Base URL: {base_url}")
    print(f"  Model:    {model}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Say hello in 5 words."}],
                "stream": True,
                "max_tokens": 50,
            },
        ) as response:
            print(f"  Status:   {response.status_code}")
            print(f"  Headers:  {dict(response.headers)}")

            if response.status_code != 200:
                text = await response.aread()
                print(f"  Error:    {text[:500]}")
                return

            # Collect all SSE lines
            raw_lines: list[str] = []
            chunks_with_usage: list[dict] = []
            chunks_with_choices: list[dict] = []
            all_chunks: list[dict] = []

            line_count = 0
            async for line in response.aiter_lines():
                line_count += 1
                raw_lines.append(line)

                # Try to parse as SSE data line
                if line.startswith("data: "):
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        print(f"\n  Line {line_count}: [DONE]")
                        continue

                    try:
                        chunk = json.loads(payload)
                        all_chunks.append(chunk)

                        has_usage = "usage" in chunk
                        has_choices = bool(chunk.get("choices"))

                        if has_usage:
                            chunks_with_usage.append(chunk)
                            print(f"\n  Line {line_count}: ✓ USAGE FOUND!")
                            print(f"    Usage data: {json.dumps(chunk['usage'], indent=2)}")

                        if has_choices:
                            choices = chunk["choices"]
                            if choices:
                                choice = choices[0]
                                delta = choice.get("delta", {})
                                finish = choice.get("finish_reason")
                                content = delta.get("content", "")

                                if content:
                                    # Only print first few content chunks
                                    if len(chunks_with_choices) < 3:
                                        print(f"  Line {line_count}: content chunk: '{content[:50]}'")
                                elif finish:
                                    print(f"  Line {line_count}: finish_reason={finish}")

                                # Check for usage inside choice
                                choice_usage = choice.get("usage")
                                if choice_usage:
                                    print(f"\n  Line {line_count}: ✓ USAGE IN CHOICE!")
                                    print(f"    Choice usage: {json.dumps(choice_usage, indent=2)}")

                            chunks_with_choices.append(chunk)

                    except json.JSONDecodeError:
                        if line_count <= 5:
                            print(f"  Line {line_count}: (non-JSON) {line[:100]}")
                else:
                    if line_count <= 5:
                        print(f"  Line {line_count}: (non-data) {line[:100]}")

            # Summary
            print(f"\n  --- Summary ---")
            print(f"  Total lines:          {line_count}")
            print(f"  Total chunks parsed:  {len(all_chunks)}")
            print(f"  Chunks with choices:  {len(chunks_with_choices)}")
            print(f"  Chunks with usage:    {len(chunks_with_usage)}")

            if chunks_with_usage:
                print(f"\n  ✓ USAGE FOUND in streaming response!")
                last_usage = chunks_with_usage[-1]["usage"]
                print(f"    Last usage: {json.dumps(last_usage, indent=2)}")
            else:
                print(f"\n  ✗ NO USAGE in any streaming chunk")
                print(f"    Checking last 3 chunks for any usage-like data...")
                for i, chunk in enumerate(all_chunks[-3:]):
                    print(f"    Chunk {len(all_chunks) - 3 + i}: keys={list(chunk.keys())}")
                    if "usage" in chunk:
                        print(f"      usage={chunk['usage']}")


async def test_streamparser_usage():
    """Test 3: Feed raw chunks to StreamParser and check for USAGE events."""
    print("\n" + "=" * 60)
    print("TEST 3: StreamParser USAGE event check")
    print("=" * 60)

    from coding_agent.config import Settings
    from coding_agent.llm.streaming import StreamParser, StreamEventType

    settings = Settings()

    api_keys = settings.get_omniroute_api_keys()
    if not api_keys:
        print("SKIP: No OmniRoute API keys configured")
        return

    import httpx

    base_url = settings.omniroute_base_url or "http://localhost:20128/v1"
    model = settings.omniroute_model or "auto"
    api_key = api_keys[0]

    print(f"  Base URL: {base_url}")
    print(f"  Model:    {model}")

    parser = StreamParser()
    usage_events: list[dict] = []
    text_tokens: list[str] = []
    total_chunks = 0

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Say hello in 5 words."}],
                "stream": True,
                "max_tokens": 50,
            },
        ) as response:
            if response.status_code != 200:
                print(f"  Error: status {response.status_code}")
                return

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    continue

                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                total_chunks += 1
                for event in parser.feed(chunk):
                    if event.type == StreamEventType.USAGE:
                        usage_events.append(event.data)
                        print(f"  ✓ USAGE event: {event.data}")
                    elif event.type == StreamEventType.TEXT:
                        text_tokens.append(str(event.data))
                    elif event.type == StreamEventType.DONE:
                        print(f"  DONE event received")

    print(f"\n  --- Summary ---")
    print(f"  Total chunks fed:  {total_chunks}")
    print(f"  TEXT events:       {len(text_tokens)}")
    print(f"  USAGE events:      {len(usage_events)}")
    print(f"  Text preview:      {''.join(text_tokens)[:200]}")

    if usage_events:
        print(f"\n  ✓ StreamParser received USAGE events!")
        for i, usage in enumerate(usage_events):
            print(f"    Event {i}: {usage}")
    else:
        print(f"\n  ✗ StreamParser received NO USAGE events")
        print(f"    This means either:")
        print(f"    1. OmniRoute doesn't send usage in streaming chunks")
        print(f"    2. Usage is in a format StreamParser doesn't recognize")
        print(f"    3. Usage arrives in a chunk that fails to parse")


async def main():
    """Run all debug tests."""
    print("OmniRoute Token Tracking Debug")
    print("=" * 60)

    await test_nonstreaming_usage()
    await test_streaming_usage()
    await test_streamparser_usage()

    print("\n" + "=" * 60)
    print("DONE — Analyze the output above to find where usage appears.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
