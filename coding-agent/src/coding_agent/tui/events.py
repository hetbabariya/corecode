"""Agent event dispatch for the TUI.

Replaces the monolithic if/elif chain in the streaming loop with a
dispatch table. Each EventType maps to a handler method on the app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from coding_agent.agent.events import EventType

if TYPE_CHECKING:
    from coding_agent.agent.events import AgentEvent
    from coding_agent.tui.repl import ChatScreen


# Maps EventType → handler method name on ChatScreen
# All handlers receive (self, event: AgentEvent) and extract data from event.data
_DISPATCH: dict[EventType, str] = {
    EventType.TEXT: "_on_text",
    EventType.TOOL_START: "_on_tool_start",
    EventType.TOOL_RESULT: "_on_tool_result",
    EventType.LOOP_START: "_on_loop_start",
    EventType.USAGE: "_on_usage",
    EventType.ERROR: "_on_error",
    EventType.MAX_TOKENS_RECOVERY: "_on_max_tokens_recovery",
    EventType.REACTIVE_COMPACT: "_on_reactive_compact",
    EventType.MICRO_COMPACT: "_on_micro_compact",
    EventType.UNDO_PUSH: "_on_undo_push",
    EventType.SIBLING_ABORT: "_on_sibling_abort",
    EventType.HOOK_BLOCK: "_on_hook_block",
    EventType.HOOK_OUTPUT: "_on_hook_output",
    EventType.STUCK_DETECTED: "_on_stuck_detected",
    EventType.SUBAGENT_STARTED: "_on_subagent_start",
    EventType.SUBAGENT_TOOL_START: "_on_subagent_tool",
    EventType.SUBAGENT_COMPLETED: "_on_subagent_complete",
    EventType.PLAN_MODE_ENTERED: "_on_plan_mode_change",
    EventType.PLAN_MODE_EXITED: "_on_plan_mode_change",
    EventType.CONTEXT_HEALTH: "_on_context_health",
    EventType.PLAN_UPDATE: "_on_plan_update",
    EventType.VERIFICATION: "_on_verification",
    EventType.BUDGET_EXCEEDED: "_on_budget_exceeded",
    EventType.PERMISSION_REQUEST: "_on_permission_request",
    EventType.PERMISSION_CHECK: "_on_permission_check",
    EventType.REFLECTION: "_on_reflection",
}


async def dispatch(app: ChatScreen, event: AgentEvent) -> None:
    """Dispatch a single agent event to the app's handler."""
    handler_name = _DISPATCH.get(event.type)
    if handler_name is None:
        return
    handler = getattr(app, handler_name, None)
    if handler is None:
        return
    await handler(event)
