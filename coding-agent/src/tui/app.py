"""Main Textual application for the coding agent TUI."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from coding_agent.agent.context import ContextManager
from coding_agent.agent.loop import AgentLoop
from coding_agent.agent.permission_callback import QueueCallback
from coding_agent.agent.permissions import PermissionManager
from coding_agent.config import Settings
from coding_agent.llm.client import LLMClient
from coding_agent.tui.stream_handler import StreamHandler
from coding_agent.tui.theme import TUI_CSS
from coding_agent.tui.widgets.chat import ChatDisplay
from coding_agent.tui.widgets.input import UserInput
from coding_agent.tui.widgets.permission import PermissionDialog
from coding_agent.tui.widgets.sidebar import Sidebar

# Register tools
importlib.import_module("coding_agent.tools")


class CodingAgentApp(App[None]):
    """Main coding agent TUI application.

    Layout:
    +----------------------------------+----------+
    |                                  |  Sidebar |
    |          Chat Display            |  Status  |
    |                                  |  Tools   |
    |                                  |  Tokens  |
    +----------------------------------+----------+
    |              User Input                    |
    +---------------------------------------------+

    Key bindings:
        Enter       → submit message
        Shift+Enter → newline in input
        Ctrl+C      → quit
        Ctrl+L      → clear chat
        Ctrl+N      → new session
    """

    CSS = TUI_CSS

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear Chat"),
        Binding("ctrl+r", "regenerate", "Regenerate"),
        Binding("ctrl+n", "new_session", "New Session"),
    ]

    TITLE = "Coding Agent"
    SUB_TITLE = "AI-powered coding assistant"

    def __init__(self, workspace: Path | None = None) -> None:
        super().__init__()
        self.workspace = workspace or Path(".")
        self.settings = Settings()

        # Build LLM client
        provider = self.settings.llm_provider
        if provider == "openrouter":
            api_keys = self.settings.get_openrouter_api_keys()
            model = self.settings.openrouter_model
        else:
            api_keys = self.settings.get_api_keys()
            model = self.settings.llm_model

        self.llm_client = LLMClient(model=model, api_keys=api_keys, provider=provider)

        # Permission callback (queue-based for TUI)
        self._perm_callback = QueueCallback()
        self._permission_future: asyncio.Future[PermissionDialog.Response] | None = None

        # Build agent components
        permissions = PermissionManager()
        context = ContextManager(max_tokens=self.settings.max_tokens)

        self.agent_loop = AgentLoop(
            llm_client=self.llm_client,
            permission_manager=permissions,
            context_manager=context,
            workspace=self.workspace,
            max_iterations=self.settings.max_iterations,
            permission_callback=self._perm_callback,
        )

        # Stream handler
        self._stream_handler = StreamHandler(self, self.agent_loop)

        # Stats tracking
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.tool_count = 0

    def compose(self) -> ComposeResult:
        """Build the UI layout."""
        yield Header()
        yield ChatDisplay(id="chat")
        yield Sidebar(id="sidebar")
        yield UserInput(id="input-container")
        yield PermissionDialog(id="permission-dialog")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        # Set sidebar values
        self.sidebar.update_stats(
            model=self.llm_client.model,
            provider=self.llm_client.provider,
            workspace=str(self.workspace.resolve()),
            state="idle",
        )

        # Focus input
        self.query_one("#input-container", UserInput).set_focus()

        # Welcome message
        self.chat_display.add_status(
            f"Coding Agent v0.1.0 -- {self.llm_client.provider}/{self.llm_client.model}"
        )
        self.chat_display.add_status(
            "Type your message and press Enter to submit. Shift+Enter for newline."
        )

    @property
    def chat_display(self) -> ChatDisplay:
        return self.query_one("#chat", ChatDisplay)

    @property
    def sidebar(self) -> Sidebar:
        return self.query_one("#sidebar", Sidebar)

    @property
    def user_input(self) -> UserInput:
        return self.query_one("#input-container", UserInput)

    @property
    def permission_dialog(self) -> PermissionDialog:
        return self.query_one("#permission-dialog", PermissionDialog)

    # -- Message handlers --

    def on_user_input_submitted(self, message: UserInput.Submitted) -> None:
        """Handle user input submission."""
        text = message.text
        if not text:
            return

        # Add user message to chat
        self.chat_display.add_user_message(text)

        # Disable input while processing
        self.user_input.disabled = True

        # Run agent loop
        self.run_worker(self._stream_handler.run(text), exclusive=True)

    def on_permission_dialog_response(self, message: PermissionDialog.Response) -> None:
        """Handle permission dialog response."""
        if self._permission_future and not self._permission_future.done():
            self._permission_future.set_result(message)

    async def wait_for_permission(self) -> PermissionDialog.Response:
        """Wait for the user to respond to a permission request."""
        self._permission_future = asyncio.get_event_loop().create_future()
        return await self._permission_future

    # -- Actions --

    def action_clear(self) -> None:
        """Clear the chat display."""
        self.chat_display.clear_chat()
        self.chat_display.add_status("Chat cleared.")

    def action_regenerate(self) -> None:
        """Regenerate the last response (re-run last prompt)."""
        # TODO: implement regeneration
        self.chat_display.add_status("Regenerate not yet implemented.")

    def action_new_session(self) -> None:
        """Start a new session (clear context)."""
        self.agent_loop.reset()
        self.chat_display.clear_chat()
        self.tool_count = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.sidebar.update_stats(
            tool_count=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost=0.0,
            state="idle",
        )
        self.chat_display.add_status("New session started.")

    def set_state(self, state: str) -> None:
        """Update the app state in the sidebar."""
        self.sidebar.set_state(state)
