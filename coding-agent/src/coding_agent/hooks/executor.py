"""Hook command execution with timeout and error handling."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from coding_agent.hooks.types import HookConfig, HookEvent, HookResult
from coding_agent.logging import logger


async def run_hook(
    hook: HookConfig,
    event: HookEvent,
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
    tool_output: str = "",
    workspace: str = "",
) -> HookResult:
    """Execute a hook command as an async subprocess.

    Environment variables passed to the hook:
      $TOOL_NAME, $TOOL_ARGS (JSON), $TOOL_PATH, $TOOL_RESULT, $WORKSPACE

    Exit codes:
      0 = success
      1 = warning (log but continue)
      2 = block (prevent the action)

    Returns a HookResult with exit code, stdout, stderr, and blocked flag.
    """
    tool_path = ""
    if tool_args and isinstance(tool_args, dict):
        tool_path = str(tool_args.get("path", ""))

    env_vars = {
        **os.environ,
        "TOOL_NAME": tool_name,
        "TOOL_ARGS": str(tool_args) if tool_args else "",
        "TOOL_PATH": tool_path,
        "TOOL_RESULT": tool_output[:4096],  # truncate large outputs
        "WORKSPACE": workspace,
        **hook.env,
    }

    timeout_s = hook.timeout_ms / 1000.0

    try:
        proc = await asyncio.create_subprocess_shell(
            hook.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_vars,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning(
                "hook_timeout",
                command=hook.command,
                timeout_ms=hook.timeout_ms,
            )
            return HookResult(
                event=event,
                tool_name=tool_name,
                exit_code=-1,
                stdout="",
                stderr=f"Hook timed out after {hook.timeout_ms}ms",
                blocked=False,
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode or 0

        if exit_code == 2:
            logger.info(
                "hook_blocked",
                command=hook.command,
                tool=tool_name,
                stderr=stderr[:200],
            )
            return HookResult(
                event=event,
                tool_name=tool_name,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                blocked=True,
            )

        if exit_code != 0:
            logger.warning(
                "hook_warning",
                command=hook.command,
                exit_code=exit_code,
                stderr=stderr[:200],
            )

        if exit_code == 0 and stdout:
            logger.debug(
                "hook_output",
                command=hook.command,
                tool=tool_name,
                output=stdout[:200],
            )

        return HookResult(
            event=event,
            tool_name=tool_name,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            blocked=False,
        )

    except Exception as exc:
        logger.error(
            "hook_error",
            command=hook.command,
            error=str(exc),
        )
        return HookResult(
            event=event,
            tool_name=tool_name,
            exit_code=-1,
            stdout="",
            stderr=str(exc),
            blocked=False,
        )
