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

        Auto-repairs broken tool_call/tool alternation before building.
        """
        self.repair_alternation()
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

        Drops individual tool result messages from the front of the
        conversation.  If dropping a tool result would orphan an
        assistant-with-tool_calls (i.e. it's the last tool result for
        that assistant), the entire assistant + tool group is removed
        together to preserve alternation.

        Use ``repair_alternation()`` after this to fill in any missing
        tool results with placeholders.

        Parameters
        ----------
        count:
            Maximum number of tool result messages to drop.

        Returns
        -------
        int
            Number of messages actually dropped.
        """
        # Collect indices of all tool messages, oldest first
        all_tool_indices: list[int] = []
        for i, msg in enumerate(self.messages):
            if msg.role == "tool":
                all_tool_indices.append(i)

        if not all_tool_indices:
            return 0

        # Determine which tool indices are safe to drop individually.
        # A tool is unsafe if it's the ONLY remaining tool for its assistant.
        safe_indices: list[int] = []
        for idx in all_tool_indices:
            # Find the assistant that produced this tool result
            assistant_idx = idx - 1
            while assistant_idx >= 0 and self.messages[assistant_idx].role == "tool":
                assistant_idx -= 1
            if assistant_idx < 0 or not (
                self.messages[assistant_idx].role == "assistant"
                and self.messages[assistant_idx].tool_calls
            ):
                # Orphaned tool — safe to drop
                safe_indices.append(idx)
                continue

            # Count how many tool messages this assistant has
            total = 0
            j = assistant_idx + 1
            while j < len(self.messages) and self.messages[j].role == "tool":
                total += 1
                j += 1

            # Count how many of those we're keeping (not in safe_indices)
            kept = 0
            for k in range(assistant_idx + 1, j):
                if k != idx and k not in all_tool_indices[:all_tool_indices.index(idx)]:
                    kept += 1

            if kept > 0:
                safe_indices.append(idx)
            else:
                # Last tool for this assistant — drop the whole group
                # This will be handled below
                pass

        # Drop safe individual tool results (oldest first)
        dropped = 0
        for idx in reversed(safe_indices[:count]):
            self.messages.pop(idx)
            dropped += 1

        # If we still have budget, drop complete groups (assistant + all tools)
        if dropped < count:
            # Re-scan for groups where ALL tool results are still present
            groups: list[tuple[int, int]] = []
            i = 0
            while i < len(self.messages):
                msg = self.messages[i]
                if msg.role == "assistant" and msg.tool_calls:
                    start = i
                    i += 1
                    while i < len(self.messages) and self.messages[i].role == "tool":
                        i += 1
                    groups.append((start, i))
                else:
                    i += 1

            still_needed = count - dropped
            for start, end in groups:
                if dropped >= count:
                    break
                size = end - start
                if dropped + size <= count or dropped == 0:
                    del self.messages[start:end]
                    dropped += size

        return dropped

    def compact_old_tool_results(self, keep_recent: int = 10) -> int:
        """Replace old tool results with compact markers.

        This is a lightweight pass that reclaims context space by replacing
        large tool results (file contents, search results) with short markers
        that preserve metadata (tool name, success/failure, line count).

        Parameters
        ----------
        keep_recent:
            Number of recent messages to preserve intact.

        Returns
        -------
        int
            Number of messages compacted.
        """
        if len(self.messages) <= keep_recent:
            return 0

        compacted = 0
        cutoff_index = len(self.messages) - keep_recent

        for i in range(cutoff_index):
            msg = self.messages[i]
            if msg.role == "tool" and len(msg.content) > 500:
                # Build compact marker
                name = msg.name or "tool"
                success = not msg.content.startswith("Error")
                status = "ok" if success else "failed"
                lines = msg.content.count("\n") + 1

                # Extract first line as preview
                first_line = msg.content.split("\n")[0][:80]

                marker = f"[Old tool result: {name} \u2192 {status}, {lines} lines]"
                if first_line:
                    marker += f"\nPreview: {first_line}"

                msg.content = marker
                compacted += 1

        return compacted

    def drop_oldest_messages(self, fraction: float = 0.2) -> int:
        """Drop the oldest messages from the conversation.

        This is the "context window sliding" — a cheaper alternative to
        summarization. Drops the oldest complete alternation groups while
        preserving the system prompt, summary, and project context.

        Never splits an assistant-with-tool_calls from its tool results.

        Parameters
        ----------
        fraction:
            Fraction of messages to drop (0.0–1.0). Default 0.2 drops 20%.

        Returns
        -------
        int
            Number of messages actually dropped.
        """
        if not self.messages:
            return 0

        count = max(1, int(len(self.messages) * fraction))
        count = min(count, len(self.messages) - 1)  # keep at least 1

        if count <= 0:
            return 0

        boundary = self._find_safe_boundary_from_start(
            self.messages, prefer_drop=count,
        )
        if boundary <= 0:
            return 0

        self.messages = self.messages[boundary:]
        return boundary

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

        Keeps the most recent complete alternation groups and folds
        everything else into *summary* (which should be produced by the
        LLM via a separate call).
        """
        if len(self.messages) <= 5:
            return

        boundary = self._find_safe_boundary_from_end(
            self.messages, prefer_keep=5,
        )
        if boundary <= 0:
            return

        recent = self.messages[boundary:]
        old = self.messages[:boundary]

        old_content: list[str] = []
        for msg in old:
            if msg.role in ("user", "assistant"):
                old_content.append(f"{msg.role}: {msg.content[:200]}")

        self._summary = summary or "\n".join(old_content)
        self.messages = recent

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    @staticmethod
    def _find_safe_boundary_from_end(
        messages: list['ConversationMessage'],
        prefer_keep: int = 5,
    ) -> int:
        """Find a safe split such that messages[i:] is a valid conversation tail.

        Walks backward from the prefer_keep boundary to find the first
        non-tool message boundary, ensuring tool results are never orphaned
        from their assistant.

        Parameters
        ----------
        messages:
            The full message list.
        prefer_keep:
            Minimum number of messages to keep at the end.

        Returns
        -------
        int
            Index such that messages[i:] is safe to keep.
        """
        if not messages or len(messages) <= prefer_keep:
            return 0

        start = len(messages) - prefer_keep
        for i in range(start, -1, -1):
            if messages[i].role != "tool":
                return i
        return 0

    @staticmethod
    def _find_safe_boundary_from_start(
        messages: list['ConversationMessage'],
        prefer_drop: int = 1,
    ) -> int:
        """Find a safe split such that messages[:i] can be removed.

        Walks forward to find the last safe boundary at or before
        *prefer_drop*.  Never splits an assistant-with-tool_calls from
        its tool results — complete groups are dropped together or not at all.

        Parameters
        ----------
        messages:
            The full message list.
        prefer_drop:
            Maximum number of messages to drop from the front.

        Returns
        -------
        int
            Index such that messages[:i] can be safely removed.
        """
        if not messages or prefer_drop <= 0:
            return 0

        last_safe = 0
        i = 0
        while i < len(messages) and last_safe < prefer_drop:
            msg = messages[i]
            if msg.role == "tool":
                last_safe = i + 1
                i += 1
            elif msg.role == "assistant" and msg.tool_calls:
                j = i + 1
                while j < len(messages) and messages[j].role == "tool":
                    j += 1
                group_size = j - i
                if last_safe + group_size <= prefer_drop:
                    last_safe = j
                    i = j
                else:
                    break
            else:
                last_safe = i + 1
                i += 1

        return min(last_safe, len(messages))

    def repair_alternation(self) -> int:
        """Repair broken tool_call/tool alternation in the message list.

        Fixes two types of corruption:
        1. **Orphaned tool messages** — a ``tool`` message whose
           ``tool_call_id`` doesn't match any preceding assistant's
           ``tool_calls``. These are removed.
        2. **Missing tool results** — an ``assistant`` message with
           ``tool_calls`` where some of the call IDs have no corresponding
           ``tool`` result right after it.  Placeholder results are
           inserted.

        Called automatically from ``build_messages()``.

        Returns
        -------
        int
            Number of messages repaired (inserted or removed).
        """
        changes = 0

        # Pass 1: Remove orphaned tool messages (no matching assistant)
        i = 0
        while i < len(self.messages):
            msg = self.messages[i]
            if msg.role == "tool":
                has_assistant = False
                for j in range(i - 1, -1, -1):
                    prev = self.messages[j]
                    if prev.role == "assistant" and prev.tool_calls:
                        if msg.tool_call_id and any(
                            tc.get("id") == msg.tool_call_id
                            for tc in prev.tool_calls
                        ):
                            has_assistant = True
                        break
                    elif prev.role != "tool":
                        break
                if not has_assistant:
                    self.messages.pop(i)
                    changes += 1
                    continue
            i += 1

        # Pass 2: Insert placeholder tool results for missing call IDs
        i = 0
        while i < len(self.messages):
            msg = self.messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                expected = {tc["id"] for tc in msg.tool_calls if tc.get("id")}
                found: set[str] = set()
                j = i + 1
                while j < len(self.messages) and self.messages[j].role == "tool":
                    tid = self.messages[j].tool_call_id
                    if tid in expected:
                        found.add(tid)
                    j += 1

                missing = expected - found
                if missing:
                    insert_pos = i + 1
                    for mid in sorted(missing):
                        for tc in msg.tool_calls:
                            if tc.get("id") == mid:
                                fn_name = (
                                    tc.get("function", {}).get("name", "unknown")
                                )
                                placeholder = ConversationMessage(
                                    role="tool",
                                    content=(
                                        f"[Tool result for '{fn_name}'\u2014"
                                        "recovered from context compaction]"
                                    ),
                                    tool_call_id=mid,
                                    name=fn_name,
                                )
                                self.messages.insert(insert_pos, placeholder)
                                insert_pos += 1
                                changes += 1
                                break
                i = j + (len(missing))
            else:
                i += 1

        return changes

    def clear(self) -> None:
        """Clear conversation history (start fresh)."""
        self.messages.clear()
        self._summary = ""
