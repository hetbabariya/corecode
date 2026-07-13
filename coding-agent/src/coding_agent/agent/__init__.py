"""Agent core — loop, context, permissions, events."""

from coding_agent.agent.context import ContextManager
from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.loop import AgentLoop
from coding_agent.agent.permission_callback import (
    AutoApproveCallback,
    PromptCallback,
    QueueCallback,
)
from coding_agent.agent.permissions import Permission, PermissionManager, TrustLevel
from coding_agent.agent.system_prompt import build_system_prompt

__all__ = [
    "AgentEvent",
    "AgentLoop",
    "AutoApproveCallback",
    "ContextManager",
    "EventType",
    "Permission",
    "PermissionManager",
    "PromptCallback",
    "QueueCallback",
    "TrustLevel",
    "build_system_prompt",
]
