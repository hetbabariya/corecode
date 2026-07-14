"""Help bar widget ΓÇö single-line bar showing available keyboard shortcuts."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

# Context-sensitive hint sets
_HINTS: dict[str, str] = {
    "normal": " Enter send ┬╖ Shift+Enter newline ┬╖ ΓåæΓåô history ┬╖ /help commands",
    "permission": " Enter confirm ┬╖ Tab cycle ┬╖ Escape deny",
    "disabled": " ...waiting...",
}


class HelpBar(Widget):
    """Bottom help bar showing available keyboard shortcuts.

    Layout::

        Enter send ┬╖ Shift+Enter newline ┬╖ ΓåæΓåô history ┬╖ /help commands
    """

    DEFAULT_CSS = """
    HelpBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
    }

    HelpBar Static {
        background: transparent;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._context = "normal"

    def compose(self) -> ComposeResult:
        yield Static(
            _HINTS["normal"],
            id="help-text",
        )

    def update_hints(self, context: str = "normal") -> None:
        """Update displayed hints based on app state."""
        if context == self._context:
            return
        self._context = context
        try:
            self.query_one("#help-text", Static).update(
                _HINTS.get(context, _HINTS["normal"])
            )
        except Exception:
            pass
