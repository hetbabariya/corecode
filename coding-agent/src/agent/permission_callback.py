"""Permission callback system for the agent loop.

Provides a callable that the agent loop invokes when a tool needs
user confirmation.  Three built-in strategies:

* **AutoApproveCallback** — always returns True (testing / non-interactive).
* **QueueCallback** — suspends until an external caller puts True/False on
  an ``asyncio.Queue`` (used by TUI / REPL).
* **PromptCallback** — asks the user via ``input()`` in a terminal.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class PermissionCallback(Protocol):
    """Signature for permission callbacks."""

    async def __call__(
        self, tool_name: str, args: dict[str, Any], permission_level: str
    ) -> bool: ...


class AutoApproveCallback:
    """Always approves — for testing and non-interactive modes."""

    async def __call__(
        self, tool_name: str, args: dict[str, Any], permission_level: str
    ) -> bool:
        return True


class QueueCallback:
    """Suspended approval via an ``asyncio.Queue[bool]``.

    The consumer (e.g. TUI) calls :meth:`approve` or :meth:`deny` after
    displaying the permission request to the user.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bool] = asyncio.Queue()

    async def __call__(
        self, tool_name: str, args: dict[str, Any], permission_level: str
    ) -> bool:
        return await self._queue.get()

    def approve(self) -> None:
        """Approve the pending permission request."""
        self._queue.put_nowait(True)

    def deny(self) -> None:
        """Deny the pending permission request."""
        self._queue.put_nowait(False)


class PromptCallback:
    """Asks the user via terminal ``input()``."""

    def __init__(self) -> None:
        self._pending: asyncio.Queue[bool] = asyncio.Queue()

    async def __call__(
        self, tool_name: str, args: dict[str, Any], permission_level: str
    ) -> bool:
        return await self._pending.get()

    def prompt_user(
        self, tool_name: str, args: dict[str, Any], permission_level: str
    ) -> bool:
        """Synchronous helper that asks via stdin (call from a thread)."""
        print(f"\n  Permission required: {permission_level}")
        print(f"  Tool: {tool_name}")
        print(f"  Args: {args}")
        answer = input("  Allow? [y/N] ").strip().lower()
        return answer in ("y", "yes")
