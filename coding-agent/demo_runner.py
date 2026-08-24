"""CoreCode Demo Runner — automated showcase of all major features.

Runs the agent through 9 demo scenarios with rich terminal output.
Screen-record your terminal while running this script.

Usage:
    cd coding-agent
    uv run python demo_runner.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()

# ── Helpers ──────────────────────────────────────────────────────────────

DEMO_WORKSPACE = Path("_demo_workspace")
W = 70  # display width


def banner(title: str, subtitle: str = "") -> None:
    """Print a section banner."""
    console.print()
    console.print(Rule(style="bold cyan"))
    console.print(
        Panel(
            Text(title, style="bold white", justify="center"),
            subtitle=subtitle,
            style="cyan",
            width=W,
        )
    )
    console.print()


def pause(seconds: float = 1.5) -> None:
    """Pause between sections for visual clarity."""
    time.sleep(seconds)


def event_dict(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    return {}


def truncate(text: str, max_lines: int = 4, max_chars: int = 300) -> str:
    if not text:
        return "(empty)"
    lines = text.split("\n")
    if len(lines) > max_lines:
        truncated = "\n".join(lines[:max_lines])
        return f"{truncated}\n  ... ({len(lines) - max_lines} more lines)"
    if len(text) > max_chars:
        return text[:max_chars] + f"\n  ... ({len(text) - max_chars} more chars)"
    return text


def format_args(args: dict[str, Any] | str, max_len: int = 100) -> str:
    if isinstance(args, str):
        return args[:max_len]
    if "path" in args:
        path = args["path"]
        if "content" in args:
            preview = args["content"][:50]
            return f'path={path} content="{preview}..."'
        if "old_text" in args:
            return f'path={path} old="{args["old_text"][:30]}..."'
        if "pattern" in args:
            return f'path={path} pattern="{args["pattern"]}"'
        return f"path={path}"
    if "query" in args:
        return f'query="{args["query"]}"'
    if "goal" in args:
        steps = args.get("steps", [])
        return f'goal="{args["goal"]}" steps={len(steps)}'
    if "command" in args:
        return f'command="{args["command"]}"'
    s = json.dumps(args, ensure_ascii=False)
    return s[:max_len] + "..." if len(s) > max_len else s


# ── Agent Setup ──────────────────────────────────────────────────────────


async def create_agent(
    workspace: Path,
    permission: str = "auto",
) -> tuple[Any, Any, Any]:
    """Create and return (agent, session_mgr, settings)."""
    from coding_agent.agent.context import ContextManager
    from coding_agent.agent.loop import AgentLoop
    from coding_agent.agent.memory import MemoryManager
    from coding_agent.agent.permission_callback import AutoApproveCallback
    from coding_agent.agent.permissions import PermissionManager
    from coding_agent.config import Settings
    from coding_agent.llm.client import LLMClient
    from coding_agent.session.manager import SessionManager

    settings = Settings()
    provider = settings.llm_provider

    if provider == "openrouter":
        api_keys = settings.get_openrouter_api_keys()
        model = settings.openrouter_model
    elif provider == "cerebras":
        api_keys = settings.get_cerebras_api_keys()
        model = settings.cerebras_model
    elif provider == "zenmux":
        api_keys = settings.get_zenmux_api_keys()
        model = settings.zenmux_model
    elif provider == "omniroute":
        api_keys = settings.get_omniroute_api_keys()
        model = settings.omniroute_model
    else:
        api_keys = settings.get_api_keys()
        model = settings.llm_model

    llm_client = LLMClient(model=model, api_keys=api_keys, provider=provider)

    summary_provider, summary_model = settings.get_summary_model()
    if summary_model != model or summary_provider != provider:
        if summary_provider == "openrouter":
            summary_keys = settings.get_openrouter_api_keys()
        elif summary_provider == "cerebras":
            summary_keys = settings.get_cerebras_api_keys()
        elif summary_provider == "zenmux":
            summary_keys = settings.get_zenmux_api_keys()
        elif summary_provider == "omniroute":
            summary_keys = settings.get_omniroute_api_keys()
        else:
            summary_keys = settings.get_api_keys()
        summary_client = LLMClient(
            model=summary_model, api_keys=summary_keys, provider=summary_provider
        )
    else:
        summary_client = None

    perm_callback = AutoApproveCallback()
    permissions = PermissionManager()
    context = ContextManager(max_tokens=settings.max_tokens)

    session_mgr = SessionManager(settings.get_db_path())
    await session_mgr.initialize()
    memory_mgr = MemoryManager(
        session_mgr,
        max_memories=settings.max_memories,
        prune_threshold=settings.memory_prune_threshold,
    )

    agent = AgentLoop(
        llm_client=llm_client,
        permission_manager=permissions,
        context_manager=context,
        workspace=workspace,
        max_iterations=settings.max_iterations,
        permission_callback=perm_callback,
        summary_llm_client=summary_client,
        memory_manager=memory_mgr,
        session_manager=session_mgr,
        max_cost=settings.max_cost_per_session,
        max_time=settings.max_time_per_task,
        agent_timeout_per_iteration=settings.agent_timeout_per_iteration,
        config=settings,
    )

    return agent, session_mgr, settings


async def run_prompt(agent: Any, prompt: str, fresh: bool = True) -> dict[str, Any]:
    """Run a single prompt through the agent and return stats."""
    from coding_agent.agent.events import EventType

    stats: dict[str, Any] = {
        "iterations": 0,
        "tools_called": 0,
        "tool_names": [],
        "text": [],
        "tool_start_time": 0.0,
        "current_tool": "",
        "tool_args_by_id": {},
    }

    async for event in agent.process_input(prompt, fresh=fresh):
        d = event_dict(event.data)

        if event.type == EventType.TEXT:
            stats["text"].append(str(event.data))

        elif event.type == EventType.LOOP_START:
            stats["iterations"] += 1
            console.print(f"    ─── iteration {stats['iterations']} ───", style="dim")

        elif event.type == EventType.TOOL_START:
            name = d.get("name", "?")
            args = d.get("args", "")
            tc_id = d.get("tc_id", "")
            stats["current_tool"] = name
            stats["tool_args_by_id"][tc_id] = args
            stats["tool_start_time"] = time.monotonic()
            stats["tool_names"].append(name)
            stats["tools_called"] += 1

        elif event.type == EventType.TOOL_RESULT:
            tool_dur = (time.monotonic() - stats["tool_start_time"]) * 1000
            result = d.get("result", "")
            tc_id = d.get("tc_id", "")
            tool_args = stats["tool_args_by_id"].pop(tc_id, "")
            if hasattr(result, "success"):
                success = result.success
                output = result.output if result.output else ""
                error = result.error or ""
            else:
                success = True
                output = str(result)
                error = ""

            icon = "✓" if success else "✗"
            args_str = format_args(tool_args)

            READ_ONLY = {
                "read_file",
                "list_files",
                "search_content",
                "search_files",
                "git_status",
                "git_diff",
                "git_log",
                "refresh_index",
            }
            if stats["current_tool"] in READ_ONLY and success and not error:
                file_path = (
                    tool_args.get("path", "") if isinstance(tool_args, dict) else ""
                )
                if file_path:
                    console.print(
                        f"    │ {icon} {stats['current_tool']} → {file_path}",
                        style="green" if success else "red",
                    )
                else:
                    console.print(
                        f"    │ {icon} {stats['current_tool']} ({tool_dur:.0f}ms)",
                        style="green" if success else "red",
                    )
            else:
                console.print(f"    │ {stats['current_tool']}", style="bold")
                console.print(f"    │   args: {args_str}", style="dim")
                if error:
                    console.print(f"    │   {icon} error: {error[:150]}", style="red")
                elif output:
                    for line in truncate(output, max_lines=2, max_chars=150).split(
                        "\n"
                    ):
                        console.print(f"    │   {line}", style="dim")
                else:
                    console.print(f"    │   {icon} ({tool_dur:.0f}ms)", style="green")
            console.print("    │", style="dim")

        elif event.type == EventType.UNDO_PUSH:
            file_path = d.get("file_path", "")
            tool_name = d.get("tool_name", "")
            console.print(
                f"    │   ↩ undoable: {tool_name} on {file_path}", style="yellow"
            )

        elif event.type == EventType.SUBAGENT_STARTED:
            prompt_preview = str(d.get("prompt", ""))[:60]
            console.print(f"    │   △ subagent — {prompt_preview}", style="magenta")

        elif event.type == EventType.SUBAGENT_TOOL_START:
            name = d.get("name", "?")
            args = d.get("args", "")
            args_str = format_args(args)
            console.print(f"    │     ◷ {name}({args_str[:50]})", style="magenta dim")

        elif event.type == EventType.SUBAGENT_COMPLETED:
            console.print("    │   ▽ subagent done", style="magenta")

        elif event.type == EventType.PLAN_MODE_ENTERED:
            console.print(
                "    │   △ plan mode enabled — read-only tools", style="yellow"
            )

        elif event.type == EventType.PLAN_MODE_EXITED:
            console.print(
                "    │   ▽ plan mode disabled — execution mode", style="yellow"
            )

        elif event.type == EventType.VERIFICATION:
            file_path = d.get("file_path", "")
            checks = d.get("checks", [])
            failed = [c for c in checks if not c.get("passed", True)]
            if failed:
                console.print(f"    │   ⚠ verification: {file_path}", style="yellow")
                for c in failed[:2]:
                    console.print(
                        f"    │     - [{c.get('tool', '?')}] {c.get('output', '')[:80]}",
                        style="yellow dim",
                    )

        elif event.type == EventType.CONTEXT_HEALTH:
            ratio = d.get("usage_ratio", 0)
            console.print(f"    │   ⚠ context at {ratio:.0%}", style="yellow")

        elif event.type == EventType.MICRO_COMPACT:
            compacted = d.get("compacted", 0)
            console.print(
                f"    │   ⚠ micro-compact: {compacted} old results cleared",
                style="yellow",
            )

        elif event.type == EventType.ERROR:
            err = d.get("error", str(event.data))
            console.print(f"    │   ✗ error: {err}", style="red")

        elif event.type == EventType.DONE:
            pass

    return stats


# ── Demo Sections ────────────────────────────────────────────────────────


async def demo_intro(settings: Any) -> None:
    """Section 1: Introduction & Config."""
    banner("1 / 9 — Introduction & Configuration", "Showcasing project setup")

    table = Table(
        title="Current Configuration",
        show_header=True,
        header_style="bold cyan",
        width=W - 4,
    )
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_row("Provider", settings.llm_provider)
    table.add_row("Model", settings.get_active_model())
    table.add_row("Exec Mode", settings.exec_mode)
    table.add_row("Max Tokens", f"{settings.max_tokens:,}")
    table.add_row("Max Cost/Session", f"${settings.max_cost_per_session}")
    table.add_row("Permission", settings.permission_level)
    table.add_row("Verify After Edit", str(settings.verify_after_edit))
    table.add_row("Hooks Enabled", str(settings.hooks_enabled))
    console.print(table)
    pause()


async def demo_basic_loop(agent: Any) -> dict[str, Any]:
    """Section 2: Basic Agent Loop."""
    banner("2 / 9 — Basic Agent Loop", "observe → think → act cycle")

    console.print("  Running a simple file-read task...", style="cyan")
    console.print()

    # Create a sample file first
    DEMO_WORKSPACE.mkdir(exist_ok=True)
    sample = DEMO_WORKSPACE / "hello.py"
    sample.write_text(
        '"""A simple hello world module."""\n\ndef greet(name: str) -> str:\n    """Return a greeting."""\n    return f"Hello, {name}!"\n\nif __name__ == "__main__":\n    print(greet("World"))\n'
    )

    stats = await run_prompt(
        agent,
        "Read the file hello.py and tell me what functions it defines.",
        fresh=True,
    )

    # Print response
    if stats["text"]:
        console.print()
        console.print("  Agent response:", style="bold")
        console.print()
        for line in "".join(stats["text"]).split("\n"):
            console.print(f"  │ {line}")
        console.print()

    # Summary
    table = Table(show_header=False, box=None, width=W - 4)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Iterations", str(stats["iterations"]))
    table.add_row("Tools called", str(stats["tools_called"]))
    table.add_row(
        "Tool names", ", ".join(stats["tool_names"]) if stats["tool_names"] else "none"
    )
    console.print(table)
    pause(2)
    return stats


async def demo_file_ops(agent: Any) -> dict[str, Any]:
    """Section 3: File Operations."""
    banner("3 / 9 — File Operations", "write, edit, multi-edit with undo tracking")

    console.print(
        "  Creating files, editing them, and showing undo tracking...", style="cyan"
    )
    console.print()

    stats = await run_prompt(
        agent,
        "Do the following in order:\n"
        "1. Create a file called math_utils.py with a function add(a, b) that returns a + b\n"
        "2. Add a function subtract(a, b) that returns a - b\n"
        "3. Add a function multiply(a, b) that returns a * b",
        fresh=True,
    )

    if stats["text"]:
        console.print()
        for line in "".join(stats["text"]).split("\n"):
            console.print(f"  │ {line}")
        console.print()

    table = Table(show_header=False, box=None, width=W - 4)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Iterations", str(stats["iterations"]))
    table.add_row("Tools called", str(stats["tools_called"]))
    table.add_row(
        "Tool names", ", ".join(stats["tool_names"]) if stats["tool_names"] else "none"
    )
    console.print(table)

    # Show created file
    math_file = DEMO_WORKSPACE / "math_utils.py"
    if math_file.exists():
        console.print()
        console.print("  Created file:", style="bold")
        console.print(Rule(style="dim"))
        for i, line in enumerate(math_file.read_text().split("\n"), 1):
            console.print(f"  {i:3d} │ {line}")
        console.print(Rule(style="dim"))
    pause(2)
    return stats


async def demo_search(agent: Any) -> dict[str, Any]:
    """Section 4: Search & Shell."""
    banner("4 / 9 — Search & Shell Execution", "content search, file search, commands")

    console.print("  Searching workspace and running a shell command...", style="cyan")
    console.print()

    stats = await run_prompt(
        agent,
        "1. Search for all Python files in the current directory\n"
        "2. Search for the word 'def' in all files\n"
        "3. Run 'python --version' to show the Python version",
        fresh=True,
    )

    if stats["text"]:
        console.print()
        for line in "".join(stats["text"]).split("\n"):
            console.print(f"  │ {line}")
        console.print()

    table = Table(show_header=False, box=None, width=W - 4)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Iterations", str(stats["iterations"]))
    table.add_row("Tools called", str(stats["tools_called"]))
    table.add_row(
        "Tool names", ", ".join(stats["tool_names"]) if stats["tool_names"] else "none"
    )
    console.print(table)
    pause(2)
    return stats


async def demo_git(agent: Any) -> dict[str, Any]:
    """Section 5: Git Operations."""
    banner("5 / 9 — Git Operations", "status, diff, log, commit")

    console.print("  Running git operations on the workspace...", style="cyan")
    console.print()

    stats = await run_prompt(
        agent,
        "1. Show the git status of the current repository\n"
        "2. Show the last 3 git commits\n"
        "3. Show the git diff if there are any changes",
        fresh=True,
    )

    if stats["text"]:
        console.print()
        for line in "".join(stats["text"]).split("\n"):
            console.print(f"  │ {line}")
        console.print()

    table = Table(show_header=False, box=None, width=W - 4)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Iterations", str(stats["iterations"]))
    table.add_row("Tools called", str(stats["tools_called"]))
    table.add_row(
        "Tool names", ", ".join(stats["tool_names"]) if stats["tool_names"] else "none"
    )
    console.print(table)
    pause(2)
    return stats


async def demo_plan(agent: Any) -> dict[str, Any]:
    """Section 6: Plan/Build Mode."""
    banner(
        "6 / 9 — Plan/Build Mode", "create plan → read-only analysis → build execution"
    )

    console.print("  Creating a plan for a multi-step task...", style="cyan")
    console.print()

    stats = await run_prompt(
        agent,
        "Create a plan to build a simple calculator program. The plan should:\n"
        "1. Define the requirements\n"
        "2. Design the module structure\n"
        "3. Implement basic operations (add, subtract, multiply, divide)\n"
        "4. Add input validation\n"
        "5. Write tests\n\n"
        "Then update each step to 'completed' as you finish it.",
        fresh=True,
    )

    if stats["text"]:
        console.print()
        for line in "".join(stats["text"]).split("\n"):
            console.print(f"  │ {line}")
        console.print()

    table = Table(show_header=False, box=None, width=W - 4)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Iterations", str(stats["iterations"]))
    table.add_row("Tools called", str(stats["tools_called"]))
    table.add_row(
        "Tool names", ", ".join(stats["tool_names"]) if stats["tool_names"] else "none"
    )
    console.print(table)
    pause(2)
    return stats


async def demo_subagent(agent: Any) -> dict[str, Any]:
    """Section 7: Subagent Spawning."""
    banner("7 / 9 — Subagent Spawning", "delegate tasks to child agents")

    console.print(
        "  Spawning a subagent for a read-only analysis task...", style="cyan"
    )
    console.print()

    stats = await run_prompt(
        agent,
        "Delegate a task to a subagent: have it read all Python files in the workspace "
        "and create a summary of what each file does. The subagent should only use "
        "read-only tools.",
        fresh=True,
    )

    if stats["text"]:
        console.print()
        for line in "".join(stats["text"]).split("\n"):
            console.print(f"  │ {line}")
        console.print()

    table = Table(show_header=False, box=None, width=W - 4)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Iterations", str(stats["iterations"]))
    table.add_row("Tools called", str(stats["tools_called"]))
    table.add_row(
        "Tool names", ", ".join(stats["tool_names"]) if stats["tool_names"] else "none"
    )
    console.print(table)
    pause(2)
    return stats


async def demo_undo_memory(agent: Any) -> dict[str, Any]:
    """Section 8: Undo/Redo & Memory."""
    banner(
        "8 / 9 — Undo/Redo & Semantic Memory", "file snapshots and cross-session memory"
    )

    console.print(
        "  Creating files, undoing changes, and storing memories...", style="cyan"
    )
    console.print()

    stats = await run_prompt(
        agent,
        "1. Create a file called notes.txt with 'First version of notes'\n"
        "2. Edit notes.txt to say 'Updated version of notes'\n"
        "3. Undo the last edit\n"
        "4. Remember that this workspace uses Python 3.12+ and prefers type hints\n"
        "5. Recall what you remember about this workspace",
        fresh=True,
    )

    if stats["text"]:
        console.print()
        for line in "".join(stats["text"]).split("\n"):
            console.print(f"  │ {line}")
        console.print()

    table = Table(show_header=False, box=None, width=W - 4)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Iterations", str(stats["iterations"]))
    table.add_row("Tools called", str(stats["tools_called"]))
    table.add_row(
        "Tool names", ", ".join(stats["tool_names"]) if stats["tool_names"] else "none"
    )
    console.print(table)
    pause(2)
    return stats


async def demo_session(agent: Any, session_mgr: Any) -> dict[str, Any]:
    """Section 9: Session Persistence."""
    banner("9 / 9 — Session Persistence", "save, resume, and history")

    console.print("  Running a task and checking session state...", style="cyan")
    console.print()

    stats = await run_prompt(
        agent,
        "1. List all files in the workspace\n"
        "2. Show the git log\n"
        "3. Count the total number of lines in all Python files",
        fresh=True,
    )

    if stats["text"]:
        console.print()
        for line in "".join(stats["text"]).split("\n"):
            console.print(f"  │ {line}")
        console.print()

    # Show session info
    if session_mgr and agent.session_id:
        console.print("  Session saved:", style="bold")
        console.print(f"    Session ID: {agent.session_id}")
        try:
            sessions = await session_mgr.list_sessions(limit=5)
            if sessions:
                table = Table(
                    title="Recent Sessions",
                    width=W - 4,
                    show_header=True,
                    header_style="bold cyan",
                )
                table.add_column("ID", style="dim")
                table.add_column("Model")
                table.add_column("Tokens")
                table.add_column("Cost")
                for s in sessions:
                    table.add_row(
                        str(s.get("id", ""))[:12] + "...",
                        str(s.get("model", "")),
                        str(s.get("total_tokens", 0)),
                        f"${s.get('total_cost', 0):.4f}",
                    )
                console.print(table)
        except Exception:
            pass

    table = Table(show_header=False, box=None, width=W - 4)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Iterations", str(stats["iterations"]))
    table.add_row("Tools called", str(stats["tools_called"]))
    table.add_row(
        "Tool names", ", ".join(stats["tool_names"]) if stats["tool_names"] else "none"
    )
    console.print(table)
    pause(2)
    return stats


# ── Main ─────────────────────────────────────────────────────────────────


async def main() -> None:
    console.clear()

    # Title
    console.print()
    console.print(
        Panel(
            Text("CoreCode — Full Feature Demo", style="bold white", justify="center"),
            subtitle="AI-Powered Coding Agent",
            style="bold cyan",
            width=W,
        )
    )
    console.print()
    console.print("  This script runs the agent through 9 demo scenarios.", style="dim")
    console.print("  Screen-record your terminal while this runs.", style="dim")
    console.print("  Press Ctrl+C at any time to stop.", style="dim")
    console.print()
    pause(2)

    # Setup workspace
    if DEMO_WORKSPACE.exists():
        shutil.rmtree(DEMO_WORKSPACE)
    DEMO_WORKSPACE.mkdir()

    # Create agent
    console.print("  Initializing agent...", style="cyan")
    try:
        agent, session_mgr, settings = await create_agent(DEMO_WORKSPACE)
    except Exception as e:
        console.print(f"\n  ✗ Failed to initialize agent: {e}", style="red")
        console.print(
            "  Make sure your .env file has a valid API key configured.", style="yellow"
        )
        console.print()
        return

    console.print("  ✓ Agent ready!", style="green")
    console.print()

    total_start = time.monotonic()
    all_stats: list[tuple[str, dict[str, Any]]] = []

    try:
        # Section 1: Intro
        await demo_intro(settings)

        # Section 2: Basic Loop
        s = await demo_basic_loop(agent)
        all_stats.append(("Basic Loop", s))

        # Section 3: File Ops
        s = await demo_file_ops(agent)
        all_stats.append(("File Operations", s))

        # Section 4: Search & Shell
        s = await demo_search(agent)
        all_stats.append(("Search & Shell", s))

        # Section 5: Git
        s = await demo_git(agent)
        all_stats.append(("Git Operations", s))

        # Section 6: Plan/Build
        s = await demo_plan(agent)
        all_stats.append(("Plan/Build Mode", s))

        # Section 7: Subagent
        s = await demo_subagent(agent)
        all_stats.append(("Subagent", s))

        # Section 8: Undo/Redo & Memory
        s = await demo_undo_memory(agent)
        all_stats.append(("Undo/Redo & Memory", s))

        # Section 9: Session Persistence
        s = await demo_session(agent, session_mgr)
        all_stats.append(("Session Persistence", s))

    except KeyboardInterrupt:
        console.print("\n\n  Demo interrupted by user.", style="yellow")

    # Final summary
    total_duration = time.monotonic() - total_start

    banner("Demo Complete!")

    summary_table = Table(
        title="Session Summary", width=W, show_header=True, header_style="bold cyan"
    )
    summary_table.add_column("Section", style="bold")
    summary_table.add_column("Iterations", justify="right")
    summary_table.add_column("Tools", justify="right")
    summary_table.add_column("Tool Names", max_width=35)

    total_iterations: int = 0
    total_tools: int = 0
    for name, s in all_stats:
        total_iterations += s["iterations"]
        total_tools += s["tools_called"]
        tools = ", ".join(s["tool_names"][:5])
        if len(s["tool_names"]) > 5:
            tools += f" +{len(s['tool_names']) - 5}"
        summary_table.add_row(
            name,
            str(s["iterations"]),
            str(s["tools_called"]),
            tools or "—",
        )

    summary_table.add_section()
    summary_table.add_row(
        "TOTAL", str(total_iterations), str(total_tools), "", style="bold"
    )

    console.print(summary_table)
    console.print()
    console.print(f"  Total duration: {total_duration:.1f}s", style="bold")
    console.print(f"  Total iterations: {total_iterations}", style="bold")
    console.print(f"  Total tool calls: {total_tools}", style="bold")
    console.print()

    # Cleanup
    console.print("  Cleaning up demo workspace...", style="dim")
    if DEMO_WORKSPACE.exists():
        shutil.rmtree(DEMO_WORKSPACE)
    console.print("  Done!", style="green")
    console.print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n\n  Demo cancelled.", style="yellow")
