"""Shell execution tool."""

from __future__ import annotations

import asyncio
import sys

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool


@tool(
    name="execute_command",
    description=(
        "Execute a shell command and return its output. "
        "Captures stdout, stderr, and exit code."
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
        Working directory. None = current directory.
    """
    if not command.strip():
        return ToolResult(success=False, error="Command cannot be empty")

    # Use shell=True on Windows for commands like "dir", "echo", etc.
    use_shell = sys.platform == "win32"

    logger.debug("execute_command", command=command, cwd=cwd, timeout=timeout)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            shell=use_shell,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except TimeoutError:
        proc.kill()  # type: ignore[union-attr]
        await proc.wait()  # type: ignore[union-attr]
        return ToolResult(
            success=False,
            error=f"Command timed out after {timeout} seconds",
            metadata={"timeout": True, "exit_code": -1},
        )
    except OSError as exc:
        return ToolResult(
            success=False,
            error=f"Failed to execute command: {exc}",
        )

    exit_code = proc.returncode or 0  # type: ignore[union-attr]
    stdout_text = stdout.decode("utf-8", errors="replace").strip()  # type: ignore[union-attr]
    stderr_text = stderr.decode("utf-8", errors="replace").strip()  # type: ignore[union-attr]

    # Build output combining stdout and stderr
    parts: list[str] = []
    if stdout_text:
        parts.append(stdout_text)
    if stderr_text:
        parts.append(f"STDERR:\n{stderr_text}")

    output = "\n\n".join(parts) if parts else "(no output)"

    logger.debug(
        "execute_command",
        command=command,
        exit_code=exit_code,
        stdout_len=len(stdout_text),
        stderr_len=len(stderr_text),
    )

    return ToolResult(
        success=exit_code == 0,
        output=output,
        error=stderr_text if exit_code != 0 and stderr_text else None,
        metadata={
            "exit_code": exit_code,
            "stdout_len": len(stdout_text),
            "stderr_len": len(stderr_text),
        },
    )
