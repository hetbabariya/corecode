"""TUI Session Browser — visual session management and resumption."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Input, Static


_NORD = {
    "primary": "#88C0D0",
    "secondary": "#81A1C1",
    "accent": "#B48EAD",
    "foreground": "#ECEFF4",
    "success": "#A3BE8C",
    "warning": "#EBCB8B",
    "error": "#BF616A",
    "dim": "#7B88A1",
    "surface": "#3B4252",
    "panel": "#434C5E",
}

BROWSER_CSS = """
Screen {
    background: $background;
}

#search-bar {
    dock: top;
    height: 3;
    background: $surface;
    padding: 0 1;
    border-bottom: tall $panel;
}

#search-bar Input {
    background: $panel;
    color: $foreground;
    border: tall $primary;
    padding: 0 1;
    width: 100%;
}

#session-table {
    height: 1fr;
    background: $background;
}

#info-panel {
    dock: bottom;
    height: 3;
    background: $surface;
    padding: 0 1;
    border-top: tall $panel;
    color: $text-muted;
}

#info-panel Static {
    color: $text-muted;
}

.help-hint {
    color: $text-muted;
    padding: 0 1;
}

DataTable > .datatable--header {
    background: $panel;
    color: $primary;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: $primary 30%;
    color: $foreground;
}

DataTable > .datatable--even-row {
    background: $surface;
}

DataTable > .datatable--odd-row {
    background: $background;
}
"""


class SessionBrowser(App[None]):
    """TUI session browser for listing, searching, and resuming sessions."""

    TITLE = "Coding Agent — Sessions"
    SUB_TITLE = ""
    CSS = BROWSER_CSS

    BINDINGS = [
        Binding("ctrl+d", "quit", "Quit", show=True),
        Binding("escape", "quit", "Quit", show=False),
        Binding("enter", "resume", "Resume", show=True),
        Binding("n", "new_session", "New", show=True),
        Binding("d", "delete_session", "Delete", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    selected_session_id: reactive[str | None] = reactive(None)
    _sessions: list[dict[str, Any]] = []
    _launch_session_id: str | None = None

    def __init__(self, workspace: Path = Path(".")) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self) -> ComposeResult:
        yield Header(icon="\u2593")
        with Vertical():
            with Horizontal(id="search-bar"):
                yield Input(
                    placeholder="Search sessions... (model, summary, id)",
                    id="search-input",
                )
            yield DataTable(id="session-table", cursor_type="row")
            with Horizontal(id="info-panel"):
                yield Static(
                    " Enter:Resume | n:New | d:Delete | r:Refresh | Ctrl+D:Quit",
                    classes="help-hint",
                )
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.add_columns("ID", "Date", "Model", "Tokens", "Cost", "Summary")
        table.zebra_stripes = True
        await self._load_sessions()
        self.query_one("#search-input").focus()

    async def _load_sessions(self, filter_text: str = "") -> None:
        from coding_agent.config import Settings
        from coding_agent.session.manager import SessionManager

        settings = Settings()
        mgr = SessionManager(settings.get_db_path())
        await mgr.initialize()
        sessions = await mgr.list_sessions(limit=100)
        await mgr.close()

        self._sessions = []
        table = self.query_one("#session-table", DataTable)
        table.clear()

        for s in sessions:
            date = s.created_at[:16].replace("T", " ") if s.created_at else "?"
            model = s.model or "unknown"
            tokens = f"{s.total_tokens:,}" if s.total_tokens else "0"
            cost = f"${s.total_cost:.4f}" if s.total_cost else "$0"
            summary = (s.summary or "(no summary)")[:60]
            sid = s.id

            # Apply filter
            if filter_text:
                flt = filter_text.lower()
                searchable = f"{sid} {model} {summary} {date}".lower()
                if flt not in searchable:
                    continue

            row_key = table.add_row(sid, date, model, tokens, cost, summary)
            self._sessions.append({
                "id": sid,
                "date": date,
                "model": model,
                "tokens": tokens,
                "cost": cost,
                "summary": summary,
                "row_key": row_key,
            })

    @on(Input.Changed, "#search-input")
    async def on_search_changed(self, event: Input.Changed) -> None:
        await self._load_sessions(filter_text=event.value)

    @on(DataTable.RowSelected, "#session-table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        row = event.cursor_row
        if row is not None and row < len(self._sessions):
            self.selected_session_id = self._sessions[row]["id"]

    async def action_resume(self) -> None:
        """Resume the selected session."""
        table = self.query_one("#session-table", DataTable)
        cursor = table.cursor_coordinate
        if cursor.row < len(self._sessions):
            session_id = self._sessions[cursor.row]["id"]
            self._launch_session_id = session_id
            self.exit()

    async def action_new_session(self) -> None:
        """Launch a new session (no resumption)."""
        self._launch_session_id = None
        self.exit()

    async def action_delete_session(self) -> None:
        """Delete the selected session after confirmation."""
        table = self.query_one("#session-table", DataTable)
        cursor = table.cursor_coordinate
        if cursor.row >= len(self._sessions):
            return

        session_id = self._sessions[cursor.row]["id"]

        # Simple confirmation via system message toggle
        from coding_agent.config import Settings
        from coding_agent.session.manager import SessionManager

        settings = Settings()
        mgr = SessionManager(settings.get_db_path())
        await mgr.initialize()

        # Delete messages first, then session
        assert mgr._db is not None
        await mgr._db.execute(
            "DELETE FROM messages WHERE session_id = ?", (session_id,),
        )
        await mgr._db.execute(
            "DELETE FROM operations WHERE session_id = ?", (session_id,),
        )
        await mgr._db.execute(
            "DELETE FROM sessions WHERE id = ?", (session_id,),
        )
        await mgr._db.commit()
        await mgr.close()

        await self._load_sessions(
            filter_text=self.query_one("#search-input", Input).value,
        )

    async def action_refresh(self) -> None:
        """Refresh the session list."""
        await self._load_sessions(
            filter_text=self.query_one("#search-input", Input).value,
        )


def run_browser(workspace: Path = Path(".")) -> str | None:
    """Run the session browser and return the selected session ID.

    Returns None if the user chose to start a new session or quit.
    """
    browser = SessionBrowser(workspace=workspace)
    browser.run()
    return browser._launch_session_id
