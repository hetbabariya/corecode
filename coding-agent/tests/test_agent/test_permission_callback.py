"""Tests for agent.permission_callback module."""

import asyncio

from coding_agent.agent.permission_callback import (
    AutoApproveCallback,
    PromptCallback,
    QueueCallback,
)


class TestAutoApproveCallback:
    """Tests for the auto-approve callback."""

    async def test_always_returns_true(self) -> None:
        cb = AutoApproveCallback()
        result = await cb("read_file", {"path": "test.py"}, "read")
        assert result is True

    async def test_always_returns_true_for_write(self) -> None:
        cb = AutoApproveCallback()
        result = await cb("edit_file", {"path": "test.py"}, "write")
        assert result is True

    async def test_always_returns_true_for_execute(self) -> None:
        cb = AutoApproveCallback()
        result = await cb("execute_command", {"command": "ls"}, "execute")
        assert result is True


class TestQueueCallback:
    """Tests for the queue-based callback."""

    async def test_approve_returns_true(self) -> None:
        cb = QueueCallback()

        async def approve_later():
            await asyncio.sleep(0.01)
            cb.approve()

        task = asyncio.create_task(approve_later())
        result = await cb("edit_file", {"path": "test.py"}, "write")
        await task
        assert result is True

    async def test_deny_returns_false(self) -> None:
        cb = QueueCallback()

        async def deny_later():
            await asyncio.sleep(0.01)
            cb.deny()

        task = asyncio.create_task(deny_later())
        result = await cb("edit_file", {"path": "test.py"}, "write")
        await task
        assert result is False

    async def test_multiple_approvals(self) -> None:
        cb = QueueCallback()
        cb.approve()
        cb.approve()
        cb.deny()

        r1 = await cb("tool1", {}, "write")
        r2 = await cb("tool2", {}, "write")
        r3 = await cb("tool3", {}, "write")

        assert r1 is True
        assert r2 is True
        assert r3 is False


class TestPromptCallback:
    """Tests for the prompt callback (non-interactive)."""

    async def test_pending_queue_starts_empty(self) -> None:
        cb = PromptCallback()
        assert cb._pending.empty()
