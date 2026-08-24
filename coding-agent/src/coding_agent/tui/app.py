"""Unified Coding Agent TUI application with screen navigation."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from coding_agent.tui.browser import BrowserScreen
from coding_agent.tui.repl import ChatScreen
from coding_agent.tui.theme import create_nord_theme

# ── Demo scenarios ───────────────────────────────────────────────────────

DEMO_SCENARIOS: list[dict[str, str]] = [
    {
        "title": "Basic File Reading",
        "prompt": "Read the file README.md and tell me what this project is about in 2 sentences.",
    },
    {
        "title": "File Operations",
        "prompt": (
            "Create a file called demo_calc.py with a function called add that takes two numbers "
            "and returns their sum. Then create a subtract function in the same file."
        ),
    },
    {
        "title": "Code Search",
        "prompt": "Search for all Python files in the src/ directory and list them.",
    },
    {
        "title": "Shell Execution",
        "prompt": "Run 'python --version' to check the Python version.",
    },
    {
        "title": "Git Operations",
        "prompt": "Show the git status and the last 2 commits.",
    },
    {
        "title": "Plan Mode",
        "prompt": (
            "Create a plan to build a simple todo app with add, list, and complete features. "
            "Then mark each step as completed."
        ),
    },
    {
        "title": "Memory",
        "prompt": (
            "Remember that this workspace uses Python 3.12+ with uv as package manager. "
            "Then recall what you remember."
        ),
    },
    {
        "title": "Summary",
        "prompt": "Summarize all the files we created and modified during this demo.",
    },
]


class CodingAgentApp(App[None]):
    """Unified TUI application with browser and chat screens."""

    CSS_PATH = ["repl.tcss", "browser.tcss"]
    TITLE = "Coding Agent"

    def __init__(
        self,
        workspace: Path = Path("."),
        demo_mode: bool = False,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.demo_mode = demo_mode

    def on_mount(self) -> None:
        self.register_theme(create_nord_theme())
        self.theme = "coding-agent"

        if self.demo_mode:
            # Skip browser, go straight to chat with demo prompts
            self.push_screen(
                ChatScreen(
                    workspace=self.workspace,
                    permission="auto",
                    session_id=None,
                    demo_mode=True,
                ),
                self._on_chat_done,
            )
        else:
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
        if self.demo_mode:
            self.exit()
            return
        # After chat exits, go back to browser
        self.push_screen(BrowserScreen(self.workspace), self._on_browser_done)
