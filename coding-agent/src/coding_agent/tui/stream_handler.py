"""Stream handler — bridges AgentEvent stream to TUI widget updates."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.loop import AgentLoop
from coding_agent.logging import logger

if TYPE_CHECKING:
    from coding_agent.tui.app import CodingAgentApp


class StreamHandler:
    """Consumes AgentEvent stream and updates TUI widgets.

    Usage::

        handler = StreamHandler(app, agent_loop)
        await handler.run("Fix the bug in main.py")
    """

    def __init__(self, app: CodingAgentApp, agent_loop: AgentLoop) -> None:
        self.app = app
        self.agent_loop = agent_loop
        self._running = False
        self._current_task: asyncio.Task[None] | None = None
        self._current_text = ""

    async def run(self, prompt: str) -> None:
        """Run the agent loop and update the UI with events."""
        if self._running:
            logger.warning("stream_handler_already_running")
            return

        self._running = True
        self._current_text = ""
        self.app.set_state("thinking")

        try:
            async for event in self.agent_loop.process_input(prompt):
                await self._handle_event(event)
        except Exception as e:
            logger.error("stream_handler_error", error=str(e))
            self.app.chat_display.add_error(str(e))
            self.app.user_input.disabled = False
            self.app.user_input.set_focus()
        finally:
            self._running = False
            self.app.set_state("idle")
            self._update_stats()

    async def _handle_event(self, event: AgentEvent) -> None:
        """Handle a single AgentEvent."""
        if event.type == EventType.TEXT:
            self._handle_text(event)
        elif event.type == EventType.TOOL_START:
            self._handle_tool_start(event)
        elif event.type == EventType.TOOL_RESULT:
            self._handle_tool_result(event)
        elif event.type == EventType.PERMISSION_REQUEST:
            await self._handle_permission(event)
        elif event.type == EventType.USAGE:
            self._handle_usage(event)
        elif event.type == EventType.DONE:
            self._handle_done()
        elif event.type == EventType.ERROR:
            self._handle_error(event)
        elif event.type == EventType.MAX_ITERATIONS:
            self._handle_max_iterations()

    def _handle_text(self, event: AgentEvent) -> None:
        """Handle streaming text from LLM."""
        text = str(event.data) if event.data else ""
        if not text:
            return

        # Accumulate text for the current assistant message
        if not self._current_text:
            self.app.chat_display.add_assistant_text("")

        self._current_text += text

        # Update the last assistant message
        self.app.chat_display.update_last_assistant(self._current_text)

    def _handle_tool_start(self, event: AgentEvent) -> None:
        """Handle tool execution start."""
        # Reset text accumulator
        self._current_text = ""

        data = _extract_dict(event.data)
        tool_name = _get_str(data, "name", "unknown")
        args = _get_dict(data, "args")

        self.app.chat_display.add_tool_start(tool_name, args)
        self.app.sidebar.set_state(f"running: {tool_name}")
        self.app.tool_count += 1

    def _handle_tool_result(self, event: AgentEvent) -> None:
        """Handle tool execution result."""
        data = _extract_dict(event.data)
        tool_name = _get_str(data, "name", "unknown")
        result = _get_str(data, "result", "")

        self.app.chat_display.add_tool_result(tool_name, result)
        self.app.sidebar.set_state("thinking")

    async def _handle_permission(self, event: AgentEvent) -> None:
        """Handle permission request — show dialog and wait for response."""
        data = _extract_dict(event.data)
        tool_name = _get_str(data, "tool_name", "unknown")
        args = _get_dict(data, "args")
        perm_level = _get_str(data, "permission_level", "write")

        # Show permission dialog
        self.app.permission_dialog.show(tool_name, args, perm_level)
        self.app.sidebar.set_state("waiting for permission")

        # Wait for user response (the dialog posts PermissionDialog.Response)
        response = await self.app.wait_for_permission()
        self.app.permission_dialog.hide()

        # Feed response back to agent loop via queue callback
        if self.agent_loop.permission_callback is not None:
            if hasattr(self.agent_loop.permission_callback, "approve"):
                if response.denied:
                    self.agent_loop.permission_callback.deny()  # type: ignore[union-attr]
                elif response.approved:
                    self.agent_loop.permission_callback.approve()  # type: ignore[union-attr]
                else:
                    self.agent_loop.permission_callback.approve()  # type: ignore[union-attr]

        self.app.sidebar.set_state("thinking")

    def _handle_usage(self, event: AgentEvent) -> None:
        """Handle token usage update."""
        data = _extract_dict(event.data)
        if data:
            self.app.prompt_tokens = _get_int(data, "prompt_tokens")
            self.app.completion_tokens = _get_int(data, "completion_tokens")
            self.app.total_tokens = _get_int(data, "total_tokens")
            self._update_stats()

    def _handle_done(self) -> None:
        """Handle task completion."""
        self._current_text = ""
        self.app.chat_display.add_status("--- Task complete ---")
        self.app.user_input.disabled = False
        self.app.user_input.set_focus()

    def _handle_error(self, event: AgentEvent) -> None:
        """Handle error event."""
        error = str(event.data) if event.data else "Unknown error"
        self.app.chat_display.add_error(error)
        self._current_text = ""
        self.app.user_input.disabled = False
        self.app.user_input.set_focus()

    def _handle_max_iterations(self) -> None:
        """Handle max iterations reached."""
        self._current_text = ""
        self.app.chat_display.add_status("--- Max iterations reached ---")
        self.app.user_input.disabled = False
        self.app.user_input.set_focus()
        self._current_text = ""

    def _update_stats(self) -> None:
        """Update sidebar with current stats."""
        self.app.sidebar.update_stats(
            prompt_tokens=self.app.prompt_tokens,
            completion_tokens=self.app.completion_tokens,
            total_tokens=self.app.total_tokens,
            cost=self.app.llm_client.total_usage.estimated_cost,
            tool_count=self.app.tool_count,
        )


def _extract_dict(data: Any) -> dict[str, Any]:
    """Safely extract a dict from event data."""
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for key, value in data.items():  # type: ignore[reportUnknownVariableType]
            result[str(key)] = value  # type: ignore[reportUnknownArgumentType]
        return result
    return {}


def _get_str(data: dict[str, Any], key: str, default: str = "") -> str:
    """Safely get a string value from a dict."""
    return str(data.get(key, default))


def _get_int(data: dict[str, Any], key: str) -> int:
    """Safely get an int value from a dict."""
    return int(data.get(key, 0))


def _get_dict(data: dict[str, Any], key: str) -> dict[str, object]:
    """Safely get a dict value from a dict."""
    value = data.get(key)
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for k, v in value.items():  # type: ignore[reportUnknownVariableType]
            result[str(k)] = v  # type: ignore[reportUnknownArgumentType]
        return result
    return {}
