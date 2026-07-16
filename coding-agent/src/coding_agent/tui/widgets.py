"""Widgets for the Coding Agent REPL."""

from __future__ import annotations

import time

from rich.markup import escape
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

# Nord palette (hex values for Rich Text styles)
_NORD = {
    "primary": "#88C0D0",
    "secondary": "#81A1C1",
    "accent": "#B48EAD",
    "foreground": "#ECEFF4",
    "success": "#A3BE8C",
    "warning": "#EBCB8B",
    "error": "#BF616A",
    "dim": "#7B88A1",
}


class UserMessage(Static):
    """Displays a user message with timestamp."""

    def __init__(self, content: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._content = content
        self._timestamp = time.strftime("%H:%M")

    def render(self) -> Text:
        text = Text()
        text.append(f" {self._timestamp} ", style="dim")
        text.append("\u2502 ", style="dim")
        text.append(self._content, style=f"bold {_NORD['primary']}")
        return text


class AssistantMessage(Static):
    """Displays an assistant message with streaming support."""

    _text: reactive[str] = reactive("")

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)

    def append(self, token: str) -> None:
        """Append a token to the message."""
        self._text += token

    def render(self) -> Text:
        if not self._text:
            return Text("  ...", style="dim")
        return Text(self._text, style=_NORD["foreground"])


class ToolCallBlock(Static):
    """Displays a tool call with name, args, and result."""

    _status: reactive[str] = reactive("running")
    _result: reactive[str] = reactive("")

    def __init__(self, name: str, args: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._name = name
        self._args = args
        self._start_time = time.monotonic()

    def set_result(self, result: str, success: bool = True) -> None:
        """Set the tool result."""
        self._result = result
        self._status = "success" if success else "error"
        self._duration_ms = (time.monotonic() - self._start_time) * 1000
        self.remove_class("-success", "-error")
        self.add_class(f"-{self._status}")

    def render(self) -> Text:
        duration = getattr(self, "_duration_ms", 0)

        if self._status == "running":
            icon = "\u25f7"
            status_style = _NORD["warning"]
            status_text = "running"
        elif self._status == "success":
            icon = "\u2713"
            status_style = _NORD["success"]
            status_text = f"{duration:.0f}ms"
        else:
            icon = "\u2717"
            status_style = _NORD["error"]
            status_text = f"{duration:.0f}ms"

        text = Text()
        text.append(f" {icon} ", style=status_style)
        text.append(self._name, style=f"bold {_NORD['primary']}")

        if self._result:
            result_preview = self._result[:300]
            if len(self._result) > 300:
                result_preview += "..."
            text.append(" \u2192 ", style="dim")
            text.append(escape(result_preview), style="dim")
        elif self._args:
            args_display = self._args[:100]
            if len(self._args) > 100:
                args_display += "..."
            text.append(f" {args_display}", style="dim")

        text.append(f" [{status_text}]", style="dim")

        return text


class SystemMessage(Static):
    """Displays a system message (warnings, recovery events)."""

    def __init__(self, content: str, level: str = "info", **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._content = content
        self._level = level
        self.add_class(f"-{level}")

    def render(self) -> Text:
        if self._level == "error":
            icon = "\u2717"
            style = _NORD["error"]
        elif self._level == "warning":
            icon = "\u26a0"
            style = _NORD["warning"]
        else:
            icon = "\u2139"
            style = "dim"

        text = Text()
        text.append(f" {icon} ", style=style)
        text.append(self._content)
        return text


class ThinkingIndicator(Static):
    """Animated thinking indicator while waiting for response."""

    _dots: reactive[int] = reactive(0)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._start_time = time.monotonic()

    def render(self) -> Text:
        elapsed = time.monotonic() - self._start_time
        dots = "." * (int(elapsed * 2) % 4)
        text = Text()
        text.append(" \u25f7 ", style=_NORD["primary"])
        text.append(f"Thinking{dots}", style="dim")
        return text


class StatusBar(Static):
    """Status bar showing tokens, cost, and iteration info."""

    _tokens: reactive[int] = reactive(0)
    _cost: reactive[float] = reactive(0.0)
    _iteration: reactive[int] = reactive(0)
    _model: reactive[str] = reactive("")
    _context_pct: reactive[float] = reactive(0.0)

    def update_stats(
        self,
        tokens: int = 0,
        cost: float = 0.0,
        iteration: int = 0,
        model: str = "",
        context_pct: float = 0.0,
    ) -> None:
        """Update status bar stats."""
        if tokens:
            self._tokens = tokens
        if cost:
            self._cost = cost
        if iteration:
            self._iteration = iteration
        if model:
            self._model = model
        if context_pct:
            self._context_pct = context_pct

    def render(self) -> Text:
        text = Text()

        if self._model:
            text.append(f" {self._model}", style=f"bold {_NORD['primary']}")
            text.append(" \u2502 ", style="dim")

        if self._tokens > 0:
            if self._tokens >= 1000:
                token_str = f"{self._tokens / 1000:.1f}k"
            else:
                token_str = str(self._tokens)
            text.append(f" {token_str} tokens", style="dim")

        if self._cost > 0:
            text.append(" \u2502 ", style="dim")
            text.append(f" ${self._cost:.4f}", style="dim")

        if self._context_pct > 0:
            text.append(" \u2502 ", style="dim")
            if self._context_pct < 0.7:
                pct_style = _NORD["success"]
            elif self._context_pct < 0.9:
                pct_style = _NORD["warning"]
            else:
                pct_style = _NORD["error"]
            text.append(f" ctx {self._context_pct:.0%}", style=pct_style)

        if self._iteration > 0:
            text.append(" \u2502 ", style="dim")
            text.append(f" iter {self._iteration}", style="dim")

        text.append("  \u2502 Ctrl+D exit", style="dim")

        return text


class Toolbar(Static):
    """Toolbar with undo/redo buttons and checkpoint info."""

    _last_checkpoint: reactive[str] = reactive("")
    _can_undo: reactive[bool] = reactive(False)
    _can_redo: reactive[bool] = reactive(False)

    def set_checkpoint(self, checkpoint_id: str, can_undo: bool = True) -> None:
        """Update checkpoint info."""
        self._last_checkpoint = checkpoint_id
        self._can_undo = can_undo
        self._can_redo = False

    def render(self) -> Text:
        text = Text()

        # Undo button
        if self._can_undo:
            text.append(" [", style="dim")
            text.append("Ctrl+Z Undo", style=f"bold {_NORD['primary']}")
            text.append("]", style="dim")
        else:
            text.append(" [", style="dim")
            text.append("Ctrl+Z Undo", style=f"dim {_NORD['dim']}")
            text.append("]", style="dim")

        text.append(" ", style="dim")

        # Redo button
        if self._can_redo:
            text.append("[", style="dim")
            text.append("Ctrl+Y Redo", style=f"bold {_NORD['primary']}")
            text.append("]", style="dim")
        else:
            text.append("[", style="dim")
            text.append("Ctrl+Y Redo", style=f"dim {_NORD['dim']}")
            text.append("]", style="dim")

        # Checkpoint info
        if self._last_checkpoint:
            text.append("  \u2502 ", style="dim")
            text.append(f"cp: {self._last_checkpoint}", style=f"bold {_NORD['accent']}")

        return text
