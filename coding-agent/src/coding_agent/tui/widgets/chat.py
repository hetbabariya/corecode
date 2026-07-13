"""Chat display widget — scrollable message history with role prefixes and markdown."""

from __future__ import annotations

import time
from typing import ClassVar

from rich.markdown import Markdown as RichMarkdown
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from coding_agent.tui.widgets.diff import DiffWidget

# Synchronized blink interval in seconds — all tool dots share this clock.
_BLINK_INTERVAL_S = 0.6

# Maximum number of child widgets kept in the chat.  Safety ceiling —
# sessions rarely exceed 50 children, but this prevents unbounded growth.
_MAX_CHAT_CHILDREN = 500


class ChatMessage(Static):
    """A single chat message widget with a role prefix."""

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        if role == "user":
            display = f"[bold]{content}[/bold]"
            cls = "chat-user"
        else:
            display = content
            cls = "chat-assistant"
        super().__init__(display, markup=True)
        self.add_class(cls)


class ToolCallMessage(Static):
    """A tool call message with synchronized blinking dot while running."""

    _running_refs: ClassVar[list[ToolCallMessage]] = []

    def __init__(
        self, tool_name: str, detail: str = "", *, status: str = "running"
    ) -> None:
        self.tool_name = tool_name
        self.detail = detail
        dot = self._current_dot(status)
        text = f" {dot} {tool_name}" + (f"  {detail}" if detail else "")
        super().__init__(text, markup=False)
        self.add_class("chat-tool-call")
        if status == "running":
            self.add_class("tool-running")
            ToolCallMessage._running_refs.append(self)
        elif status == "success":
            self.add_class("tool-ok")
        elif status == "error":
            self.add_class("tool-err")

    def set_status(self, status: str) -> None:
        """Update the tool status dot and border."""
        for cls in ("tool-running", "tool-ok", "tool-err"):
            self.remove_class(cls)
        if status == "running":
            self.add_class("tool-running")
            if self not in ToolCallMessage._running_refs:
                ToolCallMessage._running_refs.append(self)
        elif status == "success":
            self.add_class("tool-ok")
            self._unregister()
        elif status == "error":
            self.add_class("tool-err")
            self._unregister()
        else:
            self._unregister()
        self._refresh_text()

    def _unregister(self) -> None:
        try:
            ToolCallMessage._running_refs.remove(self)
        except ValueError:
            pass

    def _refresh_text(self) -> None:
        is_running = "tool-running" in self.classes
        dot = self._current_dot("running" if is_running else "done")
        self.update(f" {dot} {self.tool_name}" + (f"  {self.detail}" if self.detail else ""))

    @staticmethod
    def _current_dot(status: str) -> str:
        if status != "running":
            return "●"
        elapsed = time.monotonic()
        phase = int(elapsed / _BLINK_INTERVAL_S) % 2
        return "●" if phase == 0 else "○"

    @classmethod
    def toggle_blink(cls) -> None:
        """Toggle the blink phase and refresh all running tool dots."""
        dead: list[ToolCallMessage] = []
        for ref in cls._running_refs:
            try:
                ref._refresh_text()
            except Exception:
                dead.append(ref)
        for d in dead:
            try:
                cls._running_refs.remove(d)
            except ValueError:
                pass


class ToolResultMessage(Static):
    """A tool result with success/error border."""

    def __init__(self, tool_name: str, detail: str = "", *, ok: bool = True) -> None:
        text = f"   {tool_name}" + (f"  {detail}" if detail else "")
        super().__init__(text, markup=False)
        self.add_class("chat-tool-result")
        self.add_class("tool-ok" if ok else "tool-err")


class ToolGroupMessage(Static):
    """Multiple tool calls of the same type grouped together."""

    def __init__(self, tool_name: str, count: int) -> None:
        text = f" ○ {tool_name} × {count}"
        super().__init__(text, markup=False)
        self.add_class("chat-tool-call")
        self.add_class("tool-group")


class TypingIndicator(Static):
    """Animated typing indicator shown while the agent is processing."""

    _frames = ["◇ thinking…", "◈ thinking…", "◆ thinking…"]
    _frame_index = 0

    def __init__(self) -> None:
        super().__init__(self._frames[0], markup=False)
        self.add_class("chat-typing")
        self.set_interval(0.5, self._advance_frame)

    def _advance_frame(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(self._frames)
        self.update(self._frames[self._frame_index])


class WelcomeCard(Static):
    """Welcome card shown on startup with model info and keyboard hints."""

    def __init__(self, model: str) -> None:
        lines = [
            f"[bold]Welcome[/bold] — [bold]{model}[/bold]",
            "",
            "Type a message below to get started.",
            "",
            "Shortcuts:  Enter send  ·  Shift+Enter newline  ·  ↑↓ history",
            "            Escape cancel  ·  Tab amend  ·  /help commands",
        ]
        super().__init__("\n".join(lines), markup=True)
        self.add_class("chat-welcome")


class TaskCompleteBanner(Static):
    """Styled task completion banner with cost and token info."""

    def __init__(self, cost: float = 0.0, tokens: int = 0, tools: int = 0) -> None:
        parts = ["✓ Done"]
        if cost > 0:
            parts.append(f"${cost:.4f}")
        if tokens > 0:
            parts.append(f"{tokens:,} tokens")
        if tools > 0:
            parts.append(f"{tools} tool{'s' if tools != 1 else ''}")
        text = " · ".join(parts)
        super().__init__(text, markup=False)
        self.add_class("chat-task-done")


class CancelledBanner(Static):
    """Cancelled operation banner."""

    def __init__(self) -> None:
        super().__init__("✗ Cancelled", markup=False)
        self.add_class("chat-task-cancelled")


class MaxIterBanner(Static):
    """Max iterations reached banner."""

    def __init__(self) -> None:
        super().__init__("! Max iterations reached", markup=False)
        self.add_class("chat-task-maxiter")


class ErrorMessage(Static):
    """An error message widget."""

    def __init__(self, error: str) -> None:
        super().__init__(f"✗ Error: {error}")
        self.error_text = error
        self.add_class("chat-error")


class ChatDisplay(VerticalScroll):
    """Scrollable chat display area with role prefixes and visual structure.

    Virtual scrolling: Textual's VerticalScroll already only renders
    visible children.  We additionally cap total children at
    ``_MAX_CHAT_CHILDREN`` and prune the oldest when exceeded.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._typing_indicator: TypingIndicator | None = None
        self._ready: bool = False
        self._pending_messages: list[str] = []

    def compose(self) -> ComposeResult:
        yield from ()

    # ── Pruning ───────────────────────────────────────────

    def _prune_if_needed(self) -> None:
        """Remove oldest children when exceeding the message cap."""
        children = list(self.children)
        if len(children) > _MAX_CHAT_CHILDREN:
            excess = len(children) - _MAX_CHAT_CHILDREN
            for child in children[:excess]:
                child.remove()
            marker = Static("— Earlier messages trimmed —")
            marker.add_class("chat-status")
            self.mount(marker)

    # ── Welcome ───────────────────────────────────────────

    def add_welcome(self, model: str) -> None:
        """Show the welcome card."""
        card = WelcomeCard(model)
        self.mount(card)
        self.scroll_end(animate=False)
        self._ready = True
        for msg in self._pending_messages:
            self.add_user_message(msg)
        self._pending_messages.clear()

    # ── Typing indicator ──────────────────────────────────

    def show_typing(self) -> None:
        """Show the typing indicator."""
        if self._typing_indicator is None:
            self._typing_indicator = TypingIndicator()
            self.mount(self._typing_indicator)
            self.scroll_end(animate=False)

    def hide_typing(self) -> None:
        """Hide the typing indicator."""
        if self._typing_indicator is not None:
            try:
                self._typing_indicator.remove()
            except Exception:
                pass
            self._typing_indicator = None

    # ── Messages ──────────────────────────────────────────

    def add_user_message(self, content: str) -> None:
        """Add a user message to the chat."""
        if not self._ready:
            self._pending_messages.append(content)
            return
        self.hide_typing()
        msg = ChatMessage(role="user", content=content)
        self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_if_needed()

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message with markdown rendering."""
        self.hide_typing()
        try:
            rendered = RichMarkdown(content)
            widget = Static(rendered)
            widget.add_class("chat-assistant")
            self.mount(widget)
        except Exception:
            msg = ChatMessage(role="assistant", content=content)
            self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_if_needed()

    def add_assistant_text(self, text: str) -> None:
        """Add streaming assistant text (plain, will be replaced)."""
        self.hide_typing()
        msg = ChatMessage(role="assistant", content=text)
        self.mount(msg)
        self.scroll_end(animate=False)

    def update_last_assistant(self, content: str) -> None:
        """Update the last assistant message with stable-prefix memoization."""
        assistants = list(self.query(".chat-assistant"))
        if assistants:
            widget = assistants[-1]
            widget.remove()
            try:
                rendered = RichMarkdown(content)
                new_widget = Static(rendered)
                new_widget.add_class("chat-assistant")
                self.mount(new_widget)
            except Exception:
                msg = ChatMessage(role="assistant", content=content)
                self.mount(msg)
        self.scroll_end(animate=False)

    def add_tool_start(
        self, tool_name: str, args: dict[str, object] | None = None
    ) -> ToolCallMessage:
        """Add a tool execution start message."""
        self.hide_typing()
        detail = ""
        if args:
            args_str = str(args)
            if len(args_str) > 80:
                args_str = args_str[:77] + "..."
            detail = args_str
        msg = ToolCallMessage(tool_name=tool_name, detail=detail, status="running")
        self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_if_needed()
        return msg

    def update_tool_status(self, msg: ToolCallMessage, status: str) -> None:
        """Update a tool call message's status dot."""
        msg.set_status(status)
        self.scroll_end(animate=False)

    def add_tool_result(self, tool_name: str, result: str) -> None:
        """Add a tool result message."""
        preview = result[:200] if result else ""
        if len(result) > 200:
            preview += "..."
        ok = not any(
            marker in result.lower()
            for marker in ("error:", "traceback", "exception", "failed")
        )
        msg = ToolResultMessage(tool_name=tool_name, detail=preview, ok=ok)
        self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_if_needed()

    def add_tool_group(self, tool_name: str, count: int) -> None:
        """Add a grouped tool call message."""
        msg = ToolGroupMessage(tool_name=tool_name, count=count)
        self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_if_needed()

    def add_diff(
        self,
        old_text: str,
        new_text: str,
        filename: str = "",
    ) -> None:
        """Add a diff widget showing changes between old and new text."""
        widget = DiffWidget.from_strings(old_text, new_text, filename=filename)
        self.mount(widget)
        self.scroll_end(animate=False)
        self._prune_if_needed()

    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.hide_typing()
        msg = ErrorMessage(error=error)
        self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_if_needed()

    def add_status(self, text: str) -> None:
        """Add a status message (info, not from user/assistant)."""
        msg = Static(text)
        msg.add_class("chat-status")
        self.mount(msg)
        self.scroll_end(animate=False)
        self._prune_if_needed()

    def add_task_complete(self, cost: float = 0.0, tokens: int = 0, tools: int = 0) -> None:
        """Add a styled task completion banner."""
        self.hide_typing()
        banner = TaskCompleteBanner(cost=cost, tokens=tokens, tools=tools)
        self.mount(banner)
        self.scroll_end(animate=False)

    def add_task_cancelled(self) -> None:
        """Add a styled cancellation banner."""
        self.hide_typing()
        banner = CancelledBanner()
        self.mount(banner)
        self.scroll_end(animate=False)

    def add_task_max_iterations(self) -> None:
        """Add a styled max-iterations banner."""
        self.hide_typing()
        banner = MaxIterBanner()
        self.mount(banner)
        self.scroll_end(animate=False)

    def clear_chat(self) -> None:
        """Clear all messages from the chat."""
        self.hide_typing()
        self.remove_children()

    def get_last_assistant_text(self) -> str:
        """Return the plain text of the last assistant message."""
        assistants = list(self.query(".chat-assistant"))
        if assistants:
            try:
                return assistants[-1].renderable.plain
            except AttributeError:
                return str(assistants[-1].renderable)
        return ""
