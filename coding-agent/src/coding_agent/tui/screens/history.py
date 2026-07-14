"""History viewer screen.

Displays past sessions with their messages in a browsable Textual screen.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from coding_agent.logging import logger
from coding_agent.session.manager import SessionManager


class HistoryScreen(Screen):
    """Screen that shows past session history with messages."""

    CSS = """
    #history-list {
        height: 1fr;
        padding: 1 2;
    }
    .session-header {
        padding: 1 2;
        margin: 1 0 0 0;
        border: solid $accent;
        background: $surface;
        text-style: bold;
    }
    .session-meta {
        padding: 0 2;
        margin: 0 0 0 0;
        color: $text-muted;
        text-style: italic;
        border-left: solid $primary;
        background: $surface-darken-1;
    }
    .msg-user {
        padding: 0 2 0 4;
        margin: 0;
        border-left: solid $success;
        background: $surface-darken-1;
    }
    .msg-assistant {
        padding: 0 2 0 4;
        margin: 0;
        border-left: solid $warning;
        background: $surface;
    }
    .msg-tool {
        padding: 0 2 0 6;
        margin: 0;
        border-left: dashed gray;
        color: $text-muted;
        text-style: italic;
    }
    .no-sessions {
        color: $text-muted;
        padding: 2 4;
        text-style: italic;
    }
    .status-bar {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: $surface;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
    ]

    def __init__(self, workspace: Path | None = None) -> None:
        super().__init__()
        self._workspace = workspace or Path(".")

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="history-list")
        yield Static("Esc/Q = back", classes="status-bar")
        yield Footer()

    def action_go_back(self) -> None:
        """Go back to the previous screen."""
        self.app.pop_screen()

    async def on_mount(self) -> None:
        """Load session history on mount."""
        await self._load_history()

    async def _load_history(self) -> None:
        """Load and display session history with messages."""
        from coding_agent.config import Settings

        settings = Settings()
        db_path = settings.get_db_path()
        manager = SessionManager(db_path)

        try:
            await manager.initialize()
            sessions = await manager.list_sessions(limit=20)
        except Exception as exc:
            logger.error("history_load_failed", error=str(exc))
            sessions = []
        finally:
            await manager.close()

        container = self.query_one("#history-list")

        if not sessions:
            await container.mount(Static("No session history found.", classes="no-sessions"))
            return

        for session in sessions:
            # Session header
            meta_parts = [session.model or "unknown"]
            if session.provider:
                meta_parts.append(session.provider)
            if session.total_tokens:
                meta_parts.append(f"{session.total_tokens:,} tokens")
            if session.total_cost:
                meta_parts.append(f"${session.total_cost:.4f}")
            meta_str = " | ".join(meta_parts)

            date_str = session.created_at[:19].replace("T", " ")
            header_text = (
                f"[bold cyan]{session.id}[/] — {date_str}\n"
                f"[dim]{meta_str}[/]"
            )
            await container.mount(Static(header_text, classes="session-header"))

            # Load messages for this session
            try:
                manager2 = SessionManager(db_path)
                await manager2.initialize()
                messages = await manager2.load_session(session.id)
                await manager2.close()
            except Exception:
                messages = []

            for msg in messages:
                if msg.role == "user":
                    preview = msg.content[:300].replace("\n", " ")
                    if len(msg.content) > 300:
                        preview += "..."
                    await container.mount(
                        Static(f"[bold green]User:[/] {preview}", classes="msg-user")
                    )
                elif msg.role == "assistant":
                    preview = msg.content[:300].replace("\n", " ")
                    if len(msg.content) > 300:
                        preview += "..."
                    if preview:
                        await container.mount(
                            Static(f"[bold yellow]Agent:[/] {preview}", classes="msg-assistant")
                        )
                    # Show tool calls
                    if msg.tool_calls:
                        for tc in msg.tool_calls:
                            fn = tc.get("function", {})
                            name = fn.get("name", "?")
                            await container.mount(
                                Static(f"  [dim]→ {name}[/]", classes="msg-tool")
                            )
                elif msg.role == "tool":
                    preview = msg.content[:150].replace("\n", " ")
                    if len(msg.content) > 150:
                        preview += "..."
                    await container.mount(
                        Static(f"  [dim]← {preview}[/]", classes="msg-tool")
                    )
