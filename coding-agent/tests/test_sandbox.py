"""Tests for Docker sandbox, executor, and exec_mode toggle."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coding_agent.sandbox.docker import DockerSandbox, SandboxError, SandboxResult
from coding_agent.sandbox.executor import SandboxExecutor
from coding_agent.tools.base import ToolResult

# ---------------------------------------------------------------------------
# Helpers — mock Docker objects
# ---------------------------------------------------------------------------


class _FakeExecResult:
    """Mimics docker.models.containers.ExecResult."""

    def __init__(
        self,
        exit_code: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.exit_code = exit_code
        self.output = (stdout, stderr)


class _FakeContainer:
    """Mimics a running Docker container."""

    def __init__(self, short_id: str = "abc1234") -> None:
        self.short_id = short_id
        self.status = "running"
        self._exec_results: list[_FakeExecResult] = []

    def exec_run(
        self,
        cmd: list[str],
        workdir: str = "/workspace",
        stdout: bool = True,
        stderr: bool = True,
        demux: bool = True,
    ) -> _FakeExecResult:
        if self._exec_results:
            return self._exec_results.pop(0)
        return _FakeExecResult(0, b"ok", b"")

    def stop(self, timeout: int = 5) -> None:
        self.status = "stopped"

    def remove(self, force: bool = True) -> None:
        self.status = "removed"

    def reload(self) -> None:
        pass


def _mock_docker_client(
    container: _FakeContainer | None = None,
    image_exists: bool = True,
    ping_ok: bool = True,
) -> MagicMock:
    """Build a mock docker.DockerClient."""
    client = MagicMock()

    if image_exists:
        client.images.get.return_value = SimpleNamespace()
    else:
        from docker.errors import ImageNotFound

        client.images.get.side_effect = ImageNotFound("not found")

    client.containers.run.return_value = container or _FakeContainer()
    client.ping.return_value = (
        {} if ping_ok else (_ for _ in ()).throw(Exception("no docker"))
    )
    return client


# ===================================================================
# SandboxResult tests
# ===================================================================


class TestSandboxResult:
    def test_defaults(self) -> None:
        r = SandboxResult(exit_code=0, stdout="hi", stderr="")
        assert r.exit_code == 0
        assert r.stdout == "hi"
        assert r.stderr == ""
        assert r.timed_out is False
        assert r.duration_ms == 0.0
        assert r.metadata == {}

    def test_with_metadata(self) -> None:
        r = SandboxResult(
            exit_code=1,
            stdout="",
            stderr="err",
            timed_out=True,
            duration_ms=123.4,
            metadata={"container_id": "abc"},
        )
        assert r.timed_out is True
        assert r.metadata["container_id"] == "abc"


# ===================================================================
# DockerSandbox tests
# ===================================================================


class TestDockerSandbox:
    async def test_start_success(self) -> None:
        container = _FakeContainer("xyz")
        mock_client = _mock_docker_client(container=container)

        sandbox = DockerSandbox(image="test:latest", workspace=".")
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            await sandbox.start()

        assert sandbox._container is container
        assert sandbox._container_id == "xyz"
        mock_client.containers.run.assert_called_once()

    async def test_start_docker_not_running(self) -> None:
        from docker.errors import DockerException

        with patch(
            "coding_agent.sandbox.docker.docker.from_env",
            side_effect=DockerException("Cannot connect"),
        ):
            sandbox = DockerSandbox()
            with pytest.raises(SandboxError, match="not running"):
                await sandbox.start()

    async def test_start_image_not_found(self) -> None:
        mock_client = _mock_docker_client(image_exists=False)

        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            sandbox = DockerSandbox(image="nonexistent:latest")
            with pytest.raises(SandboxError, match="not found"):
                await sandbox.start()

    async def test_stop_cleans_up(self) -> None:
        container = _FakeContainer()
        mock_client = _mock_docker_client(container=container)

        sandbox = DockerSandbox()
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            await sandbox.start()
            assert sandbox._container is not None

            await sandbox.stop()
            assert sandbox._container is None
            assert sandbox._container_id is None

    async def test_stop_noop_when_not_started(self) -> None:
        sandbox = DockerSandbox()
        await sandbox.stop()  # Should not raise

    async def test_execute_simple_command(self) -> None:
        container = _FakeContainer()
        container._exec_results = [
            _FakeExecResult(0, b"hello world", b""),
        ]
        mock_client = _mock_docker_client(container=container)

        sandbox = DockerSandbox()
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            await sandbox.start()
            result = await sandbox.execute("echo hello world")

        assert result.exit_code == 0
        assert result.stdout == "hello world"
        assert result.stderr == ""
        assert result.timed_out is False
        assert result.duration_ms >= 0

    async def test_execute_nonzero_exit(self) -> None:
        container = _FakeContainer()
        container._exec_results = [
            _FakeExecResult(42, b"", b"something went wrong"),
        ]
        mock_client = _mock_docker_client(container=container)

        sandbox = DockerSandbox()
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            await sandbox.start()
            result = await sandbox.execute("exit 42")

        assert result.exit_code == 42
        assert result.stderr == "something went wrong"

    async def test_execute_empty_command(self) -> None:
        container = _FakeContainer()
        mock_client = _mock_docker_client(container=container)

        sandbox = DockerSandbox()
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            await sandbox.start()
            result = await sandbox.execute("")

        assert result.exit_code == -1
        assert "empty" in result.stderr.lower()

    async def test_execute_not_started_returns_error(self) -> None:
        sandbox = DockerSandbox()
        result = await sandbox.execute("echo hi")
        assert result.exit_code == -1
        assert "not started" in result.stderr.lower()

    async def test_execute_captures_stderr(self) -> None:
        container = _FakeContainer()
        container._exec_results = [
            _FakeExecResult(1, b"out", b"err line 1\nerr line 2"),
        ]
        mock_client = _mock_docker_client(container=container)

        sandbox = DockerSandbox()
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            await sandbox.start()
            result = await sandbox.execute("test")

        assert "err line 1" in result.stderr
        assert "err line 2" in result.stderr

    async def test_execute_passes_workdir(self) -> None:
        container = _FakeContainer()
        container._exec_results = [_FakeExecResult(0, b"ok", b"")]
        mock_client = _mock_docker_client(container=container)

        sandbox = DockerSandbox(workspace="/tmp/test")
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            await sandbox.start()
            result = await sandbox.execute("pwd", cwd="subdir")

        assert result.exit_code == 0
        # Verify workdir was set in metadata
        assert result.metadata["workdir"] == "/workspace/subdir"

    async def test_execute_handles_container_exception(self) -> None:
        container = _FakeContainer()
        container.exec_run = MagicMock(side_effect=Exception("container crashed"))
        mock_client = _mock_docker_client(container=container)

        sandbox = DockerSandbox()
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            await sandbox.start()
            result = await sandbox.execute("echo hi")

        assert result.exit_code == -1
        assert "error" in result.stderr.lower()

    async def test_execute_metadata_includes_container_id(self) -> None:
        container = _FakeContainer("meta123")
        container._exec_results = [_FakeExecResult(0, b"ok", b"")]
        mock_client = _mock_docker_client(container=container)

        sandbox = DockerSandbox()
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            await sandbox.start()
            result = await sandbox.execute("echo ok")

        assert result.metadata["container_id"] == "meta123"

    async def test_is_docker_available_true(self) -> None:
        mock_client = _mock_docker_client(ping_ok=True)
        sandbox = DockerSandbox()
        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            assert await sandbox.is_docker_available() is True

    async def test_is_docker_available_false(self) -> None:
        from docker.errors import DockerException

        with patch(
            "coding_agent.sandbox.docker.docker.from_env",
            side_effect=DockerException("no docker"),
        ):
            sandbox = DockerSandbox()
            assert await sandbox.is_docker_available() is False

    async def test_context_manager(self) -> None:
        container = _FakeContainer()
        mock_client = _mock_docker_client(container=container)

        with patch(
            "coding_agent.sandbox.docker.docker.from_env", return_value=mock_client
        ):
            async with DockerSandbox() as sandbox:
                assert sandbox._container is not None
            # After exit, container should be stopped
            assert sandbox._container is None


# ===================================================================
# SandboxExecutor tests
# ===================================================================


class TestSandboxExecutor:
    async def test_routes_to_sandbox(self) -> None:
        sandbox = AsyncMock()
        sandbox.is_container_running.return_value = True
        sandbox.execute.return_value = SandboxResult(
            exit_code=0, stdout="from sandbox", stderr=""
        )

        executor = SandboxExecutor(sandbox=sandbox)
        result = await executor.execute("echo test")

        assert result.success is True
        assert "from sandbox" in result.output
        assert result.metadata["sandbox"] is True
        sandbox.execute.assert_called_once()

    async def test_returns_error_when_empty_command(self) -> None:
        executor = SandboxExecutor(sandbox=AsyncMock())
        result = await executor.execute("")
        assert result.success is False
        assert "empty" in (result.error or "").lower()

    async def test_falls_back_to_host(self) -> None:
        from coding_agent.sandbox.docker import SandboxError

        sandbox = AsyncMock()
        sandbox.execute.side_effect = SandboxError("broken")

        executor = SandboxExecutor(sandbox=sandbox, fallback_to_host=True)

        with patch(
            "coding_agent.sandbox.executor.asyncio.create_subprocess_shell"
        ) as mock_subprocess:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"host output", b"")
            mock_proc.returncode = 0
            mock_subprocess.return_value = mock_proc

            result = await executor.execute("echo test")

        assert result.success is True
        assert "host output" in result.output
        assert result.metadata["sandbox"] is False

    async def test_no_fallback_returns_error(self) -> None:
        from coding_agent.sandbox.docker import SandboxError

        sandbox = AsyncMock()
        sandbox.execute.side_effect = SandboxError("broken")

        executor = SandboxExecutor(sandbox=sandbox, fallback_to_host=False)
        result = await executor.execute("echo test")

        assert result.success is False
        assert "sandbox unavailable" in (result.error or "").lower()

    async def test_no_sandbox_runs_on_host(self) -> None:
        executor = SandboxExecutor(sandbox=None, fallback_to_host=True)

        with patch(
            "coding_agent.sandbox.executor.asyncio.create_subprocess_shell"
        ) as mock_subprocess:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"direct output", b"")
            mock_proc.returncode = 0
            mock_subprocess.return_value = mock_proc

            result = await executor.execute("echo test")

        assert result.success is True
        assert "direct output" in result.output
        assert result.metadata["sandbox"] is False

    async def test_restarts_dead_container(self) -> None:
        sandbox = AsyncMock()
        sandbox.is_container_running.return_value = False
        sandbox.start = AsyncMock()
        sandbox.execute.return_value = SandboxResult(
            exit_code=0, stdout="restarted", stderr=""
        )

        executor = SandboxExecutor(sandbox=sandbox)
        result = await executor.execute("echo test")

        assert result.success is True
        sandbox.start.assert_called_once()

    async def test_sandbox_timeout_result(self) -> None:
        sandbox = AsyncMock()
        sandbox.is_container_running.return_value = True
        sandbox.execute.return_value = SandboxResult(
            exit_code=-1,
            stdout="partial",
            stderr="",
            timed_out=True,
        )

        executor = SandboxExecutor(sandbox=sandbox)
        result = await executor.execute("sleep 60", timeout=5)

        assert result.success is False
        assert "timed out" in (result.error or "").lower()
        assert result.metadata["timeout"] is True

    async def test_sandbox_stderr_in_error(self) -> None:
        sandbox = AsyncMock()
        sandbox.is_container_running.return_value = True
        sandbox.execute.return_value = SandboxResult(
            exit_code=1,
            stdout="",
            stderr="permission denied",
        )

        executor = SandboxExecutor(sandbox=sandbox)
        result = await executor.execute("rm /etc/passwd")

        assert result.success is False
        assert "permission denied" in (result.error or "")

    async def test_host_timeout(self) -> None:
        executor = SandboxExecutor(sandbox=None, fallback_to_host=True)

        with patch(
            "coding_agent.sandbox.executor.asyncio.create_subprocess_shell"
        ) as mock_subprocess:
            mock_proc = AsyncMock()
            mock_proc.communicate.side_effect = TimeoutError()
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_subprocess.return_value = mock_proc

            result = await executor.execute("sleep 60", timeout=2)

        assert result.success is False
        assert "timed out" in (result.error or "").lower()


# ===================================================================
# Shell tool integration tests
# ===================================================================


class TestShellToolIntegration:
    async def test_shell_tool_uses_executor(self) -> None:
        """Verify the shell tool routes through the executor."""
        mock_executor = AsyncMock()
        mock_executor.execute.return_value = ToolResult(
            success=True,
            output="from executor",
            metadata={"sandbox": True},
        )

        with patch("coding_agent.tools.shell._executor", mock_executor):
            from coding_agent.tools.shell import execute_command

            # execute_command is wrapped by @tool → FunctionTool; call via __wrapped__
            result = await execute_command.__wrapped__("echo test")

        assert result.success is True
        assert "from executor" in result.output


# ===================================================================
# Exec mode / config toggle tests
# ===================================================================


class TestExecModeConfig:
    """Tests for the exec_mode setting and sandbox_enabled migration."""

    def test_exec_mode_default_is_sandbox(self) -> None:
        """Default exec_mode should be 'sandbox'."""
        from coding_agent.config import Settings

        with patch.dict(os.environ, {}, clear=False):
            # Remove both vars to test defaults
            os.environ.pop("CODING_AGENT_EXEC_MODE", None)
            os.environ.pop("CODING_AGENT_SANDBOX_ENABLED", None)
            settings = Settings(_env_file=None)
            assert settings.exec_mode == "sandbox"

    def test_exec_mode_from_env(self) -> None:
        """CODING_AGENT_EXEC_MODE env var should set exec_mode."""
        from coding_agent.config import Settings

        with patch.dict(os.environ, {"CODING_AGENT_EXEC_MODE": "host"}, clear=False):
            settings = Settings(_env_file=None)
            assert settings.exec_mode == "host"

    def test_is_sandbox_mode_true(self) -> None:
        """is_sandbox_mode() returns True when exec_mode is 'sandbox'."""
        from coding_agent.config import Settings

        with patch.dict(os.environ, {"CODING_AGENT_EXEC_MODE": "sandbox"}, clear=False):
            settings = Settings(_env_file=None)
            assert settings.is_sandbox_mode() is True

    def test_is_sandbox_mode_false(self) -> None:
        """is_sandbox_mode() returns False when exec_mode is 'host'."""
        from coding_agent.config import Settings

        with patch.dict(os.environ, {"CODING_AGENT_EXEC_MODE": "host"}, clear=False):
            settings = Settings(_env_file=None)
            assert settings.is_sandbox_mode() is False

    def test_is_sandbox_mode_case_insensitive(self) -> None:
        """is_sandbox_mode() should be case-insensitive."""
        from coding_agent.config import Settings

        with patch.dict(os.environ, {"CODING_AGENT_EXEC_MODE": "SANDBOX"}, clear=False):
            settings = Settings(_env_file=None)
            assert settings.is_sandbox_mode() is True

    def test_legacy_sandbox_enabled_true_migrates(self) -> None:
        """Legacy CODING_AGENT_SANDBOX_ENABLED=true should migrate to exec_mode=sandbox."""
        from coding_agent.config import Settings

        with patch.dict(
            os.environ,
            {"CODING_AGENT_SANDBOX_ENABLED": "true"},
            clear=False,
        ):
            os.environ.pop("CODING_AGENT_EXEC_MODE", None)
            settings = Settings(_env_file=None)
            assert settings.exec_mode == "sandbox"
            assert settings.is_sandbox_mode() is True

    def test_legacy_sandbox_enabled_false_migrates(self) -> None:
        """Legacy CODING_AGENT_SANDBOX_ENABLED=false should migrate to exec_mode=host."""
        from coding_agent.config import Settings

        with patch.dict(
            os.environ,
            {"CODING_AGENT_SANDBOX_ENABLED": "false"},
            clear=False,
        ):
            os.environ.pop("CODING_AGENT_EXEC_MODE", None)
            settings = Settings(_env_file=None)
            assert settings.exec_mode == "host"
            assert settings.is_sandbox_mode() is False

    def test_legacy_sandbox_enabled_1_migrates(self) -> None:
        """Legacy CODING_AGENT_SANDBOX_ENABLED=1 should migrate to sandbox."""
        from coding_agent.config import Settings

        with patch.dict(
            os.environ,
            {"CODING_AGENT_SANDBOX_ENABLED": "1"},
            clear=False,
        ):
            os.environ.pop("CODING_AGENT_EXEC_MODE", None)
            settings = Settings(_env_file=None)
            assert settings.exec_mode == "sandbox"

    def test_exec_mode_takes_precedence_over_legacy(self) -> None:
        """When both are set, exec_mode should take precedence."""
        from coding_agent.config import Settings

        with patch.dict(
            os.environ,
            {
                "CODING_AGENT_EXEC_MODE": "host",
                "CODING_AGENT_SANDBOX_ENABLED": "true",
            },
            clear=False,
        ):
            settings = Settings(_env_file=None)
            assert settings.exec_mode == "host"

    def test_extra_fields_allowed(self) -> None:
        """Extra env vars should not cause validation errors."""
        from coding_agent.config import Settings

        with patch.dict(
            os.environ,
            {"CODING_AGENT_SANDBOX_ENABLED": "true"},
            clear=False,
        ):
            os.environ.pop("CODING_AGENT_EXEC_MODE", None)
            # This used to crash with "Extra inputs are not permitted"
            settings = Settings(_env_file=None)
            assert settings.exec_mode == "sandbox"


# ===================================================================
# Sandbox executor init from config
# ===================================================================


class TestSandboxExecutorFromConfig:
    """Tests for SandboxExecutor lazy initialization via shell tool."""

    async def test_shell_executor_uses_sandbox_mode(self) -> None:
        """Shell tool should create sandbox executor when exec_mode=sandbox."""
        from coding_agent.tools import shell

        # Reset the lazy singleton
        shell._executor = None

        mock_sandbox = AsyncMock()
        mock_sandbox.is_container_running.return_value = True
        mock_sandbox.execute.return_value = SandboxResult(
            exit_code=0, stdout="sandbox output", stderr=""
        )

        with (
            patch("coding_agent.config.Settings") as mock_settings_cls,
            patch(
                "coding_agent.sandbox.docker.DockerSandbox",
                return_value=mock_sandbox,
            ),
            patch("coding_agent.sandbox.executor.SandboxExecutor") as mock_exec_cls,
        ):
            mock_settings = mock_settings_cls.return_value
            mock_settings.is_sandbox_mode.return_value = True
            mock_settings.sandbox_image = "test:latest"
            mock_settings.workspace = Path(".")
            mock_settings.sandbox_memory_limit = "512m"
            mock_settings.sandbox_timeout = 30

            mock_executor = AsyncMock()
            mock_executor.execute.return_value = ToolResult(
                success=True, output="from sandbox"
            )
            mock_exec_cls.return_value = mock_executor

            await shell.execute_command.__wrapped__("echo test")

            # Verify sandbox path was taken
            mock_exec_cls.assert_called_once()
            call_kwargs = mock_exec_cls.call_args
            assert call_kwargs.kwargs["sandbox"] is mock_sandbox
            assert call_kwargs.kwargs["fallback_to_host"] is True

        # Clean up
        shell._executor = None

    async def test_shell_executor_uses_host_mode(self) -> None:
        """Shell tool should create host-only executor when exec_mode=host."""
        from coding_agent.tools import shell

        # Reset the lazy singleton
        shell._executor = None

        with (
            patch("coding_agent.config.Settings") as mock_settings_cls,
            patch("coding_agent.sandbox.executor.SandboxExecutor") as mock_exec_cls,
        ):
            mock_settings = mock_settings_cls.return_value
            mock_settings.is_sandbox_mode.return_value = False

            mock_executor = AsyncMock()
            mock_executor.execute.return_value = ToolResult(
                success=True, output="from host"
            )
            mock_exec_cls.return_value = mock_executor

            await shell.execute_command.__wrapped__("echo test")

            # Verify host path was taken (no sandbox)
            mock_exec_cls.assert_called_once()
            call_kwargs = mock_exec_cls.call_args
            assert call_kwargs.kwargs["sandbox"] is None

        # Clean up
        shell._executor = None


# ===================================================================
# Real integration tests — host execution (no Docker required)
# ===================================================================


class TestRealHostExecution:
    """Integration tests that run real commands on the host machine."""

    async def test_real_echo(self) -> None:
        """Run echo via SandboxExecutor on host — no sandbox."""
        executor = SandboxExecutor(sandbox=None, fallback_to_host=True)
        result = await executor.execute("echo hello from host")

        assert result.success is True
        assert "hello from host" in result.output
        assert result.metadata["sandbox"] is False
        assert result.metadata["exit_code"] == 0

    async def test_real_python(self) -> None:
        """Run a Python one-liner via host."""
        executor = SandboxExecutor(sandbox=None, fallback_to_host=True)
        result = await executor.execute('python -c "print(2 + 2)"')

        assert result.success is True
        assert "4" in result.output
        assert result.metadata["exit_code"] == 0

    async def test_real_nonzero_exit(self) -> None:
        """Non-zero exit code on host."""
        executor = SandboxExecutor(sandbox=None, fallback_to_host=True)
        result = await executor.execute('python -c "import sys; sys.exit(42)"')

        assert result.success is False
        assert result.metadata["exit_code"] == 42

    async def test_real_stderr(self) -> None:
        """Stderr output on host."""
        executor = SandboxExecutor(sandbox=None, fallback_to_host=True)
        result = await executor.execute(
            "python -c \"import sys; print('err', file=sys.stderr)\""
        )

        assert "err" in result.output

    async def test_real_cwd(self) -> None:
        """Verify cwd parameter works on host."""
        import tempfile

        executor = SandboxExecutor(sandbox=None, fallback_to_host=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await executor.execute(
                'python -c "import os; print(os.getcwd())"', cwd=tmpdir
            )

            assert result.success is True
            expected = tmpdir.replace("\\", "/").lower()
            actual = result.output.strip().replace("\\", "/").lower()
            assert expected in actual

    async def test_real_shell_tool_integration(self) -> None:
        """Run a real command through the shell tool (host mode)."""
        from coding_agent.tools import shell

        shell._executor = None

        with patch("coding_agent.config.Settings") as mock_settings_cls:
            mock_settings = mock_settings_cls.return_value
            mock_settings.is_sandbox_mode.return_value = False

            result = await shell.execute_command.__wrapped__("echo shell tool works")

            assert result.success is True
            assert "shell tool works" in result.output

        shell._executor = None


# ===================================================================
# Real integration tests — Docker sandbox execution
# ===================================================================

_docker_image_exists: bool | None = None


def _check_docker_image() -> bool:
    """Check if the sandbox Docker image exists."""
    global _docker_image_exists  # noqa: PLW0603
    if _docker_image_exists is not None:
        return _docker_image_exists
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "coding-agent-sandbox:latest"],
            capture_output=True,
            timeout=10,
        )
        _docker_image_exists = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _docker_image_exists = False
    return _docker_image_exists


class TestRealSandboxExecution:
    """Integration tests that run real commands in a Docker sandbox.

    These tests require:
    1. Docker Desktop running
    2. The sandbox image built:
       docker build -f Dockerfile.sandbox -t coding-agent-sandbox:latest .
    """

    @pytest.fixture(autouse=True)
    def _skip_if_no_image(self) -> None:
        if not _check_docker_image():
            pytest.skip(
                "Sandbox Docker image not built. "
                "Run: docker build -f Dockerfile.sandbox -t coding-agent-sandbox:latest ."
            )

    async def test_real_sandbox_echo(self) -> None:
        """Run echo inside the Docker sandbox."""
        sandbox = DockerSandbox(
            image="coding-agent-sandbox:latest",
            workspace=".",
        )
        try:
            await sandbox.start()
            result = await sandbox.execute("echo hello from sandbox")

            assert result.exit_code == 0
            assert "hello from sandbox" in result.stdout
            assert result.metadata["container_id"]
        finally:
            await sandbox.stop()

    async def test_real_sandbox_python(self) -> None:
        """Run Python inside the Docker sandbox."""
        sandbox = DockerSandbox(
            image="coding-agent-sandbox:latest",
            workspace=".",
        )
        try:
            await sandbox.start()
            result = await sandbox.execute('python3 -c "print(2 + 2)"')

            assert result.exit_code == 0
            assert "4" in result.stdout
        finally:
            await sandbox.stop()

    async def test_real_sandbox_nonzero_exit(self) -> None:
        """Non-zero exit code in sandbox."""
        sandbox = DockerSandbox(
            image="coding-agent-sandbox:latest",
            workspace=".",
        )
        try:
            await sandbox.start()
            result = await sandbox.execute("exit 42")

            assert result.exit_code == 42
        finally:
            await sandbox.stop()

    async def test_real_sandbox_stderr(self) -> None:
        """Stderr output in sandbox."""
        sandbox = DockerSandbox(
            image="coding-agent-sandbox:latest",
            workspace=".",
        )
        try:
            await sandbox.start()
            result = await sandbox.execute(
                "python3 -c \"import sys; print('err', file=sys.stderr)\""
            )

            assert "err" in result.stderr
        finally:
            await sandbox.stop()

    async def test_real_sandbox_executor_integration(self) -> None:
        """Full SandboxExecutor → DockerSandbox → real command."""
        sandbox = DockerSandbox(
            image="coding-agent-sandbox:latest",
            workspace=".",
        )
        try:
            await sandbox.start()
            executor = SandboxExecutor(sandbox=sandbox, fallback_to_host=False)
            result = await executor.execute("echo executor works")

            assert result.success is True
            assert "executor works" in result.output
            assert result.metadata["sandbox"] is True
        finally:
            await sandbox.stop()

    async def test_real_sandbox_cwd(self) -> None:
        """Verify cwd parameter works in sandbox."""
        sandbox = DockerSandbox(
            image="coding-agent-sandbox:latest",
            workspace=".",
        )
        try:
            await sandbox.start()
            result = await sandbox.execute("pwd", cwd="/tmp")

            assert result.exit_code == 0
            assert "/tmp" in result.stdout
        finally:
            await sandbox.stop()
