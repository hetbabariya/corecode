"""Chat display widget — scrollable message history with markdown rendering."""

from __future__ import annotations

from rich.markdown import Markdown as RichMarkdown
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class ChatMessage(Static):
    """A single chat message widget."""

    def __init__(self, role: str, content: str) -> None:
        super().__init__(content)
        self.role = role
        self.add_class(f"chat-{role}")


class ToolCallMessage(Static):
    """A tool call/status message widget."""

    def __init__(self, tool_name: str, detail: str = "") -> None:
        text = f"  [{tool_name}] {detail}" if detail else f"  [{tool_name}]"
        super().__init__(text, markup=False)
        self.tool_name = tool_name
        self.detail = detail
        self.add_class("tool-call-message")


class ErrorMessage(Static):
    """An error message widget."""

    def __init__(self, error: str) -> None:
        super().__init__(f"Error: {error}")
        self.error_text = error
        self.add_class("chat-error")


class ChatDisplay(VerticalScroll):
    """Scrollable chat display area.

    Manages a list of messages and auto-scrolls to the bottom.
    """

    def compose(self) -> ComposeResult:
        yield from ()

    def add_user_message(self, content: str) -> None:
        """Add a user message to the chat."""
        msg = ChatMessage(role="user", content=content)
        self.mount(msg)
        self.scroll_end(animate=False)

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message with markdown rendering."""
        try:
            rendered = RichMarkdown(content)
            widget = Static(rendered)
            widget.add_class("chat-assistant")
            self.mount(widget)
        except Exception:
            msg = ChatMessage(role="assistant", content=content)
            self.mount(msg)
        self.scroll_end(animate=False)

    def add_assistant_text(self, text: str) -> None:
        """Add streaming assistant text (plain, will be replaced)."""
        msg = ChatMessage(role="assistant", content=text)
        self.mount(msg)
        self.scroll_end(animate=False)

    def update_last_assistant(self, content: str) -> None:
        """Update the last assistant message (for streaming)."""
        assistants = list(self.query(".chat-assistant"))
        if assistants:
            widget = assistants[-1]
            try:
                rendered = RichMarkdown(content)
                widget.update(rendered)
            except Exception:
                widget.update(content)
            widget.refresh(layout=False)
        self.scroll_end(animate=False)

    def add_tool_start(
        self, tool_name: str, args: dict[str, object] | None = None
    ) -> None:
        """Add a tool execution start message."""
        detail = ""
        if args:
            args_str = str(args)
            if len(args_str) > 80:
                args_str = args_str[:77] + "..."
            detail = args_str
        msg = ToolCallMessage(tool_name=tool_name, detail=detail)
        msg.add_class("tool-call-message")
        self.mount(msg)
        self.scroll_end(animate=False)

    def add_tool_result(self, tool_name: str, result: str | None = None) -> None:
        """Add a tool result message."""
        if result is None:
            preview = "(no result)"
        else:
            preview = str(result)[:200]
            if len(str(result)) > 200:
                preview += "..."
        msg = ToolCallMessage(tool_name=f"{tool_name} result", detail=preview)
        self.mount(msg)
        self.scroll_end(animate=False)

    def add_error(self, error: str) -> None:
        """Add an error message."""
        msg = ErrorMessage(error=error)
        self.mount(msg)
        self.scroll_end(animate=False)

    def add_status(self, text: str) -> None:
        """Add a status message (info, not from user/assistant)."""
        msg = Static(text)
        msg.add_class("tool-call-message")
        self.mount(msg)
        self.scroll_end(animate=False)

    def add_welcome(self, model_name: str) -> None:
        """Add a welcome card with model info."""
        welcome = Static(
            f"Welcome! Using {model_name}\n"
            "Type your message and press Enter to submit.\n"
            "Shift+Enter for newline. /help for commands."
        )
        welcome.add_class("welcome-card")
        self.mount(welcome)
        self.scroll_end(animate=False)

    def add_task_complete(self) -> None:
        """Add a task complete banner."""
        msg = Static("Task complete.")
        msg.add_class("task-complete")
        self.mount(msg)
        self.scroll_end(animate=False)

    def add_task_cancelled(self) -> None:
        """Add a task cancelled banner."""
        msg = Static("Task cancelled.")
        msg.add_class("task-cancelled")
        self.mount(msg)
        self.scroll_end(animate=False)

    def clear_chat(self) -> None:
        """Clear all messages from the chat."""
        self.remove_children()
