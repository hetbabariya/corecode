"""Tests for shell execution tool."""

from __future__ import annotations

import sys

from coding_agent.tools.registry import tool_registry


class TestExecuteCommand:
    async def test_basic_command(self) -> None:
        result = await tool_registry.execute(
            "execute_command", {"command": "echo hello"}
        )
        assert result.success is True
        assert "hello" in result.output

    async def test_exit_code_zero(self) -> None:
        result = await tool_registry.execute("execute_command", {"command": "echo ok"})
        assert result.success is True
        assert result.metadata["exit_code"] == 0

    async def test_nonzero_exit_code(self) -> None:
        result = await tool_registry.execute("execute_command", {"command": "exit 42"})
        assert result.success is False
        assert result.metadata["exit_code"] == 42

    async def test_stderr_output(self) -> None:
        result = await tool_registry.execute(
            "execute_command",
            {
                "command": "python -c \"import sys; sys.stderr.write('err_msg'); sys.exit(1)"
            },
        )
        assert result.success is False
        assert "err_msg" in result.output

    async def test_timeout(self) -> None:
        result = await tool_registry.execute(
            "execute_command",
            {"command": 'python -c "import time; time.sleep(60)"', "timeout": 2},
        )
        assert result.success is False
        assert "timed out" in (result.error or "").lower()

    async def test_empty_command(self) -> None:
        result = await tool_registry.execute("execute_command", {"command": ""})
        assert result.success is False
        assert "empty" in (result.error or "").lower()

    async def test_whitespace_command(self) -> None:
        result = await tool_registry.execute("execute_command", {"command": "   "})
        assert result.success is False

    async def test_cwd_parameter(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        result = await tool_registry.execute(
            "execute_command",
            {"command": "pwd" if sys.platform != "win32" else "cd", "cwd": str(p)},
        )
        assert result.success is True

    async def test_multiline_output(self) -> None:
        result = await tool_registry.execute(
            "execute_command",
            {"command": "echo line1 && echo line2 && echo line3"},
        )
        assert result.success is True
        assert "line1" in result.output
        assert "line2" in result.output
        assert "line3" in result.output

    async def test_metadata_stdout_len(self) -> None:
        result = await tool_registry.execute(
            "execute_command", {"command": "echo test123"}
        )
        assert result.metadata["stdout_len"] > 0

    async def test_windows_command(self) -> None:
        if sys.platform != "win32":
            return  # type: ignore[misc]
        result = await tool_registry.execute("execute_command", {"command": "dir"})
        assert result.success is True
