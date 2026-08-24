"""Interactive REPL for the Coding Agent using Textual."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Input
from textual.worker import get_current_worker

from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.commands import CommandContext, get_registry
from coding_agent.logging import logger
from coding_agent.tui.events import dispatch
from coding_agent.tui.theme import create_nord_theme
from coding_agent.tui.widgets import (
    AssistantMessage,
    DiffViewer,
    PlanPanel,
    StatusBar,
    StatusPanel,
    SubAgentToolCallBlock,
    SystemMessage,
    ThinkingIndicator,
    ToolCallBlock,
    UserMessage,
)


class ChatScreen(Screen[str | None]):
    """Interactive chat screen for the Coding Agent."""

    TITLE = "Coding Agent"
    CSS_PATH = "repl.tcss"

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
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.workspace = workspace
        self.permission = permission
        self._resume_session_id = session_id
        self._agent: Any = None
        self._current_assistant: AssistantMessage | None = None
        self._current_tool: ToolCallBlock | None = None
        self._current_subagent: SubAgentToolCallBlock | None = None
        self._thinking: ThinkingIndicator | None = None
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._cost: float = 0.0
        self._iteration: int = 0
        self._processing: bool = False
        self._model_name: str = ""
        self._provider_name: str = ""
        self._model_registry: Any = None
        self._plan_mode: bool = False
        self._plan_panel: PlanPanel | None = None
        self._status_panel: StatusPanel | None = None
        self._interrupted: bool = False

    async def on_unmount(self) -> None:
        """Graceful shutdown — cancel workers, flush session, close DB."""
        for worker in self.workers:
            if worker.is_running:
                worker.cancel()
        if self._agent:
            try:
                if hasattr(self._agent, "session_manager") and self._agent.session_manager:
                    await self._agent.session_manager.close()
                if hasattr(self._agent, "memory_manager") and self._agent.memory_manager:
                    await self._agent.memory_manager.close()
            except Exception as exc:
                logger.warning("shutdown_error", error=str(exc))

    def compose(self) -> ComposeResult:
        yield Header(icon="\u2593")
        with VerticalScroll(id="chat-view"):
            yield SystemMessage(
                "Welcome! Type a message to start.",
                level="info",
            )
        yield Footer()
        yield StatusBar(id="status-bar")
        yield Input(placeholder="\u276f Ask anything...", id="input", password=False)

    async def on_mount(self) -> None:
        """Initialize the agent after mount."""
        await self._init_agent_with_retry()
        self._load_custom_commands()
        if self._resume_session_id:
            await self._restore_session(self._resume_session_id)
        self.query_one("#input").focus()

    async def action_quit(self) -> None:
        """Dismiss the screen, returning to the browser or exiting."""
        self.dismiss(None)

    async def _init_agent_with_retry(self) -> None:
        """Initialize the agent loop with retry logic."""
        import asyncio

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                await self._init_agent()
                return
            except Exception as exc:
                last_error = exc
                logger.warning("agent_init_retry", attempt=attempt, error=str(exc))
                if attempt < 3:
                    self._show_system(
                        f"Agent init failed (attempt {attempt}/3), retrying...",
                        "warning",
                    )
                    await asyncio.sleep(2)
        self._show_system(f"Agent init failed after 3 attempts: {last_error}", "error")

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

        # Initialize model registry
        await self._init_model_registry()

    def _load_custom_commands(self) -> None:
        """Load custom commands from .coding-agent/commands/ directories."""
        from coding_agent.commands import get_registry

        registry = get_registry()
        global_commands = Path.home() / ".coding-agent" / "commands"
        local_commands = self.workspace / ".coding-agent" / "commands"
        count = registry.load_custom_commands(global_commands, local_commands)
        if count:
            logger.info("custom_commands_loaded", count=count)

    async def _init_model_registry(self) -> None:
        """Initialize the dynamic model registry."""
        from coding_agent.config import Settings
        from coding_agent.llm.models import ModelRegistry

        settings = Settings()
        self._model_registry = ModelRegistry(settings.get_models_config_path())
        await self._model_registry.load()

    async def _restore_session(self, session_id: str) -> None:
        """Load and display messages from a previous session."""
        if not self._agent or not self._agent.session_manager:
            self._show_system("Session persistence not available.", "error")
            return

        messages = await self._agent.session_manager.load_session(session_id)
        if not messages:
            self._show_system(f"Session {session_id} has no messages.", "warning")
            return

        # Rebuild context from loaded messages
        for msg in messages:
            if msg.role == "user":
                self._agent.context.add_user_message(msg.content)
            elif msg.role == "assistant":
                self._agent.context.add_assistant_message(msg.content, msg.tool_calls)
            elif msg.role == "tool" and msg.tool_call_id:
                self._agent.context.add_tool_result(
                    msg.tool_call_id, msg.name or "", msg.content,
                )

        # Point agent at the same session so new messages are appended
        self._agent.session_id = session_id

        # Restore undo stack for this session
        self._agent.undo_manager.init_session(session_id)

        await self._display_session_messages(messages)

        # Show resume summary
        info = await self._agent.session_manager.get_session(session_id)
        if info:
            date = info.created_at[:10] if info.created_at else "?"
            self._show_system(
                f"Resumed session {session_id} from {date}. {len(messages)} messages loaded.",
                "info",
            )

    async def _display_session_messages(self, messages: list) -> None:
        """Render loaded messages into the chat view."""
        chat_view = self.query_one("#chat-view")
        for msg in messages:
            if msg.role == "user":
                await chat_view.mount(UserMessage(msg.content))
            elif msg.role == "assistant":
                if msg.content:
                    widget = AssistantMessage()
                    widget.update(msg.content)
                    await chat_view.mount(widget)
                elif msg.tool_calls:
                    tool_names = [
                        tc.get("function", {}).get("name", "?")
                        for tc in msg.tool_calls
                    ]
                    widget = AssistantMessage()
                    widget.update("  \u21b3 Called: " + ", ".join(tool_names))
                    await chat_view.mount(widget)
            elif msg.role == "tool" and msg.name:
                preview = (msg.content or "")[:300]
                block = ToolCallBlock(name=msg.name, args="")
                block._result = preview
                block._status = "success"
                block.add_class("-success")
                await chat_view.mount(block)
        chat_view.scroll_end(animate=False)

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
            self._iteration = 0
            self._prompt_tokens = 0
            self._completion_tokens = 0
            worker = get_current_worker()

            async for event in self._agent.process_input(user_input):
                if worker.is_cancelled:
                    break
                await dispatch(self, event)

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
            was_interrupted = self._interrupted
            self._interrupted = False
            self._processing = False
            self._stop_thinking()
            self._set_input_enabled(True)
            self._finish_response()
            if not was_interrupted:
                self._update_status()

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

    def _update_status(self) -> None:
        """Update the status bar."""
        status_bar = self.query_one("#status-bar", StatusBar)
        total_tokens = self._prompt_tokens + self._completion_tokens
        status_bar.update_stats(
            tokens=total_tokens,
            cost=self._cost,
            iteration=self._iteration,
            model=f"{self._model_name} ({self._provider_name})" if self._model_name else "",
            plan_mode=self._plan_mode,
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
        self._current_subagent = None

    def _update_toolbar_undo(self) -> None:
        """Update toolbar undo/redo button state."""
        from coding_agent.tools.undo import get_undo_manager

        manager = get_undo_manager()
        if manager:
            try:
                toolbar = self.query_one("Toolbar")
                toolbar.update_undo_state(
                    can_undo=manager.can_undo,
                    can_redo=manager.can_redo,
                    undo_count=manager.undo_count,
                    redo_count=manager.redo_count,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Event dispatch handlers
    # ------------------------------------------------------------------

    async def _on_text(self, event: AgentEvent) -> None:
        self._handle_text(str(event.data))

    async def _on_loop_start(self, event: AgentEvent) -> None:
        self._iteration += 1
        self._update_status()

    async def _on_tool_start(self, event: AgentEvent) -> None:
        self._stop_thinking()
        data = event.data if isinstance(event.data, dict) else {}
        name = data.get("name", "?")
        args = data.get("args", "")
        self._handle_tool_start(name, str(args))

    async def _on_tool_result(self, event: AgentEvent) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        result = data.get("result", "")
        success = True
        if hasattr(result, "success"):
            success = result.success
            result = result.output or result.error or ""
        self._handle_tool_result(str(result), success)
        # Show diff viewer for file edit tools
        name = data.get("name", "")
        if name in ("edit_file", "write_file", "apply_patch") and success:
            file_path = self._extract_tool_file_path(data)
            if file_path:
                diff_text = self._try_get_diff(file_path, str(result))
                if diff_text:
                    self._show_diff(file_path, diff_text)

    async def _on_usage(self, event: AgentEvent) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        self._prompt_tokens += int(data.get("prompt_tokens", 0))
        self._completion_tokens += int(data.get("completion_tokens", 0))
        self._update_status()

    async def _on_error(self, event: AgentEvent) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        err = data.get("error", str(event.data))
        self._show_error(str(err))

    async def _on_max_tokens_recovery(self, event: AgentEvent) -> None:
        self._show_system("context recovery", "warning")

    async def _on_reactive_compact(self, event: AgentEvent) -> None:
        self._show_system("context compacted", "warning")

    async def _on_micro_compact(self, event: AgentEvent) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        compacted = data.get("compacted", 0)
        remaining = data.get("remaining_messages", 0)
        self._show_system(
            f"compacted {compacted} messages ({remaining} remain)",
            "info",
        )

    async def _on_undo_push(self, event: AgentEvent) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        file_path = data.get("file_path", "")
        tool_name = data.get("tool_name", "")
        self._update_toolbar_undo()

    async def _on_sibling_abort(self, event: AgentEvent) -> None:
        pass

    async def _on_hook_block(self, event: AgentEvent) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        tool_name = data.get("tool_name", "?")
        self._show_system(f"hook blocked: {tool_name}", "warning")

    async def _on_hook_output(self, event: AgentEvent) -> None:
        pass

    async def _on_stuck_detected(self, event: AgentEvent) -> None:
        pass

    async def _on_subagent_start(self, event: AgentEvent) -> None:
        self._stop_thinking()
        data = event.data if isinstance(event.data, dict) else {}
        prompt = data.get("prompt", "")
        depth = getattr(event, "depth", 1)
        self._current_subagent = SubAgentToolCallBlock(prompt=prompt, depth=depth)
        chat_view = self.query_one("#chat-view")
        await chat_view.mount(self._current_subagent)
        chat_view.scroll_end(animate=False)

    async def _on_subagent_tool(self, event: AgentEvent) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        name = data.get("name", "?")
        args = str(data.get("args", ""))
        if self._current_subagent:
            self._current_subagent.add_tool_call(name, args)
            self._current_subagent.refresh()

    async def _on_subagent_complete(self, event: AgentEvent) -> None:
        if self._current_subagent:
            self._current_subagent.set_completed()
            self._current_subagent.refresh()
            self._current_subagent = None

    async def _on_plan_mode_change(self, event: AgentEvent) -> None:
        self._plan_mode = event.type == EventType.PLAN_MODE_ENTERED
        self._update_status()

    async def _on_context_health(self, event: AgentEvent) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        ratio = data.get("usage_ratio", 0)
        self._update_context_pct(ratio)

    async def _on_plan_update(self, event: AgentEvent) -> None:
        """Handle plan update events — refresh the plan panel."""
        data = event.data if isinstance(event.data, dict) else {}
        plan_data = data.get("plan")
        if plan_data and isinstance(plan_data, dict):
            goal = plan_data.get("goal", "")
            steps = plan_data.get("steps", [])
            if self._plan_panel:
                self._plan_panel.update_plan(goal, steps)
                self._plan_panel.refresh()
            else:
                self._plan_panel = PlanPanel()
                self._plan_panel.update_plan(goal, steps)
                chat_view = self.query_one("#chat-view")
                await chat_view.mount(self._plan_panel)
                chat_view.scroll_end(animate=False)

    async def _on_verification(self, event: AgentEvent) -> None:
        """Handle verification events — show diff if checks failed."""
        data = event.data if isinstance(event.data, dict) else {}
        checks = data.get("checks", [])
        failed = [c for c in checks if not c.get("passed", True)]
        if failed:
            for check in failed:
                tool = check.get("tool", "?")
                self._show_system(f"verify failed: {tool}", "warning")

    async def _on_budget_exceeded(self, event: AgentEvent) -> None:
        self._show_system("budget exceeded", "error")

    async def _on_permission_request(self, event: AgentEvent) -> None:
        pass

    async def _on_permission_check(self, event: AgentEvent) -> None:
        pass

    async def _on_reflection(self, event: AgentEvent) -> None:
        pass

    # ------------------------------------------------------------------
    # Diff viewer helpers
    # ------------------------------------------------------------------

    def _extract_tool_file_path(self, data: dict) -> str:
        """Extract file path from a tool call result data."""
        result = data.get("result", "")
        if hasattr(result, "metadata") and result.metadata:
            return result.metadata.get("file_path", "")
        args = data.get("args", {})
        if isinstance(args, dict):
            return args.get("path", args.get("file_path", ""))
        return ""

    def _try_get_diff(self, file_path: str, result_text: str) -> str:
        """Try to get a git diff for the given file."""
        try:
            import subprocess
            workspace = self.workspace
            proc = subprocess.run(
                ["git", "diff", "--", file_path],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout
        except Exception:
            pass
        return ""

    def _show_diff(self, file_path: str, diff_text: str) -> None:
        """Mount a diff viewer in the chat view."""
        viewer = DiffViewer(file_path=file_path, diff=diff_text)
        chat_view = self.query_one("#chat-view")
        chat_view.mount(viewer)
        chat_view.scroll_end(animate=False)

    @on(Input.Submitted)
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        raw = event.value
        if self._processing or not raw.strip():
            return

        # Input validation
        if len(raw) > 100_000:
            self._show_system("Input too long (max 100,000 characters)", "error")
            return

        # Check for binary content
        if raw and isinstance(raw, str):
            binary_chars = sum(1 for c in raw if ord(c) < 32 and c not in "\n\r\t")
            if binary_chars > len(raw) * 0.1:
                self._show_system("Input appears to contain binary data", "error")
                return

        user_input = raw.strip()
        event.input.clear()

        # Handle slash commands before sending to agent
        if user_input.startswith("/"):
            handled = await self._handle_command(user_input)
            if handled:
                return

        if self._agent is None:
            self._show_system("Agent not initialized. Cannot process input.", "error")
            return

        # Add user message to chat
        chat_view = self.query_one("#chat-view")
        await chat_view.mount(UserMessage(user_input))
        chat_view.scroll_end(animate=False)

        # Process input
        self._process_input(user_input)

    def action_interrupt(self) -> None:
        """Interrupt the current agent turn.

        Only cancels the worker and shows feedback.  All UI state cleanup
        (``_processing``, input enable, thinking indicator) is deferred to
        ``_process_input``'s ``finally`` block so it runs *after* the
        ``CancelledError`` propagates — avoiding the race condition where
        premature cleanup lets a new worker start while the old one is
        still winding down.
        """
        if self._processing:
            self._interrupted = True
            for worker in self.workers:
                if worker.is_running:
                    worker.cancel()
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
        """Handle slash commands via the registry. Returns True if handled."""
        registry = get_registry()
        ctx = CommandContext(agent=self._agent, workspace=self.workspace, repl=self)
        result = await registry.execute(command, ctx)
        if result is None:
            return False
        self._show_system(result, "info")
        return True

    async def action_undo(self) -> None:
        """Undo the last file mutation."""
        if self._processing:
            self._show_system("Cannot undo while processing. Press Ctrl+C to interrupt first.", "warning")
            return

        import asyncio

        from coding_agent.agent.undo import UndoManager
        from coding_agent.tools.undo import get_undo_manager

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
            except Exception:
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
            self._show_system("Cannot redo while processing. Press Ctrl+C to interrupt first.", "warning")
            return

        import asyncio

        from coding_agent.agent.undo import UndoManager
        from coding_agent.tools.undo import get_undo_manager

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
            except Exception:
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


class _ChatScreenApp(App[None]):
    """Standalone ChatScreen App (backward compat wrapper)."""

    CSS_PATH = "repl.tcss"

    def __init__(
        self,
        workspace: Path = Path("."),
        permission: str = "auto",
        session_id: str | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.permission = permission
        self._resume_session_id = session_id

    def on_mount(self) -> None:
        self.register_theme(create_nord_theme())
        self.theme = "coding-agent"

        def _on_chat_done(value: str | None) -> None:
            self.exit(value)

        self.push_screen(
            ChatScreen(
                workspace=self.workspace,
                permission=self.permission,
                session_id=self._resume_session_id,
            ),
            _on_chat_done,
        )


def run_repl(
    workspace: Path = Path("."),
    permission: str = "auto",
    session_id: str | None = None,
) -> None:
    """Run the interactive REPL."""
    app = _ChatScreenApp(
        workspace=workspace, permission=permission, session_id=session_id,
    )
    app.run()
