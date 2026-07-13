"""Live agent loop tests — run manually with a real API key.

Usage:
    uv run python tests/live_agent_test.py                    # interactive menu
    uv run python tests/live_agent_test.py --scenario text    # specific scenario
    uv run python tests/live_agent_test.py --scenario all     # run all

Requires:
    - CODING_AGENT_LLM_PROVIDER set to gemini or openrouter
    - Valid API key(s) in .env
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

# Import all tools so they register via @tool decorator
import coding_agent.tools  # noqa: F401, E402
from coding_agent.agent.context import ContextManager
from coding_agent.agent.events import EventType
from coding_agent.agent.loop import AgentLoop
from coding_agent.agent.permission_callback import AutoApproveCallback
from coding_agent.agent.permissions import PermissionManager
from coding_agent.config import Settings
from coding_agent.llm.client import LLMClient

WORKSPACE = Path(".")


def _make_loop() -> AgentLoop:
    settings = Settings()
    provider = settings.llm_provider

    if provider == "openrouter":
        api_keys = settings.get_openrouter_api_keys()
        model = settings.openrouter_model
    else:
        api_keys = settings.get_api_keys()
        model = settings.llm_model

    print(f"Provider: {provider}")
    print(f"Model:    {model}")
    print(f"Keys:     {len(api_keys)}")
    print()

    client = LLMClient(model=model, api_keys=api_keys, provider=provider)
    permissions = PermissionManager()
    context = ContextManager(max_tokens=settings.max_tokens)
    return AgentLoop(
        llm_client=client,
        permission_manager=permissions,
        context_manager=context,
        workspace=WORKSPACE,
        max_iterations=settings.max_iterations,
        permission_callback=AutoApproveCallback(),
    )


async def stream_to_terminal(events):
    """Consume AgentEvent stream and print formatted output."""
    text_buffer = ""
    tool_count = 0
    tool_start_time = 0.0

    async for event in events:
        if event.type == EventType.TEXT:
            text_buffer += str(event.data)
            print(str(event.data), end="", flush=True)

        elif event.type == EventType.TOOL_START:
            if text_buffer:
                print()
                text_buffer = ""
            tool_count += 1
            tool_start_time = time.perf_counter()
            name = event.data.get("name", "?") if isinstance(event.data, dict) else "?"
            args = event.data.get("args", "") if isinstance(event.data, dict) else ""
            print(f"   [Tool: {name}({args})]")

        elif event.type == EventType.TOOL_RESULT:
            elapsed = time.perf_counter() - tool_start_time if tool_start_time else 0
            status = "success" if not event.error else "error"
            preview = str(event.data)[:100] if event.data else ""
            print(f"   [Result: {status} — {elapsed:.1f}s] {preview}")

        elif event.type == EventType.DONE:
            print()

        elif event.type == EventType.ERROR:
            print(f"\n   [ERROR: {event.error}]")

        elif event.type == EventType.MAX_ITERATIONS:
            print("\n   [MAX ITERATIONS REACHED]")

    return tool_count


async def scenario_text() -> None:
    """Simple text response — no tools needed."""
    print("=" * 60)
    print("SCENARIO: text_only")
    print("Prompt: 'What is 2 + 2? Reply with just the number.'")
    print("Expected: Text response, no tool calls")
    print("=" * 60)

    loop = _make_loop()

    start = time.perf_counter()
    events = loop.process_input("What is 2 + 2? Reply with just the number.")
    tools = await stream_to_terminal(events)
    elapsed = time.perf_counter() - start

    print(f"\nTools called: {tools}")
    print(f"Time:         {elapsed:.2f}s")
    print(f"Total tokens: {loop.llm_client.total_usage.total_tokens}")
    assert tools == 0, "Should not call any tools for this prompt"
    print("PASSED\n")


async def scenario_read_file() -> None:
    """Read a file — should trigger read_file tool."""
    print("=" * 60)
    print("SCENARIO: read_file")
    print("Prompt: 'Read the pyproject.toml file'")
    print("Expected: Calls read_file, returns file content")
    print("=" * 60)

    loop = _make_loop()

    start = time.perf_counter()
    events = loop.process_input("Read the pyproject.toml file in this directory.")
    tools = await stream_to_terminal(events)
    elapsed = time.perf_counter() - start

    print(f"\nTools called: {tools}")
    print(f"Time:         {elapsed:.2f}s")
    print(f"Total tokens: {loop.llm_client.total_usage.total_tokens}")
    assert tools >= 1, "Should call at least 1 tool"
    print("PASSED\n")


async def scenario_search_code() -> None:
    """Search code — should trigger search_content tool."""
    print("=" * 60)
    print("SCENARIO: search_code")
    print("Prompt: 'Find all functions that use asyncio'")
    print("Expected: Calls search_content, finds matches")
    print("=" * 60)

    loop = _make_loop()

    start = time.perf_counter()
    events = loop.process_input(
        "Find all functions that use asyncio in the src/ directory."
    )
    tools = await stream_to_terminal(events)
    elapsed = time.perf_counter() - start

    print(f"\nTools called: {tools}")
    print(f"Time:         {elapsed:.2f}s")
    print(f"Total tokens: {loop.llm_client.total_usage.total_tokens}")
    assert tools >= 1, "Should call at least 1 tool"
    print("PASSED\n")


async def scenario_edit_file() -> None:
    """Edit a file — should trigger edit_file with auto-approved permissions."""
    print("=" * 60)
    print("SCENARIO: edit_file")
    print("Prompt: 'Add a comment at the top of pyproject.toml'")
    print("Expected: Calls edit_file, modifies file")
    print("NOTE: Permission auto-approved for testing")
    print("=" * 60)

    loop = _make_loop()

    start = time.perf_counter()
    events = loop.process_input(
        "Add a comment '# Test comment - please remove' at the very top of pyproject.toml."
    )
    tools = await stream_to_terminal(events)
    elapsed = time.perf_counter() - start

    print(f"\nTools called: {tools}")
    print(f"Time:         {elapsed:.2f}s")
    print(f"Total tokens: {loop.llm_client.total_usage.total_tokens}")
    assert tools >= 1, "Should call at least 1 tool"
    print("PASSED\n")


async def scenario_multi_step() -> None:
    """Multi-step task — should call multiple tools in sequence."""
    print("=" * 60)
    print("SCENARIO: multi_step")
    print("Prompt: 'List src/ files, then read the main module'")
    print("Expected: list_files + read_file (2+ tool calls)")
    print("=" * 60)

    loop = _make_loop()

    start = time.perf_counter()
    events = loop.process_input(
        "First list all Python files in src/coding_agent/, then read the main.py file."
    )
    tools = await stream_to_terminal(events)
    elapsed = time.perf_counter() - start

    print(f"\nTools called: {tools}")
    print(f"Time:         {elapsed:.2f}s")
    print(f"Total tokens: {loop.llm_client.total_usage.total_tokens}")
    assert tools >= 2, f"Should call at least 2 tools, got {tools}"
    print("PASSED\n")


async def scenario_error_handling() -> None:
    """Error handling — should handle tool failures gracefully."""
    print("=" * 60)
    print("SCENARIO: error_handling")
    print("Prompt: 'Read the file that_does_not_exist.txt'")
    print("Expected: Tool call fails, agent reports error gracefully")
    print("=" * 60)

    loop = _make_loop()

    start = time.perf_counter()
    events = loop.process_input(
        "Read the file that_does_not_exist.txt and tell me what's in it."
    )
    tools = await stream_to_terminal(events)
    elapsed = time.perf_counter() - start

    print(f"\nTools called: {tools}")
    print(f"Time:         {elapsed:.2f}s")
    print(f"Total tokens: {loop.llm_client.total_usage.total_tokens}")
    assert tools >= 1, "Should call at least 1 tool"
    print("PASSED\n")


SCENARIOS = {
    "text": scenario_text,
    "read": scenario_read_file,
    "search": scenario_search_code,
    "edit": scenario_edit_file,
    "multi": scenario_multi_step,
    "error": scenario_error_handling,
}


async def run_all() -> None:
    results: list[tuple[str, bool, str]] = []

    for name, fn in SCENARIOS.items():
        try:
            await fn()
            results.append((name, True, ""))
        except Exception as e:
            print(f"FAILED: {e}\n")
            results.append((name, False, str(e)))

    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, err in results:
        status = "PASS" if ok else f"FAIL: {err}"
        print(f"  {name:12s} {status}")
    print(f"\n{passed}/{len(results)} passed")


def interactive_menu() -> None:
    print("Select a scenario:")
    print("  1. text    — Simple text response (no tools)")
    print("  2. read    — Read a file")
    print("  3. search  — Search code patterns")
    print("  4. edit    — Edit a file (auto-approved)")
    print("  5. multi   — Multi-step task")
    print("  6. error   — Error handling")
    print("  7. all     — Run all scenarios")
    print()

    choice = input("Enter choice (1-7): ").strip()

    mapping = {
        "1": "text",
        "2": "read",
        "3": "search",
        "4": "edit",
        "5": "multi",
        "6": "error",
        "7": "all",
    }

    scenario = mapping.get(choice, "text")

    if scenario == "all":
        asyncio.run(run_all())
    elif scenario in SCENARIOS:
        asyncio.run(SCENARIOS[scenario]())
    else:
        print(f"Unknown scenario: {scenario}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Live agent loop tests")
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()) + ["all"],
        help="Run a specific scenario (or 'all')",
    )
    args = parser.parse_args()

    if args.scenario:
        if args.scenario == "all":
            asyncio.run(run_all())
        else:
            asyncio.run(SCENARIOS[args.scenario]())
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
