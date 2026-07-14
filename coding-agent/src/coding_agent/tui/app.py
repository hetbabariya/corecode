"""Main Textual application for the coding agent TUI."""

from __future__ import annotations

import asyncio
import importlib
import shlex
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static

from coding_agent.agent.context import ContextManager
from coding_agent.agent.loop import AgentLoop
from coding_agent.agent.permission_callback import QueueCallback
from coding_agent.agent.permissions import PermissionManager
from coding_agent.config import Settings
from coding_agent.llm.client import LLMClient
from coding_agent.logging import get_tui_handler, logger, setup_logging
from coding_agent.tui.stream_handler import StreamHandler
from coding_agent.tui.theme import build_css
from coding_agent.tui.themes import get_theme, list_themes, save_theme_preference
from coding_agent.tui.widgets.chat import ChatDisplay
from coding_agent.tui.widgets.input import UserInput
from coding_agent.tui.widgets.log_viewer import LogViewer
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
        Enter       -> submit message
        Shift+Enter -> newline in input
        Ctrl+C      -> quit
        Ctrl+L      -> clear chat
        Ctrl+N      -> new session
        Ctrl+Z      -> undo last file change
        Ctrl+B      -> view session history
        Ctrl+D      -> toggle debug/log viewer panel
        PgUp/PgDn   -> scroll chat
        Ctrl+Home   -> scroll chat to top
        Ctrl+End    -> scroll chat to bottom
    """

    CSS = ""

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("ctrl+r", "regenerate", "Redo", show=False),
        Binding("ctrl+n", "new_session", "New"),
        Binding("ctrl+z", "undo", "Undo"),
        Binding("ctrl+b", "history", "History"),
        Binding("ctrl+d", "toggle_debug", "Debug"),
        Binding("pageup", "scroll_chat_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_chat_down", "Scroll Down", show=False),
        Binding("ctrl+home", "scroll_chat_top", "Scroll Top", show=False),
        Binding("ctrl+end", "scroll_chat_bottom", "Scroll Bottom", show=False),
    ]

    TITLE = "Coding Agent"
    SUB_TITLE = "AI-powered coding assistant"

    def __init__(self, workspace: Path | None = None, log_level: str = "INFO") -> None:
        super().__init__()
        self.workspace = workspace or Path(".")
        self.settings = Settings()

        # Initialize logging with TUI capture
        setup_logging(level=log_level, log_file=self.settings.log_file, capture_for_tui=True)

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

        # Session persistence
        from coding_agent.session.manager import SessionManager
        from coding_agent.agent.memory import MemoryManager

        self._session_manager = SessionManager(self.settings.get_db_path())
        self._memory_manager = MemoryManager(self._session_manager)

        self.agent_loop = AgentLoop(
            llm_client=self.llm_client,
            permission_manager=permissions,
            context_manager=context,
            workspace=self.workspace,
            max_iterations=self.settings.max_iterations,
            permission_callback=self._perm_callback,
            memory_manager=self._memory_manager,
            session_manager=self._session_manager,
        )

        # Stream handler
        self._stream_handler = StreamHandler(self, self.agent_loop)

        # Stats tracking
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.tool_count = 0

        # Debug panel state
        self._debug_visible = False

        # Theme
        self._current_theme_name = "dark"

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
        # Apply theme CSS
        try:
            theme = get_theme()
            self._current_theme_name = theme.name
            self.css = build_css(theme)
        except Exception as exc:
            logger.error("theme_load_failed", error=str(exc))

        # Initialize session manager (async SQLite open)
        self.run_worker(self._init_session())

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
        model_name = f"{self.llm_client.provider}/{self.llm_client.model}"
        self.chat_display.add_status(f"Coding Agent v0.1.0 -- {model_name}")
        self.chat_display.add_status(
            "Type your message and press Enter. Shift+Enter for newline."
        )
        self.chat_display.add_status(
            "Commands: /theme, /themes, /help. Ctrl+D for debug log."
        )

    async def _init_session(self) -> None:
        """Async session initialization."""
        await self._session_manager.initialize()
        logger.info(
            "tui_app_mounted",
            model=self.llm_client.model,
            provider=self.llm_client.provider,
            workspace=str(self.workspace.resolve()),
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

    # ── Message handlers ──────────────────────────────────

    def on_user_input_submitted(self, message: UserInput.Submitted) -> None:
        """Handle user input submission."""
        text = message.text
        if not text:
            return

        # Handle /commands before forwarding to agent
        if text.startswith("/"):
            try:
                self._handle_command(text)
            except Exception as exc:
                self.chat_display.add_error(f"Command failed: {exc}")
            return

        # Add user message to chat
        self.chat_display.add_user_message(text)

        # Disable input while processing
        self.user_input.disabled = True

        # Run agent loop
        self.run_worker(self._stream_handler.run(text), exclusive=True)

    def _handle_command(self, text: str) -> None:
        """Handle slash commands."""
        try:
            parts = shlex.split(text.strip())
        except ValueError:
            parts = text.strip().split()
        cmd = parts[0].lower() if parts else ""
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/theme":
            self._cmd_theme(arg)
        elif cmd == "/themes":
            self._cmd_list_themes()
        elif cmd == "/help":
            self._cmd_help()
        elif cmd == "/cost":
            self._cmd_cost()
        elif cmd == "/clear":
            self.action_clear()
        elif cmd == "/undo":
            self.action_undo()
        else:
            self.chat_display.add_status(f"Unknown command: {cmd}. Type /help for options.")

    def _cmd_theme(self, name: str) -> None:
        """Switch the active theme at runtime."""
        if not name:
            self.chat_display.add_status(
                f"Current theme: {self._current_theme_name}. Use /themes to list."
            )
            return
        available = list_themes()
        if name not in available:
            self.chat_display.add_status(
                f"Unknown theme '{name}'. Available: {', '.join(available)}"
            )
            return
        theme = get_theme(name)
        self.css = build_css(theme)
        self._current_theme_name = name
        save_theme_preference(name)
        self.chat_display.add_status(f"Theme changed to '{name}'.")

    def _cmd_list_themes(self) -> None:
        """List available themes."""
        themes = list_themes()
        self.chat_display.add_status("Available themes: " + ", ".join(themes))

    def _cmd_help(self) -> None:
        """Show available commands."""
        help_text = (
            "Commands:\n"
            "  /theme <name>  -- switch theme\n"
            "  /themes        -- list themes\n"
            "  /cost          -- show session cost\n"
            "  /clear         -- clear chat\n"
            "  /undo          -- undo last file change\n"
            "  /help          -- this message\n"
            "\n"
            "Keyboard shortcuts:\n"
            "  Ctrl+Z   -- undo  |  Ctrl+L   -- clear\n"
            "  Ctrl+N   -- new session  |  Ctrl+D -- debug log\n"
            "  PgUp/PgDn -- scroll chat"
        )
        self.chat_display.add_status(help_text)

    def _cmd_cost(self) -> None:
        """Show current session cost."""
        cost = self.llm_client.total_usage.estimated_cost
        tokens = self.total_tokens
        self.chat_display.add_status(f"Session cost: ${cost:.4f} | Tokens: {tokens:,}")

    def on_permission_dialog_response(self, message: PermissionDialog.Response) -> None:
        """Handle permission dialog response."""
        if self._permission_future and not self._permission_future.done():
            self._permission_future.set_result(message)

    async def wait_for_permission(self) -> PermissionDialog.Response:
        """Wait for the user to respond to a permission request."""
        self._permission_future = asyncio.get_running_loop().create_future()
        return await self._permission_future

    # ── Actions ───────────────────────────────────────────

    def action_clear(self) -> None:
        """Clear the chat display."""
        self.chat_display.clear_chat()
        self.chat_display.add_status("Chat cleared.")

    def action_regenerate(self) -> None:
        """Regenerate the last response (re-run last prompt)."""
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
        logger.info("tui_new_session")

    def action_undo(self) -> None:
        """Undo the last file mutation."""
        from coding_agent.agent.undo import UndoStack

        stack = self.agent_loop.undo_stack
        entry = stack.undo()
        if entry is None:
            self.chat_display.add_status("Nothing to undo.")
            return
        try:
            UndoStack.apply_entry(entry, redo=False)
            desc = entry.description or f"{entry.tool_name} on {entry.file_path}"
            self.chat_display.add_status(f"Undone: {desc}")
            logger.info("tui_undo", file=entry.file_path)
        except Exception as exc:
            self.chat_display.add_status(f"Undo failed: {exc}")
            logger.error("tui_undo_failed", error=str(exc))

    def action_history(self) -> None:
        """Open the session history viewer."""
        from coding_agent.tui.screens.history import HistoryScreen

        self.push_screen(HistoryScreen(workspace=self.workspace))

    def action_toggle_debug(self) -> None:
        """Toggle the debug log viewer panel."""
        if len(self.screen_stack) > 1:
            return

        self._debug_visible = not self._debug_visible

        if self._debug_visible:
            self._show_debug_panel()
        else:
            self._hide_debug_panel()

    def _show_debug_panel(self) -> None:
        """Show the debug log viewer, replacing the sidebar."""
        try:
            sidebar = self.query_one("#sidebar")
            sidebar.remove()
        except Exception:
            pass

        handler = get_tui_handler()
        panel = Static(id="debug-panel")
        self.mount(panel)

        title = Static("Debug Log (Ctrl+D to close)", classes="log-viewer-title")
        panel.mount(title)

        viewer = LogViewer(handler=handler, id="log-viewer", max_lines=200)
        panel.mount(viewer)

        self.screen.styles.grid_size = 1
        self.screen.styles.grid_columns = "1fr"

    def _hide_debug_panel(self) -> None:
        """Hide the debug panel and restore the sidebar."""
        try:
            panel = self.query_one("#debug-panel")
            panel.remove()
        except Exception:
            pass

        self.screen.styles.grid_size = 2
        self.screen.styles.grid_columns = "1fr 30"

        sidebar = Sidebar(id="sidebar")
        self.mount(sidebar)
        sidebar.update_stats(
            model=self.llm_client.model,
            provider=self.llm_client.provider,
            workspace=str(self.workspace.resolve()),
            state="idle",
            tool_count=self.tool_count,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            cost=self.llm_client.total_usage.estimated_cost,
        )

    def action_scroll_chat_up(self) -> None:
        """Scroll chat area up by one page."""
        offset = max(1, self.chat_display.size.height - 2)
        self.chat_display.scroll_relative(0, -offset)

    def action_scroll_chat_down(self) -> None:
        """Scroll chat area down by one page."""
        offset = max(1, self.chat_display.size.height - 2)
        self.chat_display.scroll_relative(0, offset)

    def action_scroll_chat_top(self) -> None:
        """Scroll chat area to the very top."""
        self.chat_display.scroll_home(animate=False)

    def action_scroll_chat_bottom(self) -> None:
        """Scroll chat area to the very bottom."""
        self.chat_display.scroll_end(animate=False)

    def set_state(self, state: str) -> None:
        """Update the app state in the sidebar."""
        try:
            self.sidebar.set_state(state)
        except Exception:
            pass
