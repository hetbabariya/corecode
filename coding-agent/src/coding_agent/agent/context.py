"""Context window management for the coding agent.

Manages the conversation history that gets sent to the LLM, including
token-budget tracking and automatic summarisation when the context
window fills up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from coding_agent.llm.tokens import count_tokens


@dataclass
class ConversationMessage:
    """A single message in the conversation."""

    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to OpenAI-format dict."""
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        return msg


class ContextManager:
    """Manages conversation history and context window limits.

    Usage::

        ctx = ContextManager(max_tokens=100_000)
        ctx.system_prompt = build_system_prompt(...)

        ctx.add_user_message("Fix the bug in main.py")

        # In agent loop:
        messages = ctx.build_messages()  # list[dict] for LLM

        # After LLM responds:
        ctx.add_assistant_message(response.content, tool_calls=response.tool_calls)

        # After tool execution:
        ctx.add_tool_result(tool_call_id, tool_name, result.output)
    """

    def __init__(self, max_tokens: int = 100_000) -> None:
        self.max_tokens = max_tokens
        self.system_prompt: str = ""
        self.project_context: str = ""
        self.messages: list[ConversationMessage] = []
        self._summary: str = ""
        self._context_summary: str = ""

    # ------------------------------------------------------------------
    # Building the message list for the LLM
    # ------------------------------------------------------------------

    def build_messages(self) -> list[dict[str, Any]]:
        """Build the full message list for the LLM.

        Structure:
        1. System prompt (always first)
        2. Project context (if set separately from system prompt)
        3. Summary of older messages (if summarisation happened)
        4. Current conversation messages
        """
        result: list[dict[str, Any]] = []

        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})

        if self._context_summary:
            result.append(
                {
                    "role": "system",
                    "content": f"[Context Summary]\n{self._context_summary}",
                }
            )

        if self.project_context:
            result.append({"role": "system", "content": self.project_context})

        if self._summary:
            result.append(
                {
                    "role": "system",
                    "content": f"Summary of previous conversation:\n{self._summary}",
                }
            )

        for msg in self.messages:
            result.append(msg.to_dict())

        return result

    # ------------------------------------------------------------------
    # Adding messages
    # ------------------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        """Append a user message."""
        self.messages.append(ConversationMessage(role="user", content=content))

    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Append an assistant message (may include tool-call requests)."""
        self.messages.append(
            ConversationMessage(
                role="assistant",
                content=content,
                tool_calls=tool_calls,
            )
        )


    def add_tool_result(
        self,
        tool_call_id: str,
        name: str,
        result: str,
    ) -> None:
        """Append a tool result linked to a prior tool call."""
        self.messages.append(
            ConversationMessage(
                role="tool",
                content=result,
                tool_call_id=tool_call_id,
                name=name,
            )
        )

    def drop_oldest_tool_results(self, count: int = 2) -> int:
        """Drop the oldest tool result messages.

        This is the "overflow flush" — a cheap way to reduce context size
        by removing old tool results while preserving the conversation flow.

        Parameters
        ----------
        count:
            Maximum number of tool result messages to drop.

        Returns
        -------
        int
            Number of messages actually dropped.
        """
        # Find indices of tool result messages (oldest first)
        tool_indices: list[int] = []
        for i, msg in enumerate(self.messages):
            if msg.role == "tool":
                tool_indices.append(i)

        # Drop oldest ones (up to count)
        dropped = 0
        for idx in reversed(tool_indices[:count]):  # Reverse to preserve indices
            self.messages.pop(idx)
            dropped += 1

        return dropped

    def set_context_summary(self, summary: str) -> None:
        """Set prioritized context summary from SmartContextEngine.

        This is injected as a system message after the system prompt
        so the LLM sees prioritized context (errors, verifications, etc.).
        """
        self._context_summary = summary

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------

    def estimate_tokens(self) -> int:
        """Estimate total tokens in the full message list sent to the LLM.

        Includes system prompt, project context, summary, and all messages.
        This matches what build_messages() actually sends.
        """
        total = 0
        if self.system_prompt:
            total += count_tokens(self.system_prompt)
        if self._context_summary:
            total += count_tokens(self._context_summary)
        if self.project_context:
            total += count_tokens(self.project_context)
        if self._summary:
            total += count_tokens(self._summary)
        for msg in self.messages:
            total += count_tokens(msg.content)
            if msg.tool_calls:
                total += count_tokens(json.dumps(msg.tool_calls))
        return total

    def needs_summarization(self) -> bool:
        """Return ``True`` when estimated tokens exceed 80 % of the budget."""
        return self.estimate_tokens() > int(self.max_tokens * 0.8)

    # ------------------------------------------------------------------
    # Summarisation
    # ------------------------------------------------------------------

    def format_old_messages(self) -> str:
        """Format messages that will be summarized (all except last 5).

        Returns a readable string suitable for feeding to the LLM as
        summarization input.
        """
        if len(self.messages) <= 5:
            return ""

        old = self.messages[:-5]
        parts: list[str] = []
        for msg in old:
            if msg.role == "system":
                continue
            content = msg.content[:500] if msg.content else ""
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    fn = tc.get("function", {})
                    content += f"\n  [tool_call: {fn.get('name', '?')}]"
            if msg.role == "tool":
                name = msg.name or "tool"
                content = f"  [tool_result: {name}] {content[:200]}"
            parts.append(f"{msg.role}: {content}")
        return "\n\n".join(parts)

    def summarize_old_messages(self, summary: str) -> None:
        """Replace older messages with a compact summary.

        Keeps the most recent 5 messages and folds everything else into
        *summary* (which should be produced by the LLM via a separate call).
        """
        if len(self.messages) <= 5:
            return

        recent = self.messages[-5:]
        old = self.messages[:-5]

        old_content: list[str] = []
        for msg in old:
            if msg.role in ("user", "assistant"):
                old_content.append(f"{msg.role}: {msg.content[:200]}")

        self._summary = summary or "\n".join(old_content)
        self.messages = recent

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear conversation history (start fresh)."""
        self.messages.clear()
        self._summary = ""
