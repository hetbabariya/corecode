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
from coding_agent.tui.widgets import (
    AssistantMessage,
    StatusBar,
    SystemMessage,
    ThinkingIndicator,
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
        yield Input(placeholder="Ask anything...", id="input", password=False)
        yield StatusBar(id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the agent after mount."""
        self.register_theme(create_nord_theme())
        self.theme = "coding-agent"
        await self._init_agent()
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
        )

        # Update status bar
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_stats(model=f"{model} ({provider})")

        # Update subtitle
        self.sub_title = f"{model} \u2502 {self.workspace.name}"

    @work(thread=True)
    async def _process_input(self, user_input: str) -> None:
        """Process user input in a background thread."""
        if self._agent is None:
            self.call_from_thread(self._show_error, "Agent not initialized")
            return

        self._processing = True
        self.call_from_thread(self._set_input_enabled, False)
        self.call_from_thread(self._start_thinking)

        try:
            from coding_agent.agent.events import EventType

            self._iteration = 0
            self._prompt_tokens = 0
            self._completion_tokens = 0

            async for event in self._agent.process_input(user_input):
                if event.type == EventType.TEXT:
                    self.call_from_thread(self._handle_text, str(event.data))

                elif event.type == EventType.LOOP_START:
                    self._iteration += 1
                    self.call_from_thread(self._update_status)

                elif event.type == EventType.TOOL_START:
                    self.call_from_thread(self._stop_thinking)
                    data = event.data if isinstance(event.data, dict) else {}
                    name = data.get("name", "?")
                    args = data.get("args", "")
                    self.call_from_thread(self._handle_tool_start, name, str(args))

                elif event.type == EventType.TOOL_RESULT:
                    data = event.data if isinstance(event.data, dict) else {}
                    result = data.get("result", "")
                    success = True
                    if hasattr(result, "success"):
                        success = result.success
                        result = result.output or result.error or ""
                    self.call_from_thread(
                        self._handle_tool_result, str(result), success
                    )

                elif event.type == EventType.USAGE:
                    data = event.data if isinstance(event.data, dict) else {}
                    self._prompt_tokens += int(data.get("prompt_tokens", 0))
                    self._completion_tokens += int(data.get("completion_tokens", 0))
                    self.call_from_thread(self._update_status)

                elif event.type == EventType.ERROR:
                    data = event.data if isinstance(event.data, dict) else {}
                    err = data.get("error", str(event.data))
                    self.call_from_thread(self._show_error, str(err))

                elif event.type == EventType.MAX_TOKENS_RECOVERY:
                    self.call_from_thread(
                        self._show_system, "Max tokens recovery triggered", "warning"
                    )

                elif event.type == EventType.REACTIVE_COMPACT:
                    self.call_from_thread(
                        self._show_system,
                        "Context overflow recovery triggered",
                        "warning",
                    )

                elif event.type == EventType.CONTEXT_HEALTH:
                    data = event.data if isinstance(event.data, dict) else {}
                    ratio = data.get("usage_ratio", 0)
                    self.call_from_thread(self._update_context_pct, ratio)

                elif event.type == EventType.DONE:
                    pass

            # Update final stats
            if self._agent:
                usage = self._agent.llm_client.total_usage
                if usage.estimated_cost > 0:
                    self._cost = usage.estimated_cost
                elif self._agent._accumulated_cost > 0:
                    self._cost = self._agent._accumulated_cost

            self.call_from_thread(self._update_status)

        except Exception as exc:
            self.call_from_thread(self._show_error, f"Error: {exc}")
        finally:
            self._processing = False
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._set_input_enabled, True)
            self.call_from_thread(self._finish_response)

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


def run_repl(
    workspace: Path = Path("."),
    permission: str = "auto",
) -> None:
    """Run the interactive REPL."""
    app = CodingAgentREPL(workspace=workspace, permission=permission)
    app.run()
