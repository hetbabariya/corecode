"""High-level executor that routes commands through the sandbox or host."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult

from .docker import DockerSandbox, SandboxError, SandboxResult


class SandboxExecutor:
    """Routes shell commands through Docker sandbox or host fallback.

    Parameters
    ----------
    sandbox:
        An initialised :class:`DockerSandbox`.  ``None`` disables sandboxing.
    fallback_to_host:
        When ``True`` and the sandbox is unavailable, commands run directly
        on the host (with a warning).  When ``False`` (default), an error
        is returned.
    """

    def __init__(
        self,
        sandbox: DockerSandbox | None = None,
        fallback_to_host: bool = False,
    ) -> None:
        self._sandbox = sandbox
        self._fallback_to_host = fallback_to_host
        self._sandbox_unavailable_warned = False
        self._current_proc: asyncio.subprocess.Process | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        command: str,
        workspace: Path | str | None = None,
        timeout: int = 30,
        cwd: str | None = None,
    ) -> ToolResult:
        """Execute *command*, routing through the sandbox when available.

        Returns a :class:`ToolResult` compatible with the tool registry.
        """
        if not command.strip():
            return ToolResult(success=False, error="Command cannot be empty")

        # --- Try sandbox first ---
        if self._sandbox is not None:
            try:
                return await self._execute_in_sandbox(command, timeout=timeout, cwd=cwd)
            except SandboxError as exc:
                logger.warning("sandbox_unavailable", error=str(exc))
                if not self._sandbox_unavailable_warned:
                    logger.warning(
                        "sandbox_fallback_host",
                        reason=str(exc),
                    )
                    self._sandbox_unavailable_warned = True

                if not self._fallback_to_host:
                    return ToolResult(
                        success=False,
                        error=(
                            f"Sandbox unavailable: {exc}. "
                            "Set CODING_AGENT_SANDBOX_ENABLED=false to "
                            "run on the host directly."
                        ),
                    )

        # --- Host fallback ---
        return await self._execute_on_host(command, timeout=timeout, cwd=cwd)

    # ------------------------------------------------------------------
    # Sandbox execution
    # ------------------------------------------------------------------

    async def _execute_in_sandbox(
        self,
        command: str,
        timeout: int,
        cwd: str | None,
    ) -> ToolResult:
        assert self._sandbox is not None

        # Verify container is still alive
        if not await self._sandbox.is_container_running():
            logger.info("sandbox_container_dead_restarting")
            await self._sandbox.start()

        result: SandboxResult = await self._sandbox.execute(
            command, timeout=timeout, cwd=cwd
        )

        if result.timed_out:
            return ToolResult(
                success=False,
                output=result.stdout,
                error=f"Command timed out after {timeout} seconds",
                metadata={
                    "exit_code": result.exit_code,
                    "sandbox": True,
                    "timeout": True,
                    "duration_ms": result.duration_ms,
                },
            )

        parts: list[str] = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"STDERR:\n{result.stderr}")

        output = "\n\n".join(parts) if parts else "(no output)"

        return ToolResult(
            success=result.exit_code == 0,
            output=output,
            error=result.stderr if result.exit_code != 0 and result.stderr else None,
            metadata={
                "exit_code": result.exit_code,
                "sandbox": True,
                "duration_ms": result.duration_ms,
                "stdout_len": len(result.stdout),
                "stderr_len": len(result.stderr),
            },
        )

    # ------------------------------------------------------------------
    # Host execution (fallback)
    # ------------------------------------------------------------------

    async def _execute_on_host(
        self,
        command: str,
        timeout: int,
        cwd: str | None,
    ) -> ToolResult:
        """Run directly on the host — mirrors tools/shell.py logic.

        On Windows, uses CMD via ``shell=True`` to support ``&&``,
        ``dir``, ``type``, and other CMD built-ins.
        On Unix/macOS, uses ``/bin/sh -c`` via ``shell=True``.
        """
        exec_start = time.monotonic()
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                shell=True,
            )
            self._current_proc = proc
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            if proc is not None:
                proc.kill()
                await proc.wait()
                proc.close()
            self._current_proc = None
            duration_ms = (time.monotonic() - exec_start) * 1000
            logger.warning("host_exec_timeout", command=command[:200], timeout=timeout, duration_ms=round(duration_ms, 1))
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout} seconds",
                metadata={"timeout": True, "exit_code": -1, "sandbox": False},
            )
        except OSError as exc:
            if proc is not None:
                try:
                    proc.close()
                except Exception:
                    pass
            self._current_proc = None
            duration_ms = (time.monotonic() - exec_start) * 1000
            logger.error("host_exec_os_error", command=command[:200], error=str(exc), duration_ms=round(duration_ms, 1))
            return ToolResult(
                success=False,
                error=f"Failed to execute command: {exc}",
                metadata={"sandbox": False},
            )

        exit_code = proc.returncode or 0  # type: ignore[union-attr]
        self._current_proc = None
        try:
            proc.close()  # type: ignore[union-attr]
        except Exception:
            pass
        stdout_text = stdout.decode("utf-8", errors="replace").strip()  # type: ignore[union-attr]
        stderr_text = stderr.decode("utf-8", errors="replace").strip()  # type: ignore[union-attr]
        duration_ms = (time.monotonic() - exec_start) * 1000

        parts: list[str] = []
        if stdout_text:
            parts.append(stdout_text)
        if stderr_text:
            parts.append(f"STDERR:\n{stderr_text}")

        output = "\n\n".join(parts) if parts else "(no output)"

        return ToolResult(
            success=exit_code == 0,
            output=output,
            error=stderr_text if exit_code != 0 and stderr_text else None,
            metadata={
                "exit_code": exit_code,
                "sandbox": False,
                "stdout_len": len(stdout_text),
                "stderr_len": len(stderr_text),
            },
        )
