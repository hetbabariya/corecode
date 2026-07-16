"""Smart context selection for the agent loop.

Provides prioritized context assembly that gives the LLM the most relevant
information for each iteration, including recent messages, tool results,
error context, and verification feedback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from coding_agent.agent.context import ContextManager, ConversationMessage
from coding_agent.agent.error_recovery import ErrorTracker
from coding_agent.llm.tokens import count_tokens


@dataclass
class ContextSlice:
    """A slice of context with metadata for prioritization."""

    content: str
    priority: int  # higher = more important
    source: str  # "recent", "tool_result", "error", "verification", "plan"
    token_estimate: int = 0


class SmartContextEngine:
    """Selects and prioritizes context for each LLM iteration.

    Instead of sending the full conversation history, this engine
    selects the most relevant context slices based on what's happening
    in the current iteration.

    Usage::

        engine = SmartContextEngine(context_manager, error_tracker)
        slices = engine.select_context(
            pending_tool_calls=[...],
            verification_results=[...],
            plan_text="...",
        )
        # Feed selected slices into the context or system prompt
    """

    def __init__(
        self,
        context: ContextManager,
        error_tracker: ErrorTracker | None = None,
        max_context_tokens: int = 80_000,
    ) -> None:
        self._context = context
        self._error_tracker = error_tracker
        self._max_context_tokens = max_context_tokens
        self._last_tool_results: list[dict[str, Any]] = []
        self._verification_results: list[dict[str, Any]] = []
        self._pending_tool_calls: list[dict[str, Any]] = []

    def record_tool_result(self, name: str, result: str, success: bool) -> None:
        """Record a tool result for context selection."""
        self._last_tool_results.append({
            "name": name,
            "result": result[:500],  # truncate for storage
            "success": success,
        })
        # Keep only last 10 tool results
        if len(self._last_tool_results) > 10:
            self._last_tool_results = self._last_tool_results[-10:]

    def record_verification(self, check_type: str, passed: bool, message: str) -> None:
        """Record a verification result for context selection."""
        self._verification_results.append({
            "check_type": check_type,
            "passed": passed,
            "message": message[:300],
        })
        # Keep only last 5 verification results
        if len(self._verification_results) > 5:
            self._verification_results = self._verification_results[-5:]

    def set_pending_tool_calls(self, tool_calls: list[dict[str, Any]]) -> None:
        """Set the tool calls that are about to be executed."""
        self._pending_tool_calls = tool_calls

    def select_context(
        self,
        *,
        include_error_context: bool = True,
        include_verification: bool = True,
        include_plan: bool = False,
        plan_text: str = "",
    ) -> list[ContextSlice]:
        """Select and prioritize context slices for the current iteration.

        Returns a list of ContextSlice objects sorted by priority (highest first).
        The caller can then feed these into the context or system prompt.
        """
        slices: list[ContextSlice] = []
        token_budget = self._max_context_tokens
        excluded: list[str] = []

        # 1. Recent messages (always include)
        recent = self._get_recent_messages(count=6)
        if recent:
            content = self._format_messages(recent)
            est = self._estimate_tokens(content)
            slices.append(ContextSlice(
                content=content,
                priority=100,
                source="recent",
                token_estimate=est,
            ))
            token_budget -= est

        # 2. Recent tool results (high priority)
        if self._last_tool_results:
            content = self._format_tool_results(self._last_tool_results[-3:])
            est = self._estimate_tokens(content)
            if est < token_budget:
                slices.append(ContextSlice(
                    content=content,
                    priority=90,
                    source="tool_result",
                    token_estimate=est,
                ))
                token_budget -= est
            else:
                excluded.append("tool_result")

        # 3. Error context (if errors exist)
        if include_error_context and self._error_tracker:
            history = self._error_tracker.get_history()
            if history and any(not r.success for r in history[-10:]):
                content = self._format_error_context()
                est = self._estimate_tokens(content)
                if est < token_budget:
                    slices.append(ContextSlice(
                        content=content,
                        priority=85,
                        source="error",
                        token_estimate=est,
                    ))
                    token_budget -= est
                else:
                    excluded.append("error")

        # 4. Verification feedback
        if include_verification and self._verification_results:
            # Show recent verification results (failures prioritized)
            recent = self._verification_results[-5:]
            failures = [v for v in recent if not v["passed"]]
            content = self._format_verification(failures if failures else recent)
            est = self._estimate_tokens(content)
            if est < token_budget:
                slices.append(ContextSlice(
                    content=content,
                    priority=80,
                    source="verification",
                    token_estimate=est,
                ))
                token_budget -= est
            else:
                excluded.append("verification")

        # 5. Plan context (if enabled)
        if include_plan and plan_text:
            est = self._estimate_tokens(plan_text)
            if est < token_budget:
                slices.append(ContextSlice(
                    content=plan_text,
                    priority=70,
                    source="plan",
                    token_estimate=est,
                ))
                token_budget -= est
            else:
                excluded.append("plan")

        # Sort by priority descending
        slices.sort(key=lambda s: s.priority, reverse=True)

        return slices

    def format_selected_context(self, slices: list[ContextSlice]) -> str:
        """Format selected context slices into a single string."""
        if not slices:
            return ""

        parts: list[str] = []
        for s in slices:
            parts.append(f"[{s.source.upper()}]\n{s.content}")
        return "\n\n".join(parts)

    def get_total_tokens(self, slices: list[ContextSlice]) -> int:
        """Get total token estimate for selected slices."""
        return sum(s.token_estimate for s in slices)

    def clear_history(self) -> None:
        """Clear recorded tool results and verification results."""
        self._last_tool_results.clear()
        self._verification_results.clear()
        self._pending_tool_calls.clear()

    # ------------------------------------------------------------------
    # Internal formatting methods
    # ------------------------------------------------------------------

    def _get_recent_messages(self, count: int = 6) -> list[ConversationMessage]:
        """Get the most recent messages from context."""
        messages = self._context.messages
        return messages[-count:] if len(messages) > count else messages

    def _format_messages(self, messages: list[ConversationMessage]) -> str:
        """Format messages into a readable string."""
        parts: list[str] = []
        for msg in messages:
            if msg.role == "system":
                continue
            prefix = msg.role.upper()
            content = msg.content[:500] if len(msg.content) > 500 else msg.content
            parts.append(f"{prefix}: {content}")
        return "\n".join(parts)

    def _format_tool_results(self, results: list[dict[str, Any]]) -> str:
        """Format recent tool results."""
        parts: list[str] = []
        for r in results:
            status = "OK" if r["success"] else "FAILED"
            parts.append(f"Tool {r['name']} [{status}]: {r['result']}")
        return "\n".join(parts)

    def _format_error_context(self) -> str:
        """Format error context from the error tracker."""
        if not self._error_tracker:
            return ""

        summary = self._error_tracker.get_summary()
        consecutive = self._error_tracker.get_consecutive_errors()

        parts = ["Recent errors:"]
        parts.append(summary)

        if consecutive:
            parts.append("\nConsecutive errors per tool:")
            for tool, count in consecutive.items():
                parts.append(f"  - {tool}: {count} consecutive failures")

        strategy = self._error_tracker.suggest_strategy()
        parts.append(f"\nSuggested recovery: {strategy.value}")

        return "\n".join(parts)

    def _format_verification(self, failures: list[dict[str, Any]]) -> str:
        """Format verification failure results."""
        parts = ["Verification failures detected:"]
        for f in failures:
            parts.append(f"  [{f['check_type']}] {f['message']}")
        parts.append("\nPlease fix these issues before continuing.")
        return "\n".join(parts)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count using tiktoken (falls back to len//4)."""
        return count_tokens(text)
