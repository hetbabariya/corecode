"""Unified Coding Agent TUI application with screen navigation."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from coding_agent.tui.browser import BrowserScreen
from coding_agent.tui.repl import ChatScreen
from coding_agent.tui.theme import create_nord_theme


class CodingAgentApp(App[None]):
    """Unified TUI application with browser and chat screens."""

    CSS_PATH = ["repl.tcss", "browser.tcss"]
    TITLE = "Coding Agent"

    def __init__(self, workspace: Path = Path(".")) -> None:
        super().__init__()
        self.workspace = workspace

    def on_mount(self) -> None:
        self.register_theme(create_nord_theme())
        self.theme = "coding-agent"
        self.push_screen(BrowserScreen(self.workspace), self._on_browser_done)

    def _on_browser_done(self, session_id: str | None) -> None:
        if session_id is None:
            self.exit()
            return
        if session_id == "__new__":
            session_id = None
        self.push_screen(
            ChatScreen(
                workspace=self.workspace,
                permission="auto",
                session_id=session_id,
            ),
            self._on_chat_done,
        )

    def _on_chat_done(self, value: str | None) -> None:
        # After chat exits, go back to browser
        self.push_screen(BrowserScreen(self.workspace), self._on_browser_done)
