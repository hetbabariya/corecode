from __future__ import annotations

import asyncio
import importlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer

# Register all tools via side-effect import
importlib.import_module("coding_agent.tools")

app = typer.Typer(
    name="coding-agent",
    help="AI-powered coding agent with multi-model LLM support",
    no_args_is_help=True,
)


def _event_dict(data: Any) -> dict[str, Any]:
    """Safely extract a dict from AgentEvent.data."""
    if isinstance(data, dict):
        return data
    return {}


def _truncate(text: str, max_lines: int = 5, max_chars: int = 500) -> str:
    """Truncate tool result for display."""
    if not text:
        return "(empty)"
    lines = text.split("\n")
    if len(lines) > max_lines:
        truncated = "\n".join(lines[:max_lines])
        remaining = len(lines) - max_lines
        return f"{truncated}\n  ... ({remaining} more lines)"
    if len(text) > max_chars:
        return text[:max_chars] + f"\n  ... ({len(text) - max_chars} more chars)"
    return text


def _format_args(args: dict[str, Any] | str, max_len: int = 120) -> str:
    """Format tool arguments for display."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return args[:max_len]

    # Special formatting for common tools
    if "path" in args:
        path = args["path"]
        if "content" in args:
            content_preview = args["content"][:60]
            if len(args["content"]) > 60:
                content_preview += "..."
            return f"path={path} content=\"{content_preview}\""
        if "old_text" in args:
            return f"path={path} old_text={args['old_text'][:40]}..."
        if "pattern" in args:
            return f"path={path} pattern=\"{args['pattern']}\""
        return f"path={path}"
    if "query" in args:
        return f"query=\"{args['query']}\""
    if "goal" in args:
        steps = args.get("steps", [])
        return f"goal=\"{args['goal']}\" steps={len(steps)}"
    if "command" in args:
        return f"command=\"{args['command']}\""

    # Generic fallback
    s = json.dumps(args, ensure_ascii=False)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


@dataclass
class _RunStats:
    """Tracks stats across the agent run."""
    iterations: int = 0
    tools_called: int = 0
    tool_names: list[str] = field(default_factory=list)
    permission_checks: int = 0
    permission_denials: int = 0
    start_time: float = 0.0
    tool_start_time: float = 0.0
    current_tool: str = ""
    tool_args_by_id: dict[str, Any] = field(default_factory=dict)
    current_tool_args: Any = None  # kept for backward compat
    text_buffer: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0


@app.command()
def run(
    prompt: str = "",
    workspace: Path = Path("."),
    permission: str = "auto",
    log_level: str = "INFO",
    log_file: str | None = None,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug-level logging"),
    output_format: str = typer.Option("clean", "--format", "-f", help="Output format: clean or raw"),
) -> None:
    """Start a coding agent session.

    Use --prompt to provide a task. Permission modes: auto (default), confirm, deny.
    Use --verbose/-v for debug logging. Use --log-file to write logs to a file.
    Use --format raw for old-style output (default: clean).
    """
    from coding_agent.config import Settings
    from coding_agent.logging import setup_logging

    effective_level = "DEBUG" if verbose else log_level

    # Fall back to config's log_file when not passed via CLI
    if log_file is None:
        log_file = Settings().log_file

    setup_logging(level=effective_level, log_file=log_file)

    if not prompt:
        typer.echo("No prompt provided. Use --prompt to specify a task.")
        raise typer.Exit(code=1)

    if output_format == "raw":
        asyncio.run(_run_agent_raw(prompt, workspace, permission))
    else:
        asyncio.run(_run_agent_clean(prompt, workspace, permission))


async def _run_agent_clean(
    prompt: str,
    workspace: Path,
    permission: str,
) -> None:
    """Create agent loop and stream structured events to terminal."""
    from coding_agent.agent.context import ContextManager
    from coding_agent.agent.events import EventType
    from coding_agent.agent.loop import AgentLoop
    from coding_agent.agent.permission_callback import AutoApproveCallback, PromptCallback
    from coding_agent.agent.permissions import PermissionManager
    from coding_agent.config import Settings
    from coding_agent.llm.client import LLMClient

    settings = Settings()
    provider = settings.llm_provider

    # Main LLM client
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

    # Summary LLM client (may use different model)
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

    # Permission callback
    if permission == "auto":
        perm_callback = AutoApproveCallback()
    elif permission == "deny":
        perm_callback = None
    else:
        perm_callback = PromptCallback()

    permissions = PermissionManager()
    context = ContextManager(max_tokens=settings.max_tokens)

    # Session persistence + memory
    from coding_agent.session.manager import SessionManager
    from coding_agent.agent.memory import MemoryManager

    session_mgr = SessionManager(settings.get_db_path())
    await session_mgr.initialize()
    memory_mgr = MemoryManager(session_mgr)

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
    )

    W = 60  # box width

    # Header
    print()
    print(f"  \u256d\u2500 Coding Agent {'─' * (W - 16)}\u256e")
    print(f"  \u2502 Model:    {model} via {provider}")
    print(f"  \u2502 Workspace: {workspace.resolve()}")
    print(f"  \u2570{'─' * W}")

    # Prompt
    print(f"\n  \u25b8 {prompt}\n")

    stats = _RunStats(start_time=time.monotonic())

    async for event in agent.process_input(prompt):
        d = _event_dict(event.data)

        if event.type == EventType.TEXT:
            stats.text_buffer.append(str(event.data))

        elif event.type == EventType.LOOP_START:
            stats.iterations += 1
            print(f"    \u2500\u2500\u2500 iteration {stats.iterations} \u2500\u2500\u2500")

        elif event.type == EventType.TOOL_START:
            name = d.get("name", "?")
            args = d.get("args", "")
            tc_id = d.get("tc_id", "")
            stats.current_tool = name
            stats.tool_args_by_id[tc_id] = args
            stats.current_tool_args = args  # keep for backward compat
            stats.tool_start_time = time.monotonic()
            stats.tool_names.append(name)
            stats.tools_called += 1

        elif event.type == EventType.TOOL_RESULT:
            # Print tool call block
            tool_dur = (time.monotonic() - stats.tool_start_time) * 1000
            result = d.get("result", "")
            tc_id = d.get("tc_id", "")
            tool_args = stats.tool_args_by_id.pop(tc_id, stats.current_tool_args)
            if hasattr(result, "success"):
                success = result.success
                output = result.output if result.output else ""
                error = result.error or ""
            else:
                success = True
                output = str(result)
                error = ""

            icon = "\u2713" if success else "\u2717"
            args_str = _format_args(tool_args)

            # Compact display for read-only tools (no content preview)
            _READ_ONLY_TOOLS = {"read_file", "list_files", "search_content", "search_files", "git_status", "git_diff", "git_log", "refresh_index"}
            if stats.current_tool in _READ_ONLY_TOOLS and success and not error:
                # One-line summary
                file_path = tool_args.get("path", "") if isinstance(tool_args, dict) else ""
                if file_path:
                    print(f"    \u2503 {icon} {stats.current_tool} \u2192 {file_path}")
                else:
                    print(f"    \u2503 {icon} {stats.current_tool} ({tool_dur:.0f}ms)")
            else:
                # Full display for write/error tools
                print(f"    \u2503 {stats.current_tool}")
                print(f"    \u2503   args: {args_str}")
                if error:
                    print(f"    \u2503   {icon} error: {error[:200]}")
                elif output:
                    preview = _truncate(output, max_lines=3, max_chars=200)
                    for line in preview.split("\n"):
                        print(f"    \u2503   {line}")
                else:
                    print(f"    \u2503   {icon} ({tool_dur:.0f}ms)")
            print(f"    \u2502")

        elif event.type == EventType.PERMISSION_REQUEST:
            name = d.get("tool_name", "?")
            print(f"    \u2503   \u26a0 permission: {name}")

        elif event.type == EventType.PERMISSION_CHECK:
            name = d.get("tool_name", "?")
            approved = d.get("approved", False)
            stats.permission_checks += 1
            if not approved:
                stats.permission_denials += 1

        elif event.type == EventType.USAGE:
            if isinstance(d, dict):
                stats.prompt_tokens += int(d.get("prompt_tokens", 0))
                stats.completion_tokens += int(d.get("completion_tokens", 0))

        elif event.type == EventType.CONTEXT_HEALTH:
            ratio = d.get("usage_ratio", 0)
            slices = d.get("slice_count", 0)
            print(f"    \u2503   \u26a0 context at {ratio:.0%} ({slices} slices)")

        elif event.type == EventType.VERIFICATION:
            file_path = d.get("file_path", "")
            checks = d.get("checks", [])
            failed = [c for c in checks if not c.get("passed", True)]
            if failed:
                print(f"    \u2503   \u26a0 verification: {file_path}")
                for c in failed[:3]:
                    print(f"    \u2503     - [{c.get('tool', '?')}] {c.get('output', '')[:100]}")

        elif event.type == EventType.STUCK_DETECTED:
            msg = d.get("message", "")
            strategy = d.get("strategy", "")
            print(f"    \u2503   \u26a0 stuck: {msg} (strategy: {strategy})")

        elif event.type == EventType.ASK_USER:
            msg = d.get("message", "")
            print(f"    \u2503   ? {msg}")

        elif event.type == EventType.PLAN_UPDATE:
            action = d.get("action", "")
            if action == "replan_needed":
                print(f"    \u2503   \u26a0 replan needed")

        elif event.type == EventType.BUDGET_EXCEEDED:
            reason = d.get("reason", "")
            can_continue = d.get("can_continue", False)
            if reason == "cost":
                cost = d.get("cost", 0)
                limit = d.get("limit", 0)
                print(f"    \u2503   \u2717 budget exceeded (cost: ${cost:.4f} / ${limit:.4f})")
            elif reason == "time":
                elapsed = d.get("elapsed", 0)
                limit = d.get("limit", 0)
                print(f"    \u2503   \u2717 budget exceeded (time: {elapsed:.0f}s / {limit}s)")
            else:
                print(f"    \u2503   \u2717 budget exceeded ({reason})")
            if can_continue:
                print(f"    \u2503   Run again to continue from where we left off.")

        elif event.type == EventType.MAX_ITERATIONS:
            reason = d.get("reason", "unknown")
            if reason == "safety_net":
                print(f"    \u2503   \u2717 safety limit reached (this should not happen)")
            else:
                print(f"    \u2503   \u2717 max iterations reached ({d.get('iteration', '?')})")

        elif event.type == EventType.ERROR:
            err = d.get("error", str(event.data))
            print(f"    \u2503   \u2717 error: {err}")

        elif event.type == EventType.DONE:
            pass  # handled below

    duration = time.monotonic() - stats.start_time
    usage = llm_client.total_usage

    # Use loop's accumulated cost if client shows 0
    if usage.estimated_cost > 0:
        stats.cost = usage.estimated_cost
    else:
        stats.cost = agent._accumulated_cost

    # Use client's token counts if available, otherwise keep event-tracked counts
    if usage.prompt_tokens > 0:
        stats.prompt_tokens = usage.prompt_tokens
        stats.completion_tokens = usage.completion_tokens

    # Print response
    if stats.text_buffer:
        response = "".join(stats.text_buffer)
        print(f"  \u2502")
        for line in response.split("\n"):
            print(f"  \u2502 {line}")

    # Summary box
    print()
    print(f"  \u256d\u2500 Summary {'─' * (W - 10)}\u256e")
    print(f"  \u2502 Iterations:    {stats.iterations}")
    print(f"  \u2502 Tools called:  {stats.tools_called} ({', '.join(stats.tool_names) if stats.tool_names else 'none'})")
    print(f"  \u2502 Total time:    {duration:.1f}s")
    print(f"  \u2502 \u2500{'─' * (W - 4)}")
    print(f"  \u2502 Tokens:        {stats.prompt_tokens:,} prompt + {stats.completion_tokens:,} completion = {stats.prompt_tokens + stats.completion_tokens:,} total")
    print(f"  \u2502 Cost:          ${stats.cost:.4f}")
    print(f"  \u2502 \u2500{'─' * (W - 4)}")
    print(f"  \u2502 Permissions:   {stats.permission_checks} checked, {stats.permission_denials} denied")
    print(f"  \u2502 Prompt cache:  {agent.metrics['prompt_cache_hits']} hits, {agent.metrics['prompt_cache_misses']} misses")
    print(f"  \u2502 Summarizations:{agent.metrics['summarize_count']}")
    print(f"  \u2502 Context engine:{agent.metrics['context_suggestion_count']} suggestions")
    print(f"  \u2570{'─' * W}")
    print()

    # Cleanup
    await session_mgr.close()


async def _run_agent_raw(
    prompt: str,
    workspace: Path,
    permission: str,
) -> None:
    """Original raw output mode (logs inline)."""
    from coding_agent.agent.context import ContextManager
    from coding_agent.agent.events import EventType
    from coding_agent.agent.loop import AgentLoop
    from coding_agent.agent.permission_callback import AutoApproveCallback, PromptCallback
    from coding_agent.agent.permissions import PermissionManager
    from coding_agent.config import Settings
    from coding_agent.llm.client import LLMClient

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

    if permission == "auto":
        perm_callback = AutoApproveCallback()
    elif permission == "deny":
        perm_callback = None
    else:
        perm_callback = PromptCallback()

    permissions = PermissionManager()
    context = ContextManager(max_tokens=settings.max_tokens)

    from coding_agent.session.manager import SessionManager
    from coding_agent.agent.memory import MemoryManager

    session_mgr = SessionManager(settings.get_db_path())
    await session_mgr.initialize()
    memory_mgr = MemoryManager(session_mgr)

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
    )

    async for event in agent.process_input(prompt):
        d = _event_dict(event.data)
        if event.type == EventType.TEXT:
            print(str(event.data), end="", flush=True)
        elif event.type == EventType.TOOL_START:
            name = d.get("name", "?")
            args_str = d.get("args", "")
            print(f"\n  [Tool: {name}({args_str})]")
        elif event.type == EventType.TOOL_RESULT:
            print()
        elif event.type == EventType.PERMISSION_REQUEST:
            name = d.get("tool_name", "?")
            print(f"\n  [Permission: {name}]")
        elif event.type == EventType.DONE:
            print("\n")
        elif event.type == EventType.ERROR:
            err_msg = d.get("error", str(event.data))
            print(f"\n  [Error: {err_msg}]")
        elif event.type == EventType.MAX_ITERATIONS:
            reason = d.get("reason", "unknown")
            if reason == "safety_net":
                print("\n  [Safety limit reached - this should not happen]")
            else:
                print(f"\n  [Max iterations reached ({d.get('iteration', '?')})]")

    usage = llm_client.total_usage
    print(
        f"  Tokens: {usage.prompt_tokens} prompt + "
        f"{usage.completion_tokens} completion = {usage.total_tokens} total"
    )
    print(f"  Cost: ${usage.estimated_cost:.4f}")

    await session_mgr.close()


@app.command()
def config() -> None:
    """Show current configuration."""
    from coding_agent.config import Settings

    settings = Settings()
    provider, model = settings.get_summary_model()
    typer.echo(f"LLM Provider: {settings.llm_provider}")
    typer.echo(f"LLM Model: {settings.get_active_model()}")
    typer.echo(f"Summary Model: {model} ({provider})")
    typer.echo(f"Max Iterations: {settings.max_iterations}")
    typer.echo(f"Max Tokens: {settings.max_tokens}")
    typer.echo(f"Permission Level: {settings.permission_level}")
    typer.echo(f"Exec Mode: {settings.exec_mode}")
    typer.echo(f"Sandbox Timeout: {settings.sandbox_timeout}s")
    typer.echo(f"Log Level: {settings.log_level}")
    typer.echo(f"DB Path: {settings.get_db_path()}")


@app.command()
def version() -> None:
    """Show version information."""
    typer.echo("coding-agent v0.1.0")
    typer.echo("Python 3.12+")
    typer.echo("Built with Python, Google GenAI, Docker")


@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of sessions to show"),
) -> None:
    """List past session history."""
    import asyncio
    from coding_agent.config import Settings
    from coding_agent.session.manager import SessionManager

    settings = Settings()
    db_path = settings.get_db_path()
    manager = SessionManager(db_path)

    async def _list() -> None:
        await manager.initialize()
        sessions = await manager.list_sessions(limit=limit)
        await manager.close()

        if not sessions:
            typer.echo("No session history found.")
            return

        typer.echo(f"{'ID':<14} {'Date':<22} {'Model':<30} {'Tokens':>10} {'Cost':>10}")
        typer.echo("-" * 90)
        for s in sessions:
            date = s.created_at[:19].replace("T", " ")
            tokens = f"{s.total_tokens:,}" if s.total_tokens else "-"
            cost = f"${s.total_cost:.4f}" if s.total_cost else "-"
            model_str = f"{s.model}" if s.model else "-"
            typer.echo(f"{s.id:<14} {date:<22} {model_str:<30} {tokens:>10} {cost:>10}")

    asyncio.run(_list())


if __name__ == "__main__":
    app()
