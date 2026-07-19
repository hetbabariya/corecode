"""Shell execution tool — routes through Docker sandbox when enabled."""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

from coding_agent.logging import logger
from coding_agent.sandbox.danger_patterns import check_dangerous_command
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool

if TYPE_CHECKING:
    from coding_agent.sandbox.executor import SandboxExecutor


# ---------------------------------------------------------------------------
# Cross-platform command normalization
# ---------------------------------------------------------------------------


_UNIX_TO_WIN: list[tuple[re.Pattern[str], str]] = []


def _add_xlate(pattern: str, replacement: str) -> None:
    """Register a Unix→Windows command translation rule."""
    _UNIX_TO_WIN.append((re.compile(pattern, re.IGNORECASE), replacement))


# Common Unix commands and their Windows CMD equivalents
# mkdir -p: CMD's mkdir creates intermediate dirs in modern Windows, just strip -p
_add_xlate(r"\bmkdir\s+-p\b", "mkdir")
_add_xlate(r"\brm\s+-rf\b", "rmdir /s /q")
_add_xlate(r"\brm\s+-r\b", "rmdir /s")
_add_xlate(r"\brm\s+-f\b", "del /f")
_add_xlate(r"\bcat\b", "type")
_add_xlate(r"\bcp\s+(-[a-zA-Z]+\s+)?", "copy ")
_add_xlate(r"\bmv\b", "move")
_add_xlate(r"\bwhich\b", "where")
_add_xlate(r"\bgrep\b", "findstr")
_add_xlate(r"\bless\b", "more")
_add_xlate(r"\bclear\b", "cls")
_add_xlate(r"\btouch\b", "copy /b nul+")
_add_xlate(r"\bhead\b", "more")
_add_xlate(r"\bwc\s+-l\b", "find /c /v \"\"")


def _xlate_command(command: str) -> str:
    """Translate Unix shell commands to Windows equivalents.

    Only applies when running on Windows (``sys.platform == "win32"``).
    Uses a set of regex-based substitution rules for common commands.
    """
    if sys.platform != "win32":
        return command

    result = command
    for pattern, replacement in _UNIX_TO_WIN:
        result = pattern.sub(replacement, result)
    return result

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

    # Cross-platform: translate Unix commands to Windows equivalents
    translated = _xlate_command(command)
    if translated != command:
        logger.debug(
            "command_translated",
            original=command,
            translated=translated,
            platform=sys.platform,
        )

    # Dangerous command check
    from coding_agent.config import Settings

    settings = Settings()
    if settings.block_dangerous_commands:
        result = check_dangerous_command(translated)
        if result.is_dangerous:
            logger.warning(
                "dangerous_command_blocked",
                command=command,
                translated=translated,
                reason=result.reason,
            )
            return ToolResult(success=False, error=f"Blocked: {result.reason}")

    executor = await _get_executor()
    result = await executor.execute(
        translated,
        timeout=timeout,
        cwd=cwd,
    )
    # Log translation in output metadata so the LLM knows about it
    if translated != command and result.metadata is not None:
        result.metadata["command_original"] = command
        result.metadata["command_translated"] = translated
    return result
