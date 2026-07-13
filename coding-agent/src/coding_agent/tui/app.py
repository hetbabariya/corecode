"""Main Textual application for the coding agent TUI."""

from __future__ import annotations

import asyncio
import importlib
import shlex
from enum import Enum
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding

from coding_agent.agent.context import ContextManager
from coding_agent.agent.loop import AgentLoop
from coding_agent.agent.permission_callback import QueueCallback
from coding_agent.agent.permissions import PermissionManager
from coding_agent.config import Settings
from coding_agent.llm.client import LLMClient
from coding_agent.tui.keybindings import load_custom_bindings
from coding_agent.tui.stream_handler import StreamHandler
from coding_agent.tui.theme import build_css
from coding_agent.tui.themes import get_theme, list_themes, save_theme_preference
from coding_agent.tui.widgets.chat import ChatDisplay, ToolCallMessage
from coding_agent.tui.widgets.help_bar import HelpBar
from coding_agent.tui.widgets.input import UserInput
from coding_agent.tui.widgets.permission import PermissionDialog
from coding_agent.tui.widgets.spinner import Spinner, SpinnerMode
from coding_agent.tui.widgets.status_bar import StatusBar

# Register tools
importlib.import_module("coding_agent.tools")


class DisplayMode(Enum):
    """Display modes for the chat area."""

    DEFAULT = "default"  # scrolling log
    FOCUS = "focus"  # compact: last prompt + tool summaries + final


class CodingAgentApp(App[None]):
    """Main coding agent TUI application.

    Layout::

        ┌─ StatusBar ─────────────────────────────────────┐
        │ [spinner] model · cost · tokens · state · perm   │
        ├─ ChatDisplay (scrollable) ──────────────────────┤
        │ ...                                             │
        ├─ UserInput ─────────────────────────────────────┤
        │ ┌─ teal border ────────────────────────────┐    │
        │ │ Type message...                          │    │
        │ └──────────────────────────────────────────┘    │
        ├─ HelpBar ───────────────────────────────────────┤
        │ Enter send · Shift+Enter newline · ↑↓ history   │
        └─────────────────────────────────────────────────┘

    Key bindings:
        Enter       → submit message
        Shift+Enter → newline in input
        Escape      → cancel current operation
        Tab         → amend last message
        Ctrl+C      → quit
        Ctrl+L      → clear chat
        Ctrl+N      → new session
        Ctrl+E      → explain last tool call
        PgUp/PgDn  → scroll chat
        Ctrl+Home   → scroll chat to top
        Ctrl+End    → scroll chat to bottom
    """

    CSS = build_css()

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear Chat"),
        Binding("ctrl+r", "regenerate", "Regenerate"),
        Binding("ctrl+n", "new_session", "New Session"),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("tab", "amend", "Amend", show=False),
        Binding("ctrl+e", "explain", "Explain", show=False),
        Binding("pageup", "scroll_chat_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_chat_down", "Scroll Down", show=False),
        Binding("ctrl+home", "scroll_chat_top", "Scroll Top", show=False),
        Binding("ctrl+end", "scroll_chat_bottom", "Scroll Bottom", show=False),
        Binding("ctrl+y", "copy_last", "Copy Last", show=False),
    ]

    TITLE = "Coding Agent"
    SUB_TITLE = ""

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

        # Display mode
        self._display_mode = DisplayMode.DEFAULT

        # Load custom keybindings and merge with defaults
        custom = load_custom_bindings()
        if custom:
            self.BINDINGS = list(self.BINDINGS) + custom

    def compose(self) -> ComposeResult:
        """Build the UI layout."""
        yield StatusBar(id="status-bar")
        yield ChatDisplay(id="chat")
        yield UserInput(id="input-container")
        yield HelpBar(id="help-bar")
        yield PermissionDialog(id="permission-dialog")

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        self.status_bar.update_stats(
            model=f"{self.llm_client.provider}/{self.llm_client.model}",
            state="idle",
        )

        self.query_one("#input-container", UserInput).set_focus()

        # Show welcome card
        model_name = f"{self.llm_client.provider}/{self.llm_client.model}"
        self.chat_display.add_welcome(model_name)

        # Start the spinner animation and synchronized blink timer
        self.query_one("#status-spinner", Spinner).start()
        self.set_interval(0.6, ToolCallMessage.toggle_blink)

    def on_resize(self) -> None:
        """Handle terminal resize — refresh layout-sensitive widgets."""
        self.query_one("#help-bar", HelpBar).refresh()

    # ── Properties ────────────────────────────────────────

    @property
    def chat_display(self) -> ChatDisplay:
        return self.query_one("#chat", ChatDisplay)

    @property
    def status_bar(self) -> StatusBar:
        return self.query_one("#status-bar", StatusBar)

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

        self.chat_display.add_user_message(text)
        self.user_input.disabled = True
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
        elif cmd == "/mode":
            self._cmd_mode(arg)
        elif cmd == "/themes":
            self._cmd_list_themes()
        elif cmd == "/modes":
            self._cmd_list_modes()
        elif cmd == "/help":
            self._cmd_help()
        else:
            self.chat_display.add_status(f"Unknown command: {cmd}")

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

    @property
    def _current_theme_name(self) -> str:
        return getattr(self, "__theme_name", "dark")

    @_current_theme_name.setter
    def _current_theme_name(self, value: str) -> None:
        self.__theme_name = value

    def _cmd_list_themes(self) -> None:
        """List available themes."""
        themes = list_themes()
        self.chat_display.add_status("Available themes: " + ", ".join(themes))

    def _cmd_mode(self, name: str) -> None:
        """Switch the display mode."""
        if not name:
            self.chat_display.add_status(
                f"Current mode: {self._display_mode.value}. Use /modes to list."
            )
            return
        try:
            mode = DisplayMode(name)
        except ValueError:
            modes = [m.value for m in DisplayMode]
            self.chat_display.add_status(
                f"Unknown mode '{name}'. Available: {', '.join(modes)}"
            )
            return
        self._display_mode = mode
        self._apply_display_mode()
        self.chat_display.add_status(f"Display mode: {mode.value}.")

    def _cmd_list_modes(self) -> None:
        """List available display modes."""
        modes = [m.value for m in DisplayMode]
        self.chat_display.add_status("Available modes: " + ", ".join(modes))

    def _cmd_help(self) -> None:
        """Show available commands."""
        help_text = (
            "Commands:\n"
            "  /theme <name>  — switch theme\n"
            "  /themes        — list themes\n"
            "  /mode <name>   — switch display mode\n"
            "  /modes         — list display modes\n"
            "  /help          — this message"
        )
        self.chat_display.add_status(help_text)

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
        self.status_bar.update_stats(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost=0.0,
            state="idle",
        )
        self.chat_display.add_status("New session started.")

    def action_cancel(self) -> None:
        """Cancel the current streaming operation."""
        if self._stream_handler.running:
            self._stream_handler.cancel()
            self.user_input.disabled = False
            self.user_input.set_focus()
            self.chat_display.add_task_cancelled()
            self.set_state("idle")

    def action_amend(self) -> None:
        """Amend the last user message (load it into input for editing)."""
        last = self.user_input.last_user_message
        if last:
            self.user_input.text_area.text = last
            self.user_input.text_area.cursor_location = (
                self.user_input.text_area.document.end
            )
            self.user_input.set_focus()

    def action_explain(self) -> None:
        """Explain the last tool call (placeholder)."""
        self.chat_display.add_status("Explain not yet implemented.")

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

    def action_copy_last(self) -> None:
        """Copy the last assistant message to clipboard."""
        text = self.chat_display.get_last_assistant_text()
        if text:
            try:
                import subprocess
                process = subprocess.Popen(
                    ["clip"], stdin=subprocess.PIPE, creationflags=0x08000000
                )
                process.communicate(text.encode("utf-16-le"))
            except Exception:
                pass

    def set_state(self, state: str) -> None:
        """Update the app state in the status bar."""
        self.status_bar.set_state(state)
        # Map agent state → spinner mode
        mode_map: dict[str, SpinnerMode] = {
            "idle": SpinnerMode.IDLE,
            "thinking": SpinnerMode.THINKING,
            "requesting": SpinnerMode.REQUESTING,
            "responding": SpinnerMode.RESPONDING,
            "tool_use": SpinnerMode.TOOL_USE,
        }
        spinner_mode = mode_map.get(state, SpinnerMode.IDLE)
        self.status_bar.set_spinner_mode(spinner_mode)

    # ── Display mode ──────────────────────────────────────

    def _apply_display_mode(self) -> None:
        """Apply CSS class for the current display mode."""
        screen = self.screen
        if self._display_mode == DisplayMode.FOCUS:
            screen.add_class("focus-mode")
        else:
            screen.remove_class("focus-mode")
