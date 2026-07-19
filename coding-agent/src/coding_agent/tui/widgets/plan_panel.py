"""Plan panel widget showing current plan steps and status."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class PlanPanel(Static):
    """Sidebar panel showing the current plan's steps and their status.

    Displays steps as a numbered list with status indicators:
      ✓ completed step
      → step in progress (highlighted)
      ○ pending step
      ✗ failed step
    """

    _steps: reactive[list[dict]] = reactive([], recompose=False)
    _goal: reactive[str] = reactive("")
    _visible: reactive[bool] = reactive(True)

    DEFAULT_CSS: ClassVar[str] = """
    PlanPanel {
        margin: 0 1;
        padding: 0 1;
    }
    """

    def update_plan(self, goal: str, steps: list[dict]) -> None:
        """Update the plan display with new data.

        Parameters
        ----------
        goal:
            The plan's goal description.
        steps:
            List of step dicts with keys: description, status, result.
        """
        self._goal = goal
        self._steps = steps

    def clear(self) -> None:
        """Clear the plan display."""
        self._goal = ""
        self._steps = []

    def render(self) -> Text:
        if not self._steps and not self._goal:
            return Text("  No active plan", style="dim")

        text = Text()

        if self._goal:
            text.append(f" \U0001f9e0 {self._goal}", style="bold")
            text.append("\n")

        for _i, step in enumerate(self._steps):
            description = step.get("description", "")
            status = step.get("status", "pending")
            result = step.get("result", "")

            if status == "completed":
                icon = "\u2713"
                style = "bold #A3BE8C"  # green
            elif status == "in_progress":
                icon = "\u2192"
                style = "bold #EBCB8B"  # yellow
            elif status == "failed":
                icon = "\u2717"
                style = "bold #BF616A"  # red
            else:
                icon = "\u25cb"
                style = "dim"

            text.append(f"\n  {icon} ", style=style)
            text.append(description, style=style if status == "in_progress" else "")

            if result:
                text.append(f" \u2014 {result[:60]}", style="dim")

        return text
