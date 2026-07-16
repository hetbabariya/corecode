"""Shell execution tool — routes through Docker sandbox when enabled."""

from __future__ import annotations

from typing import TYPE_CHECKING

from coding_agent.logging import logger
from coding_agent.sandbox.danger_patterns import check_dangerous_command
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool

if TYPE_CHECKING:
    from coding_agent.sandbox.executor import SandboxExecutor

# ---------------------------------------------------------------------------
# Lazy sandbox executor singleton
# ---------------------------------------------------------------------------

_executor: SandboxExecutor | None = None


async def _get_executor() -> SandboxExecutor:
    """Return (and lazily create) the sandbox executor singleton."""
    global _executor  # noqa: PLW0603
    if _executor is not None:
        return _executor

    from coding_agent.config import Settings
    from coding_agent.sandbox.docker import DockerSandbox, SandboxError
    from coding_agent.sandbox.executor import SandboxExecutor

    settings = Settings()
    if settings.is_sandbox_mode():
        sandbox = DockerSandbox(
            image=settings.sandbox_image,
            workspace=settings.workspace,
            memory_limit=settings.sandbox_memory_limit,
            timeout=settings.sandbox_timeout,
        )
        try:
            await sandbox.start()
            logger.info("shell_sandbox_started", image=settings.sandbox_image)
        except SandboxError as exc:
            logger.warning("shell_sandbox_start_failed", error=str(exc))
            sandbox = None

        _executor = SandboxExecutor(
            sandbox=sandbox,
            fallback_to_host=True,
        )
    else:
        _executor = SandboxExecutor(sandbox=None, fallback_to_host=True)

    return _executor


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool(
    name="execute_command",
    description=(
        "Execute a shell command and return its output. "
        "Captures stdout, stderr, and exit code. "
        "Runs inside a Docker sandbox when enabled."
    ),
    permission="execute",
)
async def execute_command(
    command: str,
    timeout: int = 30,
    cwd: str | None = None,
) -> ToolResult:
    """Execute a shell command.

    Parameters
    ----------
    command:
        Shell command to execute.
    timeout:
        Maximum execution time in seconds.
    cwd:
        Working directory. None = current directory (or /workspace in sandbox).
    """
    if not command.strip():
        return ToolResult(success=False, error="Command cannot be empty")

    # Dangerous command check
    from coding_agent.config import Settings

    settings = Settings()
    if settings.block_dangerous_commands:
        result = check_dangerous_command(command)
        if result.is_dangerous:
            logger.warning(
                "dangerous_command_blocked",
                command=command,
                reason=result.reason,
            )
            return ToolResult(success=False, error=f"Blocked: {result.reason}")

    executor = await _get_executor()
    result = await executor.execute(
        command,
        timeout=timeout,
        cwd=cwd,
    )
    return result
