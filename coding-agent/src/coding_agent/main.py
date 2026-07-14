from __future__ import annotations

import asyncio
import importlib
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


def _event_dict(data: Any) -> dict[str, str]:  # type: ignore[type-arg]
    """Safely extract a str-valued dict from AgentEvent.data."""
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}  # type: ignore[misc]
    return {}


@app.command()
def run(
    prompt: str = "",
    workspace: Path = Path("."),
    permission: str = "auto",
    log_level: str = "INFO",
    log_file: str | None = None,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug-level logging"),
) -> None:
    """Start a coding agent session.

    Use --prompt for single-shot mode, or run without it to launch the TUI.
    Permission modes: auto (default), confirm, deny.
    Use --verbose/-v for debug logging. Use --log-file to write logs to a file.
    """
    from coding_agent.logging import setup_logging

    effective_level = "DEBUG" if verbose else log_level
    setup_logging(level=effective_level, log_file=log_file)

    if not prompt:
        _launch_tui(workspace)
        return

    asyncio.run(_run_agent(prompt, workspace, permission))


def _launch_tui(workspace: Path) -> None:
    """Launch the Textual TUI application."""
    from coding_agent.tui.app import CodingAgentApp

    app = CodingAgentApp(workspace=workspace)
    app.run()


async def _run_agent(
    prompt: str,
    workspace: Path,
    permission: str,
) -> None:
    """Create agent loop and stream events to terminal."""
    from coding_agent.agent.context import ContextManager
    from coding_agent.agent.events import EventType
    from coding_agent.agent.loop import AgentLoop
    from coding_agent.agent.permission_callback import AutoApproveCallback
    from coding_agent.agent.permissions import PermissionManager
    from coding_agent.config import Settings
    from coding_agent.llm.client import LLMClient

    settings = Settings()
    provider = settings.llm_provider

    # Main LLM client
    if provider == "openrouter":
        api_keys = settings.get_openrouter_api_keys()
        model = settings.openrouter_model
    else:
        api_keys = settings.get_api_keys()
        model = settings.llm_model

    llm_client = LLMClient(model=model, api_keys=api_keys, provider=provider)

    # Summary LLM client (may use different model)
    summary_provider, summary_model = settings.get_summary_model()
    if summary_model != model or summary_provider != provider:
        if summary_provider == "openrouter":
            summary_keys = settings.get_openrouter_api_keys()
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
        perm_callback = None  # Will skip denied permissions
    else:
        perm_callback = AutoApproveCallback()

    permissions = PermissionManager()
    context = ContextManager(max_tokens=settings.max_tokens)

    agent = AgentLoop(
        llm_client=llm_client,
        permission_manager=permissions,
        context_manager=context,
        workspace=workspace,
        max_iterations=settings.max_iterations,
        permission_callback=perm_callback,
        summary_llm_client=summary_client,
    )

    # Stream events to terminal
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
            print("\n  [Max iterations reached]")

    # Print summary stats
    usage = llm_client.total_usage
    print(
        f"  Tokens: {usage.prompt_tokens} prompt + "
        f"{usage.completion_tokens} completion = {usage.total_tokens} total"
    )
    print(f"  Cost: ${usage.estimated_cost:.4f}")


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
    typer.echo("Built with Textual, Google GenAI, Docker")


if __name__ == "__main__":
    app()
