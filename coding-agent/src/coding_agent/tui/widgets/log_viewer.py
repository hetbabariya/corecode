"""Log viewer widget — displays recent log entries in a scrollable panel."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.timer import Timer
from textual.widgets import RichLog

if TYPE_CHECKING:
    from coding_agent.logging import TUILogHandler


class LogViewer(RichLog):
    """Auto-updating log viewer that reads from the TUILogHandler buffer.

    Polls the log buffer every 0.5 seconds and renders new entries.
    Pauses auto-scroll if the user scrolls up.
    """

    _last_count: int = 0
    _auto_scroll: bool = True
    _poll_timer: Timer | None = None

    def __init__(self, handler: TUILogHandler, max_lines: int = 500, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._handler = handler
        self._max_lines = max_lines
        self._last_count = 0

    def on_mount(self) -> None:
        """Start polling for new log entries."""
        self._poll_timer = self.set_interval(0.5, self._poll_logs)

    def on_unmount(self) -> None:
        """Stop polling."""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None

    def _poll_logs(self) -> None:
        """Check for new log entries and render them."""
        entries = self._handler.get_entries(count=self._max_lines)
        if len(entries) == self._last_count:
            return

        self._last_count = len(entries)
        self.clear()

        for entry in entries[-self._max_lines:]:
            line = self._render_entry(entry)
            self.write(line)

        if self._auto_scroll:
            self.scroll_end(animate=False)

    def _render_entry(self, entry: object) -> Text:
        """Render a single log entry as colored Rich Text."""
        from coding_agent.logging import LogEntry

        if not isinstance(entry, LogEntry):
            return Text(str(entry))

        # Short timestamp: HH:MM:SS
        try:
            ts = datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")
        except (ValueError, OSError):
            ts = "??:??:??"

        # Level badge
        level = entry.level.upper()
        if level == "DEBUG":
            level_text = Text(f" {level} ", style="dim")
        elif level == "INFO":
            level_text = Text(f" {level} ", style="bold cyan")
        elif level == "WARNING":
            level_text = Text(f" {level} ", style="bold yellow")
        elif level == "ERROR":
            level_text = Text(f" {level} ", style="bold red")
        else:
            level_text = Text(f" {level} ", style="bold")

        # Build line
        line = Text()
        line.append(f"{ts} ", style="dim")
        line.append_text(level_text)
        line.append(f" {entry.event}")

        # Append key data fields if present
        if entry.data:
            interesting = {
                k: v
                for k, v in entry.data.items()
                if k not in ("event", "log_level", "log_level_as_number")
                and v is not None
                and str(v).strip()
            }
            if interesting:
                detail = ", ".join(f"{k}={v}" for k, v in list(interesting.items())[:5])
                line.append(f" [{detail}]", style="dim")

        return line
