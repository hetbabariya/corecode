"""Error recovery and stuck detection.

Tracks tool call history, categorizes errors, detects stuck patterns,
and provides structured error context for the LLM.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from coding_agent.logging import logger


class ErrorCategory(str, Enum):
    """Classification of errors for recovery strategy."""

    TRANSIENT = "transient"  # rate limit, timeout → retry
    PERMANENT = "permanent"  # file not found, permission denied → alternative
    LOGIC = "logic"  # wrong file, wrong approach → replan
    UNKNOWN = "unknown"


class RetryStrategy(str, Enum):
    """Suggested recovery strategy."""

    RETRY = "retry"  # same tool, wait and retry
    ALTERNATIVE = "alternative"  # try different approach
    REPLAN = "replan"  # step back, create new plan
    ASK_USER = "ask_user"  # ask user for help


@dataclass
class ToolCallRecord:
    """Record of a single tool call for tracking."""

    name: str
    args_hash: str
    success: bool
    error: str = ""
    timestamp: float = 0.0


class ErrorTracker:
    """Tracks tool call history and detects stuck patterns.

    Usage::

        tracker = ErrorTracker()

        # After each tool execution
        tracker.record_tool_call("edit_file", {"path": "x.py"}, success=False, error="File not found")

        # Check if stuck
        if tracker.is_stuck():
            message = tracker.get_stuck_message()
            strategy = tracker.suggest_strategy()
    """

    def __init__(self, window_size: int = 10, stuck_threshold: int = 3) -> None:
        self._history: deque[ToolCallRecord] = deque(maxlen=window_size)
        self._stuck_threshold = stuck_threshold
        self._consecutive_errors: dict[str, int] = {}
        self._stuck_count: int = 0
        self._ask_user_count: int = 0

    def record_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        *,
        success: bool = True,
        error: str = "",
        timestamp: float = 0.0,
    ) -> None:
        """Record a tool call for tracking.

        Parameters
        ----------
        name:
            Tool name (e.g. ``"edit_file"``).
        args:
            Tool arguments.
        success:
            Whether the call succeeded.
        error:
            Error message if failed.
        timestamp:
            Optional timestamp for ordering.
        """
        args_hash = self._hash_args(args)
        record = ToolCallRecord(
            name=name,
            args_hash=args_hash,
            success=success,
            error=error,
            timestamp=timestamp,
        )
        self._history.append(record)

        # Track consecutive errors per tool
        if not success:
            self._consecutive_errors[name] = self._consecutive_errors.get(name, 0) + 1
            logger.debug(
                "error_recorded",
                tool=name,
                error=error[:200],
                consecutive=self._consecutive_errors[name],
            )
        else:
            was_failing = self._consecutive_errors.pop(name, None)
            if was_failing:
                logger.debug("error_resolved", tool=name)

    def is_stuck(self) -> bool:
        """Return True if the agent appears stuck.

        Stuck patterns:
        - Same tool + same args hash called N+ times (stuck_threshold)
        - Same tool + same error N+ times
        """
        if len(self._history) < self._stuck_threshold:
            return False

        # Check for repeated identical calls
        recent = list(self._history)[-self._stuck_threshold:]
        if len(recent) >= self._stuck_threshold:
            # All same tool + same args
            if all(r.name == recent[0].name and r.args_hash == recent[0].args_hash for r in recent):
                return True
            # All same tool + same error
            if (
                all(not r.success for r in recent)
                and all(r.name == recent[0].name for r in recent)
                and len(set(r.error for r in recent)) == 1
                and recent[0].error
            ):
                return True

        return False

    def _increment_stuck_count(self) -> None:
        """Increment the stuck counter (called by suggest_strategy and get_stuck_message)."""
        self._stuck_count += 1

    def get_stuck_message(self) -> str:
        """Return a message to inject when stuck."""
        if not self._history:
            return ""

        last = self._history[-1]
        self._stuck_count += 1

        if self._stuck_count >= 3:
            return (
                f"You have tried {last.name} multiple times with the same approach and failed each time. "
                "Stop and try a completely different approach. "
                "Consider reading different files, searching for patterns, or asking the user for help."
            )

        return (
            f"Tool '{last.name}' has failed repeatedly with the same error. "
            "Try a different approach instead of retrying the same operation."
        )

    def suggest_strategy(self) -> RetryStrategy:
        """Suggest a recovery strategy based on error history."""
        if not self._history:
            return RetryStrategy.ALTERNATIVE

        last = self._history[-1]

        # Stuck detection → escalate
        if self.is_stuck():
            self._increment_stuck_count()

        # Too many stuck cycles → ask user
        if self._stuck_count >= 3:
            self._ask_user_count += 1
            logger.warning("error_stuck_ask_user", tool=last.name, stuck_count=self._stuck_count)
            return RetryStrategy.ASK_USER

        # Stuck but not yet at ask_user threshold → replan
        if self._stuck_count >= 2:
            logger.warning("error_stuck_replan", tool=last.name, stuck_count=self._stuck_count)
            return RetryStrategy.REPLAN

        # Classify the error
        category = self.categorize_error(last.error)
        strategy = {
            ErrorCategory.TRANSIENT: RetryStrategy.RETRY,
            ErrorCategory.PERMANENT: RetryStrategy.ALTERNATIVE,
            ErrorCategory.LOGIC: RetryStrategy.REPLAN,
        }.get(category, RetryStrategy.ALTERNATIVE)

        logger.debug(
            "error_strategy_suggested",
            tool=last.name,
            category=category.value,
            strategy=strategy.value,
        )
        return strategy

    def categorize_error(self, error: str) -> ErrorCategory:
        """Classify an error message into a category."""
        error_lower = error.lower()

        # Logic errors (wrong approach) — check before permanent
        if any(kw in error_lower for kw in (
            "not found in", "appears", "multiple times",
            "match", "no such", "invalid",
        )):
            return ErrorCategory.LOGIC

        # Transient errors
        if any(kw in error_lower for kw in ("rate limit", "429", "timeout", "timed out", "try again")):
            return ErrorCategory.TRANSIENT

        # Permanent errors
        if any(kw in error_lower for kw in (
            "not found", "no such file", "permission denied",
            "access denied", "does not exist", "is a directory",
        )):
            return ErrorCategory.PERMANENT

        return ErrorCategory.UNKNOWN

    def get_history(self) -> list[ToolCallRecord]:
        """Return the current history window."""
        return list(self._history)

    def get_consecutive_errors(self) -> dict[str, int]:
        """Return current consecutive error counts per tool."""
        return dict(self._consecutive_errors)

    def get_summary(self) -> str:
        """Return a human-readable summary of recent activity."""
        if not self._history:
            return "No tool calls recorded."

        lines: list[str] = []
        lines.append(f"Recent tool calls ({len(self._history)}):")
        for record in self._history:
            status = "ok" if record.success else f"FAILED: {record.error[:80]}"
            lines.append(f"  - {record.name}: {status}")

        if self._consecutive_errors:
            lines.append("\nConsecutive errors:")
            for tool, count in self._consecutive_errors.items():
                lines.append(f"  - {tool}: {count}")

        return "\n".join(lines)

    def reset(self) -> None:
        """Clear all tracking state."""
        self._history.clear()
        self._consecutive_errors.clear()
        self._stuck_count = 0
        self._ask_user_count = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_args(args: dict[str, Any]) -> str:
        """Hash tool arguments for comparison."""
        try:
            raw = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            raw = str(args)
        return hashlib.md5(raw.encode()).hexdigest()[:12]
