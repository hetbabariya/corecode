"""Types for the hooks system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HookEvent(Enum):
    """Lifecycle events that can trigger hooks."""

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"


@dataclass
class HookConfig:
    """Configuration for a single hook command."""

    matcher: str  # regex pattern matching tool names
    command: str  # shell command to execute
    timeout_ms: int = 10_000
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class HookResult:
    """Result of running a hook command."""

    event: HookEvent
    tool_name: str
    exit_code: int
    stdout: str
    stderr: str
    blocked: bool = False  # True if exit code == 2
