"""Status panel showing scratchpad preview and todo counts."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class StatusPanel(Static):
    """Sidebar panel showing scratchpad preview and todo summary.

    Displays:
    - Scratchpad: first few lines or "(empty)"
    - Todo: count by status (pending, in_progress, completed, blocked, cancelled)
    """

    _scratchpad: reactive[str] = reactive("")
    _todos: reactive[list[dict]] = reactive([], recompose=False)
    _visible: reactive[bool] = reactive(True)

    DEFAULT_CSS: ClassVar[str] = """
    StatusPanel {
        margin: 0 1;
        padding: 0 1;
    }
    StatusPanel .section-header {
        text-style: bold;
        color: $text-muted;
    }
    """

    def update_scratchpad(self, content: str) -> None:
        """Update the scratchpad preview."""
        self._scratchpad = content

    def update_todos(self, todos: list[dict]) -> None:
        """Update the todo list."""
        self._todos = todos

    def render(self) -> Text:
        text = Text()

        # --- Scratchpad section ---
        text.append(" Scratchpad", style="bold")
        text.append("\n")

        if self._scratchpad:
            lines = self._scratchpad.split("\n")
            shown = lines[:5]
            for line in shown:
                text.append(f"  {line}\n", style="dim")
            if len(lines) > 5:
                text.append(f"  [...{len(lines) - 5} more lines]\n", style="dim")
        else:
            text.append("  (empty)\n", style="dim")

        # --- Todo section ---
        text.append("\n Todos", style="bold")
        text.append("\n")

        if self._todos:
            status_counts: dict[str, int] = {}
            for t in self._todos:
                s = t.get("status", "pending")
                status_counts[s] = status_counts.get(s, 0) + 1

            for status in ("pending", "in_progress", "completed", "blocked", "cancelled"):
                count = status_counts.get(status, 0)
                if count:
                    text.append(f"  {count} {status}", style=_status_style(status))
                    text.append("\n")
        else:
            text.append("  (none)\n", style="dim")

        return text


def _status_style(status: str) -> str:
    """Return the color for a todo status."""
    return {
        "completed": "bold #A3BE8C",
        "in_progress": "bold #EBCB8B",
        "blocked": "#BF616A",
        "cancelled": "dim",
        "pending": "dim",
    }.get(status, "dim")
