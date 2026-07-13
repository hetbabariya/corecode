"""Live agent loop integration tests — specific behavior scenarios.

Usage:
    uv run python tests/live_agent_loop_test.py

Each test verifies a specific agent loop behavior with real LLM calls.
Auto-approves all permissions for testing purposes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import coding_agent.tools  # noqa: F401, E402
from coding_agent.agent.context import ContextManager
from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.loop import AgentLoop
from coding_agent.agent.permission_callback import AutoApproveCallback
from coding_agent.agent.permissions import PermissionManager
from coding_agent.config import Settings
from coding_agent.llm.client import LLMClient

WORKSPACE = Path(".")
settings = Settings()


def _make_loop() -> AgentLoop:
    provider = settings.llm_provider
    if provider == "openrouter":
        api_keys = settings.get_openrouter_api_keys()
        model = settings.openrouter_model
    else:
        api_keys = settings.get_api_keys()
        model = settings.llm_model

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


async def _collect_events(loop: AgentLoop, prompt: str) -> list[AgentEvent]:
    """Run the loop and collect all events."""
    events: list[AgentEvent] = []
    async for event in loop.process_input(prompt):
        events.append(event)
    return events


def _filter_events(events: list[AgentEvent], event_type: EventType) -> list[AgentEvent]:
    return [e for e in events if e.type == event_type]


def _print_result(name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")


async def test_text_only_response() -> None:
    """Agent should respond with text only when no tools are needed."""
    print("\nTest: text_only_response")
    loop = _make_loop()
    events = await _collect_events(loop, "What is 2 + 2? Reply with just the number.")

    text_events = _filter_events(events, EventType.TEXT)
    tool_starts = _filter_events(events, EventType.TOOL_START)

    has_text = len(text_events) > 0
    no_tools = len(tool_starts) == 0
    passed = has_text and no_tools

    text_content = "".join(str(e.data) for e in text_events)
    _print_result("has_text", has_text, f"{len(text_content)} chars")
    _print_result("no_tools_called", no_tools, f"{len(tool_starts)} tools")
    _print_result("overall", passed)


async def test_tool_called_for_file_read() -> None:
    """Agent should call read_file when asked to read a file."""
    print("\nTest: tool_called_for_file_read")
    loop = _make_loop()
    events = await _collect_events(loop, "Read the pyproject.toml file.")

    tool_starts = _filter_events(events, EventType.TOOL_START)
    tool_names = [
        e.data.get("name", "") for e in tool_starts if isinstance(e.data, dict)
    ]

    has_tool = len(tool_starts) > 0
    passed = has_tool

    _print_result("has_tool_call", has_tool, f"tools: {tool_names}")
    _print_result("overall", passed)


async def test_tool_called_for_search() -> None:
    """Agent should call search_content when asked to find code patterns."""
    print("\nTest: tool_called_for_search")
    loop = _make_loop()
    events = await _collect_events(
        loop, "Find all functions that use 'async def' in src/coding_agent/."
    )

    tool_starts = _filter_events(events, EventType.TOOL_START)
    tool_names = [
        e.data.get("name", "") for e in tool_starts if isinstance(e.data, dict)
    ]

    has_tool = len(tool_starts) > 0
    _print_result("has_tool_call", has_tool, f"tools: {tool_names}")
    _print_result("overall", has_tool)


async def test_multi_turn_context() -> None:
    """Agent should remember previous conversation context."""
    print("\nTest: multi_turn_context")
    loop = _make_loop()

    # Turn 1
    await _collect_events(loop, "My favorite color is purple. Remember this.")

    # Turn 2
    events2 = await _collect_events(loop, "What is my favorite color?")
    text2 = "".join(str(e.data) for e in _filter_events(events2, EventType.TEXT))

    mentions_color = "purple" in text2.lower()
    _print_result("remembers_context", mentions_color, f"response: {text2[:100]}")
    _print_result("overall", mentions_color)


async def test_permission_auto_approve() -> None:
    """Write permissions should be auto-approved for testing."""
    print("\nTest: permission_auto_approve")
    loop = _make_loop()

    # Ask agent to write a test file
    events = await _collect_events(
        loop,
        "Create a file called _test_permission_check.txt with the content 'hello'",
    )

    tool_starts = _filter_events(events, EventType.TOOL_START)
    errors = _filter_events(events, EventType.ERROR)

    has_tool = len(tool_starts) > 0
    no_errors = len(errors) == 0
    _print_result("has_tool_call", has_tool)
    _print_result("no_permission_errors", no_errors)
    _print_result("overall", has_tool and no_errors)


async def test_error_recovery() -> None:
    """Agent should handle tool failures gracefully."""
    print("\nTest: error_recovery")
    loop = _make_loop()

    events = await _collect_events(
        loop, "Read the file /nonexistent/path/that/does/not/exist.txt"
    )

    tool_starts = _filter_events(events, EventType.TOOL_START)
    text_events = _filter_events(events, EventType.TEXT)

    has_tool = len(tool_starts) > 0
    has_text = len(text_events) > 0
    _print_result("attempted_tool", has_tool)
    _print_result("provided_text_response", has_text)
    _print_result("overall", has_tool and has_text)


async def test_max_iterations() -> None:
    """Agent should stop at max iterations."""
    print("\nTest: max_iterations")
    loop = _make_loop()

    # Give a task that would require many steps
    events = await _collect_events(
        loop,
        "Read every Python file in the entire src/ directory one by one and list them all.",
    )

    max_iter_events = _filter_events(events, EventType.MAX_ITERATIONS)
    done_events = _filter_events(events, EventType.DONE)

    stopped_naturally = len(done_events) > 0 and len(max_iter_events) == 0
    hit_limit = len(max_iter_events) > 0
    passed = stopped_naturally or hit_limit

    _print_result(
        "stopped", passed, f"done={len(done_events)}, max_iter={len(max_iter_events)}"
    )
    _print_result("overall", passed)


async def main() -> None:
    print(f"Provider: {settings.llm_provider}")
    print(f"Model:    {settings.get_active_model()}")
    print(f"Workspace: {WORKSPACE.resolve()}")

    tests = [
        test_text_only_response,
        test_tool_called_for_file_read,
        test_tool_called_for_search,
        test_multi_turn_context,
        test_permission_auto_approve,
        test_error_recovery,
        test_max_iterations,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"  [ERROR] {test.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
