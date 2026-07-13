"""Stream handler — bridges AgentEvent stream to TUI widget updates."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.loop import AgentLoop
from coding_agent.logging import logger

if TYPE_CHECKING:
    from coding_agent.tui.app import CodingAgentApp
    from coding_agent.tui.widgets.chat import ToolCallMessage

# Tools whose results should be rendered as diffs
_DIFF_TOOLS = {"edit_file", "write_file"}


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
        self._cancel_requested = False
        self._current_task: asyncio.Task[None] | None = None
        self._current_text = ""
        # Tool grouping: tool_name -> count
        self._tool_counts: dict[str, int] = defaultdict(int)
        # Track running tool messages for status updates
        self._running_tools: dict[str, ToolCallMessage] = {}

    @property
    def running(self) -> bool:
        """Whether the stream handler is currently processing."""
        return self._running

    def cancel(self) -> None:
        """Request cancellation of the current stream."""
        self._cancel_requested = True
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

    async def run(self, prompt: str) -> None:
        """Run the agent loop and update the UI with events."""
        if self._running:
            logger.warning("stream_handler_already_running")
            return

        self._running = True
        self._cancel_requested = False
        self._current_text = ""
        self._tool_counts.clear()
        self._running_tools.clear()
        self._current_task = asyncio.current_task()
        self.app.set_state("thinking")
        self.app.chat_display.show_typing()

        try:
            async for event in self.agent_loop.process_input(prompt):
                if self._cancel_requested:
                    break
                await self._handle_event(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("stream_handler_error", error=str(e))
            self.app.chat_display.add_error(str(e))
        finally:
            self._running = False
            self._current_task = None
            self.app.user_input.disabled = False
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

        # Reset the spinner's stall timer
        self.app.status_bar.token_received()

        if not self._current_text:
            self.app.chat_display.add_assistant_text("")

        self._current_text += text
        self.app.chat_display.update_last_assistant(self._current_text)

    def _handle_tool_start(self, event: AgentEvent) -> None:
        """Handle tool execution start."""
        self._current_text = ""
        self.app.status_bar.token_received()

        data = _extract_dict(event.data)
        tool_name = _get_str(data, "name", "unknown")
        args = _get_dict(data, "args")
        call_id = _get_str(data, "id", "")
        self._tool_counts[tool_name] += 1
        if not call_id:
            call_id = f"{tool_name}_{self._tool_counts[tool_name]}"

        msg = self.app.chat_display.add_tool_start(tool_name, args)
        self._running_tools[call_id] = msg
        self.app.set_state(f"running: {tool_name}")
        self.app.tool_count += 1

    def _handle_tool_result(self, event: AgentEvent) -> None:
        """Handle tool execution result."""
        data = _extract_dict(event.data)
        tool_name = _get_str(data, "name", "unknown")
        result = _get_str(data, "result", "")
        call_id = _get_str(data, "id", "")

        # Update running tool dot to success/error
        msg = self._running_tools.pop(call_id, None) if call_id else None
        if msg is None:
            # Fallback: find any running tool with this name
            for cid, _m in list(self._running_tools.items()):
                if cid.startswith(tool_name):
                    msg = self._running_tools.pop(cid)
                    break
        if msg is not None:
            ok = not any(
                marker in result.lower()
                for marker in ("error:", "traceback", "exception", "failed")
            )
            status = "success" if ok else "error"
            self.app.chat_display.update_tool_status(msg, status)

        # Render as diff for edit_file/write_file tools — skip for large results
        if tool_name in _DIFF_TOOLS and result and len(result) < 10_000:
            self._render_tool_diff(tool_name, data, result)
        else:
            preview = result[:500] if result else ""
            if len(result) > 500:
                preview += "..."
            self.app.chat_display.add_tool_result(tool_name, preview)

        self.app.set_state("thinking")

    def _render_tool_diff(
        self, tool_name: str, data: dict[str, Any], result: str
    ) -> None:
        """Render edit_file/write_file results as a diff widget."""
        filename = _get_str(data, "file_path", "")
        if not filename:
            filename = _get_str(data, "path", "")

        # Try to extract old/new content from args or result
        old_content = _get_str(data, "old_content", "")
        new_content = _get_str(data, "new_content", "")
        content = _get_str(data, "content", "")

        if old_content and new_content:
            self.app.chat_display.add_diff(old_content, new_content, filename)
        elif content and old_content:
            self.app.chat_display.add_diff(old_content, content, filename)
        else:
            # Fall back to result preview
            preview = result[:500] if result else ""
            if len(result) > 500:
                preview += "..."
            self.app.chat_display.add_tool_result(tool_name, preview)

    async def _handle_permission(self, event: AgentEvent) -> None:
        """Handle permission request — show dialog and wait for response."""
        data = _extract_dict(event.data)
        tool_name = _get_str(data, "tool_name", "unknown")
        args = _get_dict(data, "args")
        perm_level = _get_str(data, "permission_level", "write")

        self.app.permission_dialog.show(tool_name, args, perm_level)
        self.app.set_state("waiting for permission")
        self.app.query_one("#help-bar").update_hints("permission")

        response = await self.app.wait_for_permission()
        self.app.permission_dialog.hide()
        self.app.user_input.set_focus()
        self.app.query_one("#help-bar").update_hints("normal")

        if self.agent_loop.permission_callback is not None:
            if hasattr(self.agent_loop.permission_callback, "approve"):
                if response.denied:
                    self.agent_loop.permission_callback.deny()  # type: ignore[union-attr]
                elif response.approved:
                    self.agent_loop.permission_callback.approve()  # type: ignore[union-attr]
                else:
                    self.agent_loop.permission_callback.approve()  # type: ignore[union-attr]

        self.app.set_state("thinking")

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
        self._flush_tool_groups()
        self.app.chat_display.add_task_complete(
            cost=self.app.llm_client.total_usage.estimated_cost,
            tokens=self.app.total_tokens,
            tools=self.app.tool_count,
        )

    def _handle_error(self, event: AgentEvent) -> None:
        """Handle error event."""
        error = str(event.data) if event.data else "Unknown error"
        self.app.chat_display.add_error(error)
        self._current_text = ""

    def _handle_max_iterations(self) -> None:
        """Handle max iterations reached."""
        self._current_text = ""
        self.app.chat_display.add_task_max_iterations()

    def _flush_tool_groups(self) -> None:
        """Flush accumulated tool counts as grouped messages."""
        for tool_name, count in self._tool_counts.items():
            if count > 1:
                self.app.chat_display.add_tool_group(tool_name, count)
        self._tool_counts.clear()

    def _update_stats(self) -> None:
        """Update status bar with current stats."""
        self.app.status_bar.update_stats(
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
