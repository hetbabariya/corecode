"""Core agent loop — observe, think, act, repeat.

This is the heart of the coding agent.  It wires together the LLM client,
tool registry, permission system, and context manager into an agentic loop
that streams responses and executes tool calls.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from coding_agent.agent.context import ContextManager
from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.permissions import PermissionManager
from coding_agent.agent.system_prompt import build_system_prompt
from coding_agent.llm.client import LLMClient
from coding_agent.llm.streaming import StreamEventType
from coding_agent.logging import logger
from coding_agent.tools.registry import tool_registry


class PermissionCallback(Protocol):
    """Signature for permission callbacks."""

    async def __call__(
        self, tool_name: str, args: dict[str, Any], permission_level: str
    ) -> bool: ...


class AgentLoop:
    """Core agentic loop — observe, think, act, repeat.

    Usage::

        llm = LLMClient(model="gemini-2.5-flash", api_key="...")
        permissions = PermissionManager(level=Permission.WRITE)
        context = ContextManager(max_tokens=100_000)

        agent = AgentLoop(
            llm_client=llm,
            permission_manager=permissions,
            context_manager=context,
            workspace=Path("."),
            max_iterations=20,
        )

        async for event in agent.process_input("Fix the bug in main.py"):
            if event.type == EventType.TEXT:
                print(event.data, end="", flush=True)
            elif event.type == EventType.DONE:
                print("\\n[Done]")
    """

    def __init__(
        self,
        llm_client: LLMClient,
        permission_manager: PermissionManager,
        context_manager: ContextManager,
        workspace: Path,
        max_iterations: int = 20,
        permission_callback: PermissionCallback | None = None,
        summary_llm_client: LLMClient | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.permissions = permission_manager
        self.context = context_manager
        self.workspace = workspace
        self.max_iterations = max_iterations
        self.permission_callback = permission_callback
        self.summary_llm_client = summary_llm_client

        # Build and inject the system prompt
        self.context.system_prompt = build_system_prompt(
            model=llm_client.model,
            provider=llm_client.provider,
            workspace=workspace,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def process_input(
        self,
        user_input: str,
    ) -> AsyncIterator[AgentEvent]:
        """Process user input and yield events for the TUI / REPL.

        The loop runs until one of:
        * The LLM produces a response with **no** tool calls (task complete).
        * The iteration counter reaches *max_iterations*.
        """
        self.context.add_user_message(user_input)

        for iteration in range(self.max_iterations):
            logger.info("agent_iteration", iteration=iteration + 1)

            # --- Build messages for LLM ---
            messages = self.context.build_messages()
            tools = tool_registry.get_schemas()

            # --- Stream LLM response ---
            tool_calls: list[dict[str, Any]] = []
            text_parts: list[str] = []

            async for event in self.llm_client.stream(messages, tools=tools):
                if event.type == StreamEventType.TEXT:
                    text_parts.append(str(event.data))
                    yield AgentEvent(type=EventType.TEXT, data=event.data)

                elif event.type == StreamEventType.TOOL_CALL:
                    tool_calls.append(event.data)  # type: ignore[arg-type]

                elif event.type == StreamEventType.USAGE:
                    yield AgentEvent(type=EventType.USAGE, data=event.data)

                elif event.type == StreamEventType.DONE:
                    break

            # --- Store assistant turn in context ---
            full_text = "".join(text_parts)
            if full_text or tool_calls:
                self.context.add_assistant_message(
                    content=full_text,
                    tool_calls=tool_calls if tool_calls else None,
                )

            # --- No tool calls → done ---
            if not tool_calls:
                yield AgentEvent(type=EventType.DONE)
                return

            # --- Execute each tool call ---
            for tc in tool_calls:
                fn: dict[str, Any] = tc.get("function", {})
                tool_name: str = fn.get("name", "")
                raw_args: str = fn.get("arguments", "{}")
                tc_id: str = tc.get("id", "")

                try:
                    tool_args: dict[str, Any] = json.loads(raw_args)
                except json.JSONDecodeError:
                    tool_args = {}

                # Permission check
                try:
                    tool_obj = tool_registry.get(tool_name)
                    perm_level: str = tool_obj.permission_level
                except KeyError:
                    perm_level = "read"

                if not self.permissions.check(tool_name, perm_level):
                    yield AgentEvent(
                        type=EventType.PERMISSION_REQUEST,
                        data={
                            "tool_name": tool_name,
                            "args": tool_args,
                            "permission_level": perm_level,
                        },
                    )

                    if self.permission_callback is not None:
                        approved = await self.permission_callback(
                            tool_name, tool_args, perm_level
                        )
                    else:
                        approved = True

                    if not approved:
                        # Feed denial back to LLM as tool result
                        self.context.add_tool_result(
                            tool_call_id=tc_id,
                            name=tool_name,
                            result=(
                                "Permission denied by user. "
                                "Try a different approach that doesn't "
                                "require this operation."
                            ),
                        )
                        yield AgentEvent(
                            type=EventType.TOOL_RESULT,
                            data={
                                "name": tool_name,
                                "result": "Permission denied by user.",
                            },
                        )
                        continue

                    self.permissions.approve_tool(tool_name)

                # Execute
                yield AgentEvent(
                    type=EventType.TOOL_START,
                    data={"name": tool_name, "args": tool_args},
                )

                result = await tool_registry.execute_from_llm(tc)

                yield AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={"name": tool_name, "result": result},
                )

                self.context.add_tool_result(
                    tool_call_id=tc_id,
                    name=tool_name,
                    result=result.output,
                )

            # --- Check context budget ---
            if self.context.needs_summarization():
                logger.info(
                    "agent_context_summarization_needed",
                    tokens=self.context.estimate_tokens(),
                    max=self.context.max_tokens,
                )
                await self._summarize_context()

        # Iteration budget exhausted
        yield AgentEvent(type=EventType.MAX_ITERATIONS)

    # ------------------------------------------------------------------
    # Summarization
    # ------------------------------------------------------------------

    async def _summarize_context(self) -> None:
        """Generate a summary of old messages using the LLM."""
        old_text = self.context.format_old_messages()
        if not old_text:
            return

        client = self.summary_llm_client or self.llm_client

        summary_messages = [
            {
                "role": "system",
                "content": (
                    "You are a summarization assistant. "
                    "Summarize the following conversation concisely. "
                    "Focus on: what the user asked, what was found, "
                    "what was changed. Max 500 tokens."
                ),
            },
            {
                "role": "user",
                "content": f"Summarize this conversation:\n\n{old_text}",
            },
        ]

        try:
            response = await client.complete(summary_messages)
            self.context.summarize_old_messages(response.content)
            logger.info(
                "agent_context_summarized",
                summary_length=len(response.content),
            )
        except Exception as e:
            logger.error("agent_summarize_failed", error=str(e))

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear conversation state for a fresh session."""
        self.context.clear()
        self.permissions.reset()
