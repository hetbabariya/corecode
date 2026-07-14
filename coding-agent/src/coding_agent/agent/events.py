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
    PERMISSION_REQUEST = "perm_req"
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


@dataclass
class AgentEvent:
    """A single event from the agent loop."""

    type: EventType
    data: Any = None
