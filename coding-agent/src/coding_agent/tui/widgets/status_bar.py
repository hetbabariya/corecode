"""Status bar widget — single-line bar showing model, cost, tokens, state."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from coding_agent.tui.widgets.spinner import Spinner, SpinnerMode


def _format_cost(cost: float) -> str:
    """Format cost with appropriate precision."""
    if cost < 0.01:
        return f"${cost:.4f}"
    if cost < 1.0:
        return f"${cost:.3f}"
    return f"${cost:.2f}"


def _safe_separator() -> str:
    """Return a separator character, falling back to ASCII if needed."""
    try:
        "·".encode()
        return " · "
    except (UnicodeEncodeError, UnicodeDecodeError):
        return " -> "


class StatusBar(Widget):
    """Top status bar replacing both Header and Sidebar.

    Layout::

        [spinner] model · $cost · tokens · state · permission_mode
    """

    def compose(self) -> ComposeResult:
        sep = _safe_separator()
        yield Spinner(id="status-spinner")
        yield Static(sep, classes="status-sep")
        yield Static("--", id="status-model")
        yield Static(sep, classes="status-sep")
        yield Static("$0.0000", id="status-cost")
        yield Static(sep, classes="status-sep")
        yield Static("0 tokens", id="status-tokens")
        yield Static(sep, classes="status-sep")
        yield Static("idle", id="status-state")
        yield Static(sep, classes="status-sep")
        yield Static("normal", id="status-perm")

    # ── Update helpers ────────────────────────────────────

    def set_model(self, model: str) -> None:
        self.query_one("#status-model", Static).update(model)

    def set_cost(self, cost: float) -> None:
        widget = self.query_one("#status-cost", Static)
        widget.update(_format_cost(cost))
        # Color-code by cost threshold
        for cls in ("status-idle", "status-thinking", "status-error"):
            widget.remove_class(cls)
        if cost >= 5.0:
            widget.add_class("status-error")
        elif cost >= 1.0:
            widget.add_class("status-thinking")
        else:
            widget.add_class("status-idle")

    def set_tokens(self, total: int) -> None:
        self.query_one("#status-tokens", Static).update(f"{total:,} tokens")

    def set_state(self, state: str) -> None:
        widget = self.query_one("#status-state", Static)
        widget.update(state)
        # Colour-code state
        state_classes = {
            "idle": "status-idle",
            "thinking": "status-thinking",
            "error": "status-error",
        }
        for cls in ("status-idle", "status-thinking", "status-error"):
            widget.remove_class(cls)
        if state in state_classes:
            widget.add_class(state_classes[state])

    def set_permission_mode(self, mode: str) -> None:
        self.query_one("#status-perm", Static).update(mode)

    def set_spinner_mode(self, mode: SpinnerMode) -> None:
        """Set the spinner animation mode."""
        self.query_one("#status-spinner", Spinner).set_mode(mode)

    def token_received(self) -> None:
        """Notify the spinner that a token arrived (resets stall timer)."""
        self.query_one("#status-spinner", Spinner).token_received()

    def update_stats(
        self,
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost: float = 0.0,
        tool_count: int = 0,
        state: str = "idle",
    ) -> None:
        """Update all stats at once."""
        if model:
            self.set_model(model)
        self.set_tokens(total_tokens)
        self.set_cost(cost)
        self.set_state(state)
