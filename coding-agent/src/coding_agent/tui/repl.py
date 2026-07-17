"""Interactive REPL for the Coding Agent using Textual."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input

from coding_agent.tui.theme import REPL_CSS, create_nord_theme
from coding_agent.logging import logger
from coding_agent.tui.widgets import (
    AssistantMessage,
    StatusBar,
    SystemMessage,
    ThinkingIndicator,
    Toolbar,
    ToolCallBlock,
    UserMessage,
)


class CodingAgentREPL(App[None]):
    """Interactive REPL for the Coding Agent."""

    TITLE = "Coding Agent"
    SUB_TITLE = ""
    CSS = REPL_CSS

    BINDINGS = [
        Binding("ctrl+d", "quit", "Exit", show=True),
        Binding("ctrl+c", "interrupt", "Interrupt", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
        Binding("ctrl+z", "undo", "Undo", show=True),
        Binding("ctrl+y", "redo", "Redo", show=True),
    ]

    def __init__(
        self,
        workspace: Path = Path("."),
        permission: str = "auto",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.workspace = workspace
        self.permission = permission
        self._agent: Any = None
        self._current_assistant: AssistantMessage | None = None
        self._current_tool: ToolCallBlock | None = None
        self._thinking: ThinkingIndicator | None = None
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._cost: float = 0.0
        self._iteration: int = 0
        self._processing: bool = False
        self._model_name: str = ""
        self._provider_name: str = ""

    def compose(self) -> ComposeResult:
        yield Header(icon="\u2593")
        with VerticalScroll(id="chat-view"):
            yield SystemMessage(
                "Welcome! Type a message to start. Ctrl+D to exit, Ctrl+C to interrupt.",
                level="info",
            )
        yield Toolbar(id="toolbar")
        yield Input(placeholder="Ask anything...", id="input", password=False)
        yield StatusBar(id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the agent after mount."""
        self.register_theme(create_nord_theme())
        self.theme = "coding-agent"
        await self._init_agent()
        self._update_toolbar_undo()
        self.query_one("#input").focus()

    async def _init_agent(self) -> None:
        """Initialize the agent loop."""
        from coding_agent.agent.context import ContextManager
        from coding_agent.agent.loop import AgentLoop
        from coding_agent.agent.memory import MemoryManager
        from coding_agent.agent.permission_callback import (
            AutoApproveCallback,
            PromptCallback,
        )
        from coding_agent.agent.permissions import PermissionManager
        from coding_agent.config import Settings
        from coding_agent.llm.client import LLMClient
        from coding_agent.session.manager import SessionManager

        settings = Settings()
        provider = settings.llm_provider

        # Main LLM client
        if provider == "openrouter":
            api_keys = settings.get_openrouter_api_keys()
            model = settings.openrouter_model
        elif provider == "cerebras":
            api_keys = settings.get_cerebras_api_keys()
            model = settings.cerebras_model
        elif provider == "zenmux":
            api_keys = settings.get_zenmux_api_keys()
            model = settings.zenmux_model
        elif provider == "omniroute":
            api_keys = settings.get_omniroute_api_keys()
            model = settings.omniroute_model
        else:
            api_keys = settings.get_api_keys()
            model = settings.llm_model

        self._model_name = model
        self._provider_name = provider

        llm_client = LLMClient(model=model, api_keys=api_keys, provider=provider)

        # Summary LLM client
        summary_provider, summary_model = settings.get_summary_model()
        if summary_model != model or summary_provider != provider:
            if summary_provider == "openrouter":
                summary_keys = settings.get_openrouter_api_keys()
            elif summary_provider == "cerebras":
                summary_keys = settings.get_cerebras_api_keys()
            elif summary_provider == "zenmux":
                summary_keys = settings.get_zenmux_api_keys()
            elif summary_provider == "omniroute":
                summary_keys = settings.get_omniroute_api_keys()
            else:
                summary_keys = settings.get_api_keys()
            summary_client = LLMClient(
                model=summary_model, api_keys=summary_keys, provider=summary_provider
            )
        else:
            summary_client = None

        # Permission callback
        if self.permission == "auto":
            perm_callback = AutoApproveCallback()
        elif self.permission == "deny":
            perm_callback = None
        else:
            perm_callback = PromptCallback()

        permissions = PermissionManager()
        context = ContextManager(max_tokens=settings.max_tokens)

        # Session persistence + memory
        session_mgr = SessionManager(settings.get_db_path())
        await session_mgr.initialize()
        memory_mgr = MemoryManager(
            session_mgr,
            max_memories=settings.max_memories,
            prune_threshold=settings.memory_prune_threshold,
        )

        self._agent = AgentLoop(
            llm_client=llm_client,
            permission_manager=permissions,
            context_manager=context,
            workspace=self.workspace,
            max_iterations=settings.max_iterations,
            permission_callback=perm_callback,
            summary_llm_client=summary_client,
            memory_manager=memory_mgr,
            session_manager=session_mgr,
            max_cost=settings.max_cost_per_session,
            max_time=settings.max_time_per_task,
            agent_timeout_per_iteration=settings.agent_timeout_per_iteration,
        )

        # Update status bar
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_stats(model=f"{model} ({provider})")

        # Update subtitle
        self.sub_title = f"{model} \u2502 {self.workspace.name}"

    @work
    async def _process_input(self, user_input: str) -> None:
        """Process user input on the main event loop.

        Runs on the main event loop (not a thread) so that shared resources
        like the httpx AsyncClient and aiosqlite connection — which are
        created on the main loop — remain usable across calls.
        """
        if self._agent is None:
            self._show_error("Agent not initialized")
            return

        self._processing = True
        self._set_input_enabled(False)
        self._start_thinking()

        try:
            from coding_agent.agent.events import EventType

            self._iteration = 0
            self._prompt_tokens = 0
            self._completion_tokens = 0

            async for event in self._agent.process_input(user_input):
                if event.type == EventType.TEXT:
                    self._handle_text(str(event.data))

                elif event.type == EventType.LOOP_START:
                    self._iteration += 1
                    self._update_status()

                elif event.type == EventType.TOOL_START:
                    self._stop_thinking()
                    data = event.data if isinstance(event.data, dict) else {}
                    name = data.get("name", "?")
                    args = data.get("args", "")
                    self._handle_tool_start(name, str(args))

                elif event.type == EventType.TOOL_RESULT:
                    data = event.data if isinstance(event.data, dict) else {}
                    result = data.get("result", "")
                    success = True
                    if hasattr(result, "success"):
                        success = result.success
                        result = result.output or result.error or ""
                    self._handle_tool_result(str(result), success)

                elif event.type == EventType.USAGE:
                    data = event.data if isinstance(event.data, dict) else {}
                    self._prompt_tokens += int(data.get("prompt_tokens", 0))
                    self._completion_tokens += int(data.get("completion_tokens", 0))
                    self._update_status()

                elif event.type == EventType.ERROR:
                    data = event.data if isinstance(event.data, dict) else {}
                    err = data.get("error", str(event.data))
                    self._show_error(str(err))

                elif event.type == EventType.MAX_TOKENS_RECOVERY:
                    self._show_system("Max tokens recovery triggered", "warning")

                elif event.type == EventType.REACTIVE_COMPACT:
                    self._show_system(
                        "Context overflow recovery triggered",
                        "warning",
                    )

                elif event.type == EventType.MICRO_COMPACT:
                    data = event.data if isinstance(event.data, dict) else {}
                    compacted = data.get("compacted", 0)
                    remaining = data.get("remaining_messages", 0)
                    self._show_system(
                        f"Micro-compact: {compacted} old results cleared ({remaining} messages remain)",
                        "warning",
                    )

                elif event.type == EventType.UNDO_PUSH:
                    data = event.data if isinstance(event.data, dict) else {}
                    file_path = data.get("file_path", "")
                    tool_name = data.get("tool_name", "")
                    self._show_system(
                        f"Undoable: {tool_name} on {file_path}",
                        "info",
                    )
                    self._update_toolbar_undo()

                elif event.type == EventType.SIBLING_ABORT:
                    data = event.data if isinstance(event.data, dict) else {}
                    tool_name = data.get("tool_name", "?")
                    self._show_system(
                        f"Sibling abort: {tool_name} cancelled (sibling failed)",
                        "warning",
                    )

                elif event.type == EventType.HOOK_BLOCK:
                    data = event.data if isinstance(event.data, dict) else {}
                    tool_name = data.get("tool_name", "?")
                    reason = data.get("reason", "Hook blocked this action")
                    self._show_system(
                        f"Hook blocked: {tool_name} — {reason}",
                        "warning",
                    )

                elif event.type == EventType.HOOK_OUTPUT:
                    data = event.data if isinstance(event.data, dict) else {}
                    hook_event = data.get("event", "?")
                    tool_name = data.get("tool_name", "?")
                    output = data.get("output", "")
                    self._show_system(
                        f"Hook [{hook_event}] {tool_name}: {output}",
                        "info",
                    )

                elif event.type == EventType.STUCK_DETECTED:
                    data = event.data if isinstance(event.data, dict) else {}
                    msg = data.get("message", "")
                    strategy = data.get("strategy", "")
                    self._show_system(
                        f"Stuck detected: {msg} (strategy: {strategy})",
                        "warning",
                    )

                elif event.type == EventType.CONTEXT_HEALTH:
                    data = event.data if isinstance(event.data, dict) else {}
                    ratio = data.get("usage_ratio", 0)
                    self._update_context_pct(ratio)

                elif event.type == EventType.DONE:
                    pass

            # Update final stats
            if self._agent:
                usage = self._agent.llm_client.total_usage
                if usage.estimated_cost > 0:
                    self._cost = usage.estimated_cost
                elif self._agent._accumulated_cost > 0:
                    self._cost = self._agent._accumulated_cost

            self._update_status()

        except Exception as exc:
            self._show_error(f"Error: {exc}")
        finally:
            self._processing = False
            self._stop_thinking()
            self._set_input_enabled(True)
            self._finish_response()

    def _start_thinking(self) -> None:
        """Show thinking indicator."""
        if self._thinking is None:
            self._thinking = ThinkingIndicator()
            chat_view = self.query_one("#chat-view")
            chat_view.mount(self._thinking)
            chat_view.scroll_end(animate=False)

    def _stop_thinking(self) -> None:
        """Remove thinking indicator."""
        if self._thinking:
            self._thinking.remove()
            self._thinking = None

    def _handle_text(self, token: str) -> None:
        """Handle a text token from the assistant."""
        self._stop_thinking()

        if self._current_assistant is None:
            self._current_assistant = AssistantMessage()
            chat_view = self.query_one("#chat-view")
            chat_view.mount(self._current_assistant)
            chat_view.scroll_end(animate=False)

        self._current_assistant.append(token)
        self._current_assistant.refresh()
        chat_view = self.query_one("#chat-view")
        chat_view.scroll_end(animate=False)

    def _handle_tool_start(self, name: str, args: str) -> None:
        """Handle a tool call starting."""
        # Finalize any current assistant message
        self._current_assistant = None

        self._current_tool = ToolCallBlock(name=name, args=args)
        chat_view = self.query_one("#chat-view")
        chat_view.mount(self._current_tool)
        chat_view.scroll_end(animate=False)

    def _handle_tool_result(self, result: str, success: bool) -> None:
        """Handle a tool call result."""
        if self._current_tool:
            self._current_tool.set_result(result, success)
            self._current_tool.refresh()
            self._current_tool = None

    def _show_error(self, message: str) -> None:
        """Show an error message."""
        chat_view = self.query_one("#chat-view")
        chat_view.mount(SystemMessage(message, level="error"))
        chat_view.scroll_end(animate=False)

    def _show_system(self, message: str, level: str = "info") -> None:
        """Show a system message."""
        chat_view = self.query_one("#chat-view")
        chat_view.mount(SystemMessage(message, level=level))
        chat_view.scroll_end(animate=False)

    def _update_toolbar_undo(self) -> None:
        """Update the toolbar with undo/redo state."""
        from coding_agent.tools.undo import get_undo_manager
        manager = get_undo_manager()
        if manager:
            toolbar = self.query_one("#toolbar", Toolbar)
            toolbar.update_undo_state(
                can_undo=manager.can_undo,
                can_redo=manager.can_redo,
                undo_count=manager.undo_count,
                redo_count=manager.redo_count,
            )

    def _update_status(self) -> None:
        """Update the status bar."""
        status_bar = self.query_one("#status-bar", StatusBar)
        total_tokens = self._prompt_tokens + self._completion_tokens
        status_bar.update_stats(
            tokens=total_tokens,
            cost=self._cost,
            iteration=self._iteration,
        )

    def _update_context_pct(self, ratio: float) -> None:
        """Update context usage percentage."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_stats(context_pct=ratio)

    def _set_input_enabled(self, enabled: bool) -> None:
        """Enable or disable the input widget."""
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = not enabled

    def _finish_response(self) -> None:
        """Finish the current response."""
        self._current_assistant = None
        self._current_tool = None

    @on(Input.Submitted)
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        if self._processing or not event.value.strip():
            return

        user_input = event.value.strip()
        event.input.clear()

        # Handle slash commands before sending to agent
        if user_input.startswith("/"):
            handled = await self._handle_command(user_input)
            if handled:
                return

        # Add user message to chat
        chat_view = self.query_one("#chat-view")
        await chat_view.mount(UserMessage(user_input))
        chat_view.scroll_end(animate=False)

        # Process input
        self._process_input(user_input)

    def action_interrupt(self) -> None:
        """Interrupt the current agent turn."""
        if self._processing:
            for worker in self.workers:
                if worker.is_running:
                    worker.cancel()
            self._processing = False
            self._stop_thinking()
            self._set_input_enabled(True)
            self._show_system("Interrupted", "warning")

    def action_clear(self) -> None:
        """Clear the chat view."""
        chat_view = self.query_one("#chat-view")
        chat_view.remove_children()
        self._current_assistant = None
        self._current_tool = None
        self._thinking = None
        # Re-add welcome message
        chat_view.mount(
            SystemMessage(
                "Chat cleared. Type a message to continue.",
                level="info",
            )
        )

    async def _handle_command(self, command: str) -> bool:
        """Handle slash commands. Returns True if command was handled."""
        from coding_agent.agent.permissions import PermissionMode

        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/permissions":
            if not self._agent:
                self._show_system("Agent not initialized", "error")
                return True

            pm = self._agent.permissions

            if not arg:
                # Show current mode
                mode = pm.mode.value
                self._show_system(f"Current permission mode: {mode}", "info")
                return True

            # Try to parse mode
            mode_map = {m.value: m for m in PermissionMode}
            # Also accept short aliases
            mode_map[">"] = PermissionMode.DEFAULT
            mode_map[">>"] = PermissionMode.ACCEPT_EDITS
            mode_map["?"] = PermissionMode.PLAN
            mode_map["!"] = PermissionMode.BYPASS

            mode = mode_map.get(arg)
            if mode is None:
                valid = ", ".join(m.value for m in PermissionMode)
                self._show_system(
                    f"Unknown mode: {arg}. Options: {valid}",
                    "error",
                )
                return True

            warning = pm.set_mode(mode, str(self.workspace))
            self._show_system(f"Permission mode: {mode.value}", "info")
            if warning:
                self._show_system(warning, "warning")
            logger.info("permission_mode_changed", mode=mode.value, workspace=str(self.workspace))
            return True

        # Unknown command — don't handle, let it pass through to agent
        return False

    async def action_undo(self) -> None:
        """Undo the last file mutation."""
        if self._processing:
            return

        import asyncio
        from coding_agent.tools.undo import get_undo_manager
        from coding_agent.agent.undo import UndoManager

        manager = get_undo_manager()
        if not manager:
            self._show_system("Undo system not available.", "error")
            return

        def _do_undo() -> tuple[bool, str]:
            entry = manager.undo()
            if entry is None:
                return False, ""
            try:
                UndoManager.apply_entry(entry, redo=False)
                desc = entry.description or f"{entry.tool_name} on {entry.file_path}"
                return True, desc
            except Exception as e:
                manager.push(entry)
                raise

        try:
            success, desc = await asyncio.to_thread(_do_undo)
            if success:
                self._show_system(f"Undone: {desc}", "warning")
                self._update_toolbar_undo()
            else:
                self._show_system("Nothing to undo.", "info")
        except Exception as e:
            self._show_system(f"Undo failed: {e}", "error")

    async def action_redo(self) -> None:
        """Redo the last undone mutation."""
        if self._processing:
            return

        import asyncio
        from coding_agent.tools.undo import get_undo_manager
        from coding_agent.agent.undo import UndoManager

        manager = get_undo_manager()
        if not manager:
            self._show_system("Undo system not available.", "error")
            return

        def _do_redo() -> tuple[bool, str]:
            entry = manager.redo()
            if entry is None:
                return False, ""
            try:
                UndoManager.apply_entry(entry, redo=True)
                desc = entry.description or f"{entry.tool_name} on {entry.file_path}"
                return True, desc
            except Exception as e:
                manager.push(entry)
                raise

        try:
            success, desc = await asyncio.to_thread(_do_redo)
            if success:
                self._show_system(f"Redone: {desc}", "warning")
                self._update_toolbar_undo()
            else:
                self._show_system("Nothing to redo.", "info")
        except Exception as e:
            self._show_system(f"Redo failed: {e}", "error")


def run_repl(
    workspace: Path = Path("."),
    permission: str = "auto",
) -> None:
    """Run the interactive REPL."""
    app = CodingAgentREPL(workspace=workspace, permission=permission)
    app.run()
