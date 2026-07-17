"""Docker sandbox — persistent container for isolated command execution."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound
from docker.models.containers import Container

from coding_agent.logging import logger

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SandboxResult:
    """Structured result from a sandboxed command execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]


# ---------------------------------------------------------------------------
# DockerSandbox
# ---------------------------------------------------------------------------

# Sentinel for the keep-alive process running inside the container.
_KEEPALIVE_CMD = "sleep infinity"


class DockerSandbox:
    """Persistent Docker sandbox for command execution.

    Manages a single long-lived container.  Commands are executed inside it
    via ``docker exec``.  Call :meth:`start` before :meth:`execute` and
    :meth:`stop` when finished (or use as an async context manager)::

        async with DockerSandbox(workspace=Path(".")) as sandbox:
            result = await sandbox.execute("echo hello")
    """

    def __init__(
        self,
        image: str = "coding-agent-sandbox:latest",
        workspace: Path | str = ".",
        memory_limit: str = "512m",
        cpu_quota: int = 100_000,
        timeout: int = 30,
    ) -> None:
        self.image = image
        self.workspace = Path(workspace).resolve()
        self.memory_limit = memory_limit
        self.cpu_quota = cpu_quota
        self.default_timeout = timeout

        self._client: docker.DockerClient | None = None
        self._container: Container | None = None
        self._container_id: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create and start the persistent sandbox container."""
        logger.info(
            "sandbox_starting",
            image=self.image,
            workspace=str(self.workspace),
            memory=self.memory_limit,
        )
        try:
            self._client = docker.from_env()
        except DockerException as exc:
            logger.error("sandbox_docker_unavailable", error=str(exc))
            raise SandboxError(
                f"Docker is not running or not installed: {exc}"
            ) from exc

        # Verify image exists
        try:
            self._client.images.get(self.image)
        except ImageNotFound as exc:
            logger.warning("sandbox_image_not_found", image=self.image)
            raise SandboxError(
                f"Docker image {self.image!r} not found. "
                f"Build it first: docker build -f Dockerfile.sandbox -t {self.image} ."
            ) from exc

        # Run a persistent container with keep-alive
        try:
            self._container = self._client.containers.run(
                self.image,
                command=_KEEPALIVE_CMD,
                volumes={str(self.workspace): {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                mem_limit=self.memory_limit,
                cpu_quota=self.cpu_quota,
                detach=True,
                auto_remove=False,
            )
            self._container_id = self._container.short_id
            logger.info(
                "sandbox_started",
                container_id=self._container_id,
                image=self.image,
            )
        except DockerException as exc:
            logger.error("sandbox_start_failed", error=str(exc))
            raise SandboxError(f"Failed to start sandbox container: {exc}") from exc

    async def stop(self) -> None:
        """Stop and remove the sandbox container."""
        if self._container is None:
            return

        logger.info("sandbox_stopping", container_id=self._container_id)
        try:
            await asyncio.to_thread(self._container.stop, timeout=5)
        except Exception:
            pass  # Container may already be stopped

        try:
            await asyncio.to_thread(self._container.remove, force=True)
        except Exception:
            pass  # Already removed

        logger.info("sandbox_stopped", container_id=self._container_id)
        self._container = None
        self._container_id = None

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        command: str,
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> SandboxResult:
        """Execute a command inside the persistent container.

        Parameters
        ----------
        command:
            Shell command to run.
        timeout:
            Max seconds to wait.  ``None`` uses the instance default.
        cwd:
            Working directory inside the container (relative to /workspace).
        """
        if self._container is None:
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr="Sandbox not started. Call start() first.",
                metadata={"error": "not_started"},
            )

        if not command.strip():
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr="Command cannot be empty",
                metadata={"error": "empty_command"},
            )

        # Build the exec command
        exec_cmd = ["sh", "-c", command]
        if cwd:
            workdir = cwd if cwd.startswith("/") else f"/workspace/{cwd}"
        else:
            workdir = "/workspace"

        t0 = time.monotonic()
        timed_out = False
        try:
            if timeout and timeout > 0:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._exec_with_timeout,
                        exec_cmd,
                        workdir,
                    ),
                    timeout=timeout,
                )
            else:
                result = await asyncio.to_thread(
                    self._exec_with_timeout,
                    exec_cmd,
                    workdir,
                )
            duration_ms = (time.monotonic() - t0) * 1000

            return SandboxResult(
                exit_code=result["exit_code"],
                stdout=result["stdout"],
                stderr=result["stderr"],
                timed_out=False,
                duration_ms=duration_ms,
                metadata={
                    "container_id": self._container_id,
                    "workdir": workdir,
                },
            )

        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "sandbox_exec_timeout",
                container_id=self._container_id,
                timeout=timeout,
                duration_ms=round(duration_ms, 1),
            )
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"Container command timed out after {timeout}s",
                timed_out=True,
                duration_ms=duration_ms,
                metadata={
                    "container_id": self._container_id,
                    "timeout_s": timeout,
                },
            )

        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.error(
                "sandbox_exec_error",
                container_id=self._container_id,
                error=str(exc),
            )
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"Container execution error: {exc}",
                duration_ms=duration_ms,
                metadata={
                    "container_id": self._container_id,
                    "error": type(exc).__name__,
                },
            )

    def _exec_with_timeout(
        self,
        cmd: list[str],
        workdir: str,
    ) -> dict[str, Any]:
        """Synchronous exec inside the running container (run via to_thread)."""
        assert self._container is not None

        exec_result = self._container.exec_run(
            cmd,
            workdir=workdir,
            stdout=True,
            stderr=True,
            demux=True,
        )

        # exec_run with demux=True returns (stdout_bytes, stderr_bytes) tuple.
        # Docker SDK type stubs are incomplete — the output is a tuple, not iterator.
        output: tuple[bytes | None, bytes | None] = exec_result.output  # pyright: ignore[reportAssignmentType]
        stdout_bytes, stderr_bytes = output

        return {
            "exit_code": exec_result.exit_code,
            "stdout": (stdout_bytes or b"").decode("utf-8", errors="replace").strip(),
            "stderr": (stderr_bytes or b"").decode("utf-8", errors="replace").strip(),
            "timed_out": False,
        }

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def is_docker_available(self) -> bool:
        """Check if Docker daemon is reachable."""
        try:
            client = docker.from_env()

            def _ping() -> bool:
                client.ping()  # pyright: ignore[reportUnknownMemberType]
                return True

            return await asyncio.to_thread(_ping)
        except DockerException:
            return False

    async def is_container_running(self) -> bool:
        """Check if the sandbox container is alive."""
        if self._container is None:
            return False
        try:
            await asyncio.to_thread(self._container.reload)
            return self._container.status == "running"
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> DockerSandbox:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.stop()


# ---------------------------------------------------------------------------
# Sandbox error
# ---------------------------------------------------------------------------


class SandboxError(Exception):
    """Raised when the sandbox cannot be started or is unavailable."""
