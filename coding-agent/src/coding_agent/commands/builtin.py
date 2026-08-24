"""Built-in slash commands."""

from __future__ import annotations

from typing import Any

from coding_agent.commands.registry import CommandContext
from coding_agent.commands.types import Command

# ------------------------------------------------------------------
# /help
# ------------------------------------------------------------------

async def _help_handler(ctx: CommandContext, args: str) -> str:
    """List available commands."""
    from coding_agent.commands import get_registry

    registry = get_registry()
    lines = ["Available commands:"]
    for cmd in registry.list_commands():
        lines.append(f"  /{cmd.name:<14s} {cmd.description}")
    lines.append("")
    lines.append("Unknown /commands are sent to the agent as messages.")
    return "\n".join(lines)


# ------------------------------------------------------------------
# /clear
# ------------------------------------------------------------------

async def _clear_handler(ctx: CommandContext, args: str) -> str:
    """Reset conversation (keep session)."""
    if ctx.repl._agent and ctx.repl._agent.context:
        ctx.repl._agent.context.clear()
    ctx.repl.action_clear()
    return "Conversation cleared."


# ------------------------------------------------------------------
# /compact
# ------------------------------------------------------------------

async def _compact_handler(ctx: CommandContext, args: str) -> str:
    """Force summarization of context."""
    if not ctx.repl._agent:
        return "Agent not initialized."

    agent = ctx.repl._agent
    if agent.summary_llm_client is None and not agent.llm_client:
        return "No LLM client available for summarization."

    ctx.repl._show_system("Summarizing context...", "warning")
    await agent._summarize_context()

    tokens = agent.context.estimate_tokens()
    max_tokens = agent.context.max_tokens
    pct = tokens / max_tokens if max_tokens > 0 else 0
    return f"Context compacted. Now using {tokens:,} / {max_tokens:,} tokens ({pct:.0%})"


# ------------------------------------------------------------------
# /cost
# ------------------------------------------------------------------

async def _cost_handler(ctx: CommandContext, args: str) -> str:
    """Show current session cost."""
    repl = ctx.repl
    usage = repl._agent.llm_client.total_usage if repl._agent else None

    prompt = repl._prompt_tokens
    completion = repl._completion_tokens
    cost = repl._cost

    if usage and usage.estimated_cost > 0:
        cost = usage.estimated_cost
    if usage:
        prompt = usage.prompt_tokens
        completion = usage.completion_tokens

    total = prompt + completion
    return (
        f"Session cost: ${cost:.6f}\n"
        f"Tokens: {prompt:,} prompt + {completion:,} completion = {total:,} total"
    )


# ------------------------------------------------------------------
# /tokens
# ------------------------------------------------------------------

async def _tokens_handler(ctx: CommandContext, args: str) -> str:
    """Show token usage breakdown."""
    repl = ctx.repl
    agent = repl._agent
    if not agent:
        return "Agent not initialized."

    usage = agent.llm_client.total_usage
    max_tokens = agent.context.max_tokens
    current = agent.context.estimate_tokens()
    pct = current / max_tokens if max_tokens > 0 else 0

    lines = [
        f"Context window: {current:,} / {max_tokens:,} ({pct:.0%})",
        f"LLM calls:      {usage.prompt_tokens:,} prompt + {usage.completion_tokens:,} completion",
        f"Total this run: {repl._prompt_tokens + repl._completion_tokens:,} tokens",
    ]

    if agent.summary_llm_client:
        lines.append("Summary model:  (separate client)")

    return "\n".join(lines)


# ------------------------------------------------------------------
# /model
# ------------------------------------------------------------------

async def _model_handler(ctx: CommandContext, args: str) -> str:
    """Switch model or show available models.

    /model              — show numbered list of all available models
    /model <name>       — switch to that model
    /model add <provider> <name> [--base-url URL] — add custom model
    /model remove <name> — remove a custom model
    """
    repl = ctx.repl
    agent = repl._agent
    if not agent:
        return "Agent not initialized."

    registry = repl._model_registry
    if not registry:
        return "Model registry not available."

    if not args.strip():
        return _format_model_list(registry, repl._model_name)

    parts = args.strip().split(None, 1)
    subcmd = parts[0].lower()

    # /model add <provider> <name> [--base-url URL]
    if subcmd == "add" and len(parts) > 1:
        return await _model_add(registry, parts[1])

    # /model remove <name>
    if subcmd == "remove" and len(parts) > 1:
        return await _model_remove(registry, parts[1].strip())

    # /model <name> — switch
    model_name = args.strip()
    entry = registry.resolve(model_name)
    if not entry:
        # Try as raw name on default provider
        entry = registry.resolve_or_raw(model_name)

    # Check API key availability
    if not entry.api_key:
        prov = registry.get_provider(entry.provider)
        env_name = prov.api_key_env if prov else "UNKNOWN"
        return (
            f"No API key for {entry.provider}. "
            f"Set {env_name} in your .env file."
        )

    # Perform the switch
    old_model = repl._model_name
    old_provider = repl._provider_name
    old_tokens = agent.llm_client.total_usage.prompt_tokens + agent.llm_client.total_usage.completion_tokens
    old_cost = agent.llm_client.total_usage.estimated_cost

    agent.llm_client.switch_model(
        model=entry.name,
        provider=entry.provider,
        api_key=entry.api_key,
        base_url=entry.base_url,
        extra_headers=entry.extra_headers,
        sdk=entry.sdk,
    )

    repl._model_name = entry.name
    repl._provider_name = entry.provider

    # Update status bar
    try:
        status_bar = repl.query_one("#status-bar")
        status_bar.update_stats(model=f"{entry.name} ({entry.provider})")
    except Exception:
        pass

    lines = [f"Switched to: {entry.name} ({entry.provider}) [{entry.tier}]"]
    if old_tokens > 0:
        lines.insert(
            0,
            f"Previous: {old_tokens:,} tokens, ${old_cost:.4f} cost "
            f"({old_model} — {old_provider}).",
        )
    return "\n".join(lines)


def _format_model_list(registry: Any, current_model: str) -> str:
    """Format a numbered list of available models."""
    models = registry.list_models()
    if not models:
        return "No models available. Add one with: /model add <provider> <name> --base-url URL"

    lines = [
        f"  Current: {current_model} ({registry.default_provider})",
        "",
        "  #   Model                              Provider      Tier",
        "  " + "\u2500" * 65,
    ]
    for i, m in enumerate(models, 1):
        marker = " (active)" if m.name == current_model else ""
        default = " (default)" if m.is_default else ""
        name_str = f"{m.name}{default}{marker}"
        if len(name_str) > 36:
            name_str = name_str[:33] + "..."
        lines.append(
            f"  {i:<4} {name_str:<36} {m.provider:<14} {m.tier}"
        )

    lines.extend([
        "",
        "  Usage: /model <name>  |  /model add <provider> <name> --base-url URL",
        "  Aliases: /fast (cheapest), /smart (most capable)",
    ])
    return "\n".join(lines)


async def _model_add(registry: Any, args: str) -> str:
    """Handle /model add <provider> <name> [--base-url URL]."""
    import shlex
    try:
        tokens = shlex.split(args)
    except ValueError:
        tokens = args.split()

    if len(tokens) < 2:
        return "Usage: /model add <provider> <name> [--base-url URL]"

    provider = tokens[0]
    name = tokens[1]
    base_url = None

    # Parse --base-url
    for i, t in enumerate(tokens):
        if t == "--base-url" and i + 1 < len(tokens):
            base_url = tokens[i + 1]

    if not base_url:
        prov = registry.get_provider(provider)
        if prov and prov.base_url:
            base_url = prov.base_url
        else:
            return f"base_url required for new provider '{provider}'. Use: --base-url URL"

    ok = await registry.add_model(
        provider=provider,
        name=name,
        base_url=base_url,
    )
    if ok:
        return f"Added {name} to provider {provider}. Use /model {name} to switch."
    return "Failed to add model. Check provider name and base_url."


async def _model_remove(registry: Any, name: str) -> str:
    """Handle /model remove <name>."""
    ok = await registry.remove_model(name)
    if ok:
        return f"Removed model: {name}"
    return f"Model '{name}' not found."


# ------------------------------------------------------------------
# /fast
# ------------------------------------------------------------------

async def _fast_handler(ctx: CommandContext, args: str) -> str:
    """Switch to the fastest available model."""
    return await _switch_by_tier(ctx, "fast")


# ------------------------------------------------------------------
# /smart
# ------------------------------------------------------------------

async def _smart_handler(ctx: CommandContext, args: str) -> str:
    """Switch to the most capable available model."""
    return await _switch_by_tier(ctx, "smart")


async def _switch_by_tier(ctx: CommandContext, tier: str) -> str:
    """Switch to the best model for a given tier."""
    repl = ctx.repl
    agent = repl._agent
    if not agent:
        return "Agent not initialized."

    registry = repl._model_registry
    if not registry:
        return "Model registry not available."

    entry = registry.get_by_tier(tier)
    if not entry:
        return f"No '{tier}' model available."

    if not entry.api_key:
        prov = registry.get_provider(entry.provider)
        env_name = prov.api_key_env if prov else "UNKNOWN"
        return (
            f"No API key for {entry.provider}. "
            f"Set {env_name} in your .env file."
        )

    agent.llm_client.switch_model(
        model=entry.name,
        provider=entry.provider,
        api_key=entry.api_key,
        base_url=entry.base_url,
        extra_headers=entry.extra_headers,
        sdk=entry.sdk,
    )

    repl._model_name = entry.name
    repl._provider_name = entry.provider

    try:
        status_bar = repl.query_one("#status-bar")
        status_bar.update_stats(model=f"{entry.name} ({entry.provider})")
    except Exception:
        pass

    return f"Switched to: {entry.name} ({entry.provider}) [{tier}]"


# ------------------------------------------------------------------
# /permissions
# ------------------------------------------------------------------

async def _permissions_handler(ctx: CommandContext, args: str) -> str:
    """Show or change permission mode."""
    from coding_agent.agent.permissions import PermissionMode

    agent = ctx.repl._agent
    if not agent:
        return "Agent not initialized."

    pm = agent.permissions

    if not args:
        return f"Current permission mode: {pm.mode.value}"

    mode_map = {m.value: m for m in PermissionMode}
    mode_map[">"] = PermissionMode.DEFAULT
    mode_map[">>"] = PermissionMode.ACCEPT_EDITS
    mode_map["?"] = PermissionMode.PLAN
    mode_map["!"] = PermissionMode.BYPASS

    mode = mode_map.get(args)
    if mode is None:
        valid = ", ".join(m.value for m in PermissionMode)
        return f"Unknown mode: {args}. Options: {valid} (or >, >>, ?, !)"

    warning = pm.set_mode(mode, str(ctx.workspace))
    result = f"Permission mode: {mode.value}"
    if warning:
        result += f"\n{warning}"
    return result


# ------------------------------------------------------------------
# /plan
# ------------------------------------------------------------------

async def _plan_handler(ctx: CommandContext, args: str) -> str:
    """Enter plan mode or show current plan state."""
    agent = ctx.repl._agent
    if not agent:
        return "Agent not initialized."

    # If already in plan mode, show current plan
    if agent._plan_mode:
        prompt = agent.plan_manager.to_prompt()
        if prompt:
            return prompt
        return "In plan mode. No plan created yet — the agent will create one on its next turn."

    # Enter plan mode
    agent.set_plan_mode(True)

    # Auto-create plan template if no plan exists
    if not agent.plan_manager.has_plan:
        goal = args.strip() if args.strip() else "Implementation plan"
        agent.plan_manager.create_plan(
            goal=goal,
            steps=[
                "Analyze codebase and understand current state",
                "Identify files and changes needed",
                "Design the implementation approach",
                "List specific changes with file:line references",
                "Identify risks, edge cases, and testing strategy",
            ],
        )

    return (
        "Plan mode enabled. Only read-only tools available.\n"
        "The agent can read files, search code, and create plans, but cannot write.\n"
        "Use /build to exit plan mode and start execution."
    )


# ------------------------------------------------------------------
# /build
# ------------------------------------------------------------------

async def _build_handler(ctx: CommandContext, args: str) -> str:
    """Exit plan mode and enter execution mode."""
    agent = ctx.repl._agent
    if not agent:
        return "Agent not initialized."

    if not agent._plan_mode:
        return "Already in execution mode."

    agent.set_plan_mode(False)

    if agent.plan_manager.has_plan:
        return f"Execution mode active. Plan: {agent.plan_manager.plan.goal}"
    return "Execution mode active."


# ------------------------------------------------------------------
# /memory
# ------------------------------------------------------------------

async def _memory_handler(ctx: CommandContext, args: str) -> str:
    """Show or search memories."""
    agent = ctx.repl._agent
    if not agent or not agent.memory_manager:
        return "Memory system not available."

    mm = agent.memory_manager

    if args.lower() == "clear":
        mm.clear_working()
        return "Working memory cleared."

    memories = await mm.recall(
        query=args,
        workspace=str(ctx.workspace),
        limit=10,
    )

    if not memories:
        msg = "No memories found."
        if args:
            msg += " Try /memory (no args) to list all."
        return msg

    lines = [f"Memories ({len(memories)}):"]
    for m in memories:
        score = mm.score_memory(m)
        tags = f" [{', '.join(m.tags)}]" if m.tags else ""
        preview = m.content[:80] + "..." if len(m.content) > 80 else m.content
        lines.append(f"  [{score:.2f}] ({m.memory_type}){tags} {preview}")

    return "\n".join(lines)


# ------------------------------------------------------------------
# /rewind
# ------------------------------------------------------------------

async def _rewind_handler(ctx: CommandContext, args: str) -> str:
    """Show checkpoints and restore one."""
    from coding_agent.agent.undo import UndoManager
    from coding_agent.tools.undo import get_undo_manager

    manager = get_undo_manager()
    if not manager:
        return "Undo system not available."

    if not args:
        entries = manager.list_entries(limit=10)
        if not entries:
            return "No checkpoints available."

        lines = ["Recent checkpoints:"]
        for i, e in enumerate(entries):
            desc = e.description or f"{e.tool_name} on {e.file_path}"
            lines.append(f"  {i + 1}. {desc}")
        lines.append("\nUsage: /rewind <number> to restore, or use Ctrl+Z to undo.")
    return "\n".join(lines)


# ------------------------------------------------------------------
# /resume
# ------------------------------------------------------------------

async def _resume_handler(ctx: CommandContext, args: str) -> str:
    """Show session picker or resume a specific session.

    /resume          — show numbered list of recent sessions
    /resume <number>  — resume that session from the list
    /resume <id>      — resume by session ID directly
    """
    agent = ctx.repl._agent
    if not agent or not agent.session_manager:
        return "Session persistence not available."

    sessions = await agent.session_manager.list_sessions(limit=20)
    if not sessions:
        return "No previous sessions found."

    if args.strip():
        arg = args.strip()

        # Try as a number first
        try:
            idx = int(arg) - 1
            if 0 <= idx < len(sessions):
                session_id = sessions[idx].id
                return await _do_resume(ctx, session_id)
            return f"Invalid number. Choose 1-{len(sessions)}."
        except ValueError:
            pass

        # Try as a session ID
        for s in sessions:
            if s.id == arg:
                return await _do_resume(ctx, arg)
        return f"Session {arg} not found."

    # Show numbered list
    lines = [
        "  #   ID             Date         Model                 Tokens   Summary",
        "  " + "\u2500" * 80,
    ]
    for i, s in enumerate(sessions, 1):
        date = s.created_at[:10] if s.created_at else "?"
        model = (s.model or "?")[:20]
        tokens = f"{s.total_tokens:,}" if s.total_tokens else "0"
        summary = (s.summary or "(no summary)")[:25]
        lines.append(
            f"  {i:<4} {s.id:<14} {date:<12} {model:<20} {tokens:>8}  {summary}"
        )
    lines.append("")
    lines.append("  Usage: /resume <number> or /resume <session-id>")
    return "\n".join(lines)


async def _do_resume(ctx: CommandContext, session_id: str) -> str:
    """Load and restore a session into the current REPL."""
    agent = ctx.repl._agent
    if not agent or not agent.session_manager:
        return "Session persistence not available."

    messages = await agent.session_manager.load_session(session_id)
    if not messages:
        return f"Session {session_id} has no messages."

    # Rebuild context
    agent.context.clear()
    for msg in messages:
        if msg.role == "user":
            agent.context.add_user_message(msg.content)
        elif msg.role == "assistant":
            agent.context.add_assistant_message(msg.content, msg.tool_calls)
        elif msg.role == "tool" and msg.tool_call_id:
            agent.context.add_tool_result(
                msg.tool_call_id, msg.name or "", msg.content,
            )

    # Point agent at the same session
    agent.session_id = session_id

    # Restore undo stack for this session
    agent.undo_manager.init_session(session_id)

    # Update the REPL's internal session tracking
    ctx.repl._resume_session_id = session_id

    # Display messages in the chat view
    await ctx.repl._display_session_messages(messages)

    info = await agent.session_manager.get_session(session_id)
    date = info.created_at[:10] if info and info.created_at else "?"
    undo_info = ""
    if agent.undo_manager.undo_count:
        undo_info = f" ({agent.undo_manager.undo_count} undoable)"
    return (
        f"Resumed session {session_id} from {date}. "
        f"{len(messages)} messages loaded.{undo_info}"
    )


# ------------------------------------------------------------------
# /rename
# ------------------------------------------------------------------

async def _rename_handler(ctx: CommandContext, args: str) -> str:
    """Rename a session summary.

    /rename <new name>           — rename current session
    /rename <number> <new name>  — rename session from /resume list
    /rename <id> <new name>      — rename by session ID
    """
    agent = ctx.repl._agent
    if not agent or not agent.session_manager:
        return "Session persistence not available."

    if not args.strip():
        return "Usage: /rename <new name>  or  /rename <id> <new name>"

    sessions = await agent.session_manager.list_sessions(limit=20)

    # Try parsing "<number> <rest>" pattern
    parts = args.strip().split(None, 1)
    if len(parts) == 2:
        first, rest = parts
        # Try as number
        try:
            idx = int(first) - 1
            if 0 <= idx < len(sessions):
                session_id = sessions[idx].id
                await agent.session_manager.update_session_summary(
                    session_id, rest,
                )
                return f"Renamed session {session_id} to: {rest}"
        except ValueError:
            pass
        # Try as session ID
        for s in sessions:
            if s.id == first:
                await agent.session_manager.update_session_summary(
                    first, rest,
                )
                return f"Renamed session {first} to: {rest}"

    # Default: rename current session
    if not agent.session_id:
        return "No active session to rename."

    await agent.session_manager.update_session_summary(
        agent.session_id, args.strip(),
    )
    return f"Current session renamed to: {args.strip()}"

    try:
        idx = int(args) - 1
        entries = manager.list_entries(limit=20)
        if idx < 0 or idx >= len(entries):
            return f"Invalid checkpoint number. Choose 1-{len(entries)}."

        entry = entries[idx]
        UndoManager.apply_entry(entry, redo=False)
        desc = entry.description or f"{entry.tool_name} on {entry.file_path}"
        return f"Restored: {desc}"
    except ValueError:
        return "Usage: /rewind <number>"


# ------------------------------------------------------------------
# /history
# ------------------------------------------------------------------

async def _history_handler(ctx: CommandContext, args: str) -> str:
    """Show session history."""
    agent = ctx.repl._agent
    if not agent or not agent.session_manager:
        return "Session persistence not available."

    sessions = await agent.session_manager.list_sessions(limit=10)
    if not sessions:
        return "No previous sessions found."

    lines = ["Recent sessions:"]
    for s in sessions:
        date = s.created_at[:10] if s.created_at else "?"
        model = s.model or "unknown"
        tokens = f"{s.total_tokens:,}" if s.total_tokens else "0"
        cost = f"${s.total_cost:.4f}" if s.total_cost else "$0"
        summary = s.summary[:40] + "..." if s.summary and len(s.summary) > 40 else (s.summary or "(no summary)")
        lines.append(f"  {s.id}  {date}  {model:<20s}  {tokens:>10s} tokens  {cost:>8s}  {summary}")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Public: all built-in commands
# ------------------------------------------------------------------

def get_builtin_commands() -> list[Command]:
    """Return all built-in commands."""
    return [
        Command(
            name="help",
            description="List available commands",
            handler=_help_handler,
            usage="/help",
            aliases=["?"],
        ),
        Command(
            name="clear",
            description="Reset conversation (keep session)",
            handler=_clear_handler,
            usage="/clear",
        ),
        Command(
            name="compact",
            description="Force summarization of context",
            handler=_compact_handler,
            usage="/compact",
        ),
        Command(
            name="cost",
            description="Show current session cost",
            handler=_cost_handler,
            usage="/cost",
        ),
        Command(
            name="tokens",
            description="Show token usage breakdown",
            handler=_tokens_handler,
            usage="/tokens",
        ),
        Command(
            name="model",
            description="Switch model or show available models",
            handler=_model_handler,
            usage="/model [name|add|remove]",
        ),
        Command(
            name="fast",
            description="Switch to fastest model",
            handler=_fast_handler,
            usage="/fast",
        ),
        Command(
            name="smart",
            description="Switch to most capable model",
            handler=_smart_handler,
            usage="/smart",
        ),
        Command(
            name="permissions",
            description="Show/change permission mode",
            handler=_permissions_handler,
            usage="/permissions [mode]",
            aliases=[">", ">>"],
        ),
        Command(
            name="plan",
            description="Enter plan mode (read-only) or show current plan",
            handler=_plan_handler,
            usage="/plan [goal]",
        ),
        Command(
            name="build",
            description="Exit plan mode and start execution",
            handler=_build_handler,
            usage="/build",
        ),
        Command(
            name="memory",
            description="Show/search memories",
            handler=_memory_handler,
            usage="/memory [query|clear]",
        ),
        Command(
            name="rewind",
            description="Restore a checkpoint",
            handler=_rewind_handler,
            usage="/rewind [number]",
        ),
        Command(
            name="history",
            description="Show session history",
            handler=_history_handler,
            usage="/history",
        ),
        Command(
            name="resume",
            description="Resume a previous session",
            handler=_resume_handler,
            usage="/resume [number|session-id]",
        ),
        Command(
            name="rename",
            description="Rename session summary",
            handler=_rename_handler,
            usage="/rename <new name> or /rename <id> <name>",
        ),
    ]
