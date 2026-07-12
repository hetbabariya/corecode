from pathlib import Path

import typer

app = typer.Typer(
    name="coding-agent",
    help="AI-powered coding agent with multi-model LLM support",
    no_args_is_help=True,
)


@app.command()
def run(
    prompt: str = "",
    model: str = "claude-3-5-sonnet-20241022",
    workspace: Path = Path("."),
    permission_level: str = "write",
    sandbox: bool = True,
    log_level: str = "INFO",
) -> None:
    """Start an interactive coding agent session."""
    from coding_agent.logging import setup_logging

    setup_logging(level=log_level)

    if prompt:
        typer.echo(f"Starting agent with prompt: {prompt}")
        typer.echo(f"Model: {model}")
        typer.echo(f"Workspace: {workspace.resolve()}")
        typer.echo(f"Permission level: {permission_level}")
        typer.echo(f"Sandbox: {'enabled' if sandbox else 'disabled'}")
    else:
        typer.echo("Interactive mode coming soon. Use --prompt to start with a task.")


@app.command()
def config() -> None:
    """Show current configuration."""
    from coding_agent.config import Settings

    settings = Settings()
    typer.echo(f"LLM Model: {settings.llm_model}")
    typer.echo(f"Max Iterations: {settings.max_iterations}")
    typer.echo(f"Max Tokens: {settings.max_tokens}")
    typer.echo(f"Permission Level: {settings.permission_level}")
    typer.echo(f"Sandbox Enabled: {settings.sandbox_enabled}")
    typer.echo(f"Sandbox Timeout: {settings.sandbox_timeout}s")
    typer.echo(f"Log Level: {settings.log_level}")
    typer.echo(f"DB Path: {settings.get_db_path()}")


@app.command()
def version() -> None:
    """Show version information."""
    typer.echo("coding-agent v0.1.0")
    typer.echo("Python 3.12+")
    typer.echo("Built with Textual, LiteLLM, Docker")


if __name__ == "__main__":
    app()
