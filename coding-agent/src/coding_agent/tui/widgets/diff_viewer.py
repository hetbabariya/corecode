"""Collapsible diff viewer widget for displaying file changes."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class DiffViewer(Static):
    """Collapsible widget that displays a unified diff.

    Shows file path header, color-coded added/removed lines,
    and toggles visibility on click (or programmatically).
    """

    _expanded: reactive[bool] = reactive(False)
    _diff: reactive[str] = reactive("")

    DEFAULT_CSS: ClassVar[str] = """
    DiffViewer {
        margin: 0 0 1 0;
        padding: 0 1;
    }
    DiffViewer.-collapsed {
        height: 1;
    }
    DiffViewer > .diff-header {
        color: $text-muted;
    }
    """

    def __init__(self, file_path: str = "", diff: str = "", **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._file_path = file_path
        if diff:
            self._diff = diff
        self.add_class("-collapsed")

    @property
    def diff(self) -> str:
        return self._diff

    @diff.setter
    def diff(self, value: str) -> None:
        self._diff = value

    def toggle(self) -> None:
        """Toggle expanded/collapsed state."""
        self._expanded = not self._expanded
        if self._expanded:
            self.remove_class("-collapsed")
        else:
            self.add_class("-collapsed")

    def expand(self) -> None:
        """Expand to show full diff."""
        self._expanded = True
        self.remove_class("-collapsed")

    def collapse(self) -> None:
        """Collapse to single line."""
        self._expanded = False
        self.add_class("-collapsed")

    def on_click(self) -> None:
        """Toggle on click."""
        self.toggle()

    def render(self) -> Text:
        text = Text()

        # Header line with expand/collapse indicator
        indicator = "\u25bc" if self._expanded else "\u25b6"
        header = f" {indicator} diff --git a/{self._file_path}"
        text.append(header, style="bold")

        if not self.diff:
            text.append(" (no changes)", style="dim")
            return text

        if not self._expanded:
            line_count = self.diff.count("\n")
            text.append(f"  [{line_count} lines]", style="dim")
            return text

        # Expanded: render the diff with color coding
        for line in self.diff.split("\n"):
            if line.startswith("@@"):
                text.append(f"\n  {line}", style="italic")
            elif line.startswith("+"):
                text.append(f"\n  {line}", style="#A3BE8C")  # green
            elif line.startswith("-"):
                text.append(f"\n  {line}", style="#BF616A")  # red
            elif line.startswith("diff --git") or line.startswith("index") or line.startswith("---") or line.startswith("+++"):
                text.append(f"\n  {line}", style="dim")
            else:
                text.append(f"\n  {line}")

        return text
