"""Event types for agent-to-TUI communication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EventType(Enum):
    """Types of events the agent loop can emit."""

    TEXT = "text"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    LOOP_START = "loop_start"
    PERMISSION_REQUEST = "perm_req"
    PERMISSION_CHECK = "perm_check"
    PERMISSION_RESPONSE = "perm_res"
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"
    MAX_ITERATIONS = "max_iter"
    BUDGET_EXCEEDED = "budget_exceeded"
    PLAN_UPDATE = "plan_update"
    VERIFICATION = "verification"
    STUCK_DETECTED = "stuck_detected"
    ASK_USER = "ask_user"
    CONTEXT_HEALTH = "context_health"
    REFLECTION = "reflection"
    MAX_TOKENS_RECOVERY = "max_tokens_recovery"
    REACTIVE_COMPACT = "reactive_compact"
    MICRO_COMPACT = "micro_compact"
    UNDO_PUSH = "undo_push"
    SIBLING_ABORT = "sibling_abort"
    HOOK_BLOCK = "hook_block"
    HOOK_OUTPUT = "hook_output"
    PERMISSION_MODE_CHANGED = "perm_mode_changed"
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_TOOL_START = "subagent_tool_start"
    SUBAGENT_TOOL_RESULT = "subagent_tool_result"
    SUBAGENT_COMPLETED = "subagent_completed"
    PLAN_MODE_ENTERED = "plan_mode_entered"
    PLAN_MODE_EXITED = "plan_mode_exited"


@dataclass
class AgentEvent:
    """A single event from the agent loop."""

    type: EventType
    data: Any = None
    error: str | None = None
    depth: int = 0
