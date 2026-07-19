"""TUI Session Browser — visual session management and resumption."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from coding_agent.tui.theme import create_nord_theme


class BrowserScreen(Screen[str | None]):
    """Screen for browsing, searching, and resuming sessions."""

    TITLE = "Coding Agent \u2014 Sessions"
    CSS_PATH = "browser.tcss"

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
        if self.selected_session_id:
            self.dismiss(self.selected_session_id)

    async def action_new_session(self) -> None:
        """Start a new session."""
        self.dismiss("__new__")

    async def action_delete_session(self) -> None:
        """Delete the selected session."""
        if not self.selected_session_id:
            return
        from coding_agent.config import Settings
        from coding_agent.session.manager import SessionManager

        settings = Settings()
        mgr = SessionManager(settings.get_db_path())
        await mgr.initialize()
        assert mgr._db is not None
        await mgr._db.execute(
            "DELETE FROM messages WHERE session_id = ?", (self.selected_session_id,),
        )
        await mgr._db.execute(
            "DELETE FROM operations WHERE session_id = ?", (self.selected_session_id,),
        )
        await mgr._db.execute(
            "DELETE FROM sessions WHERE id = ?", (self.selected_session_id,),
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


class SessionBrowser(App[str | None]):
    """Standalone session browser App (backward compat wrapper)."""

    CSS_PATH = "browser.tcss"

    def __init__(self, workspace: Path = Path(".")) -> None:
        super().__init__()
        self.workspace = workspace
        self._launch_session_id: str | None = None

    def on_mount(self) -> None:
        self.register_theme(create_nord_theme())
        self.theme = "coding-agent"
        self.push_screen(BrowserScreen(self.workspace), self._on_browser_done)

    def _on_browser_done(self, session_id: str | None) -> None:
        self._launch_session_id = session_id
        self.exit(session_id)


def run_browser(workspace: Path = Path(".")) -> str | None:
    """Run the session browser and return the selected session ID."""
    browser = SessionBrowser(workspace=workspace)
    browser.run()
    return browser._launch_session_id
