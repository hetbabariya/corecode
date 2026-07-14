"""Core agent loop — observe, think, act, repeat.

This is the heart of the coding agent.  It wires together the LLM client,
tool registry, permission system, and context manager into an agentic loop
that streams responses and executes tool calls.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from coding_agent.agent.context import ContextManager
from coding_agent.agent.context_limits import (
    truncate_search_results,
    truncate_tool_result,
)
from coding_agent.agent.error_recovery import ErrorTracker
from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.permissions import PermissionManager
from coding_agent.agent.planner import PlanManager
from coding_agent.agent.system_prompt import build_system_prompt
from coding_agent.agent.verifier import PostEditVerifier
from coding_agent.agent.workspace_index import WorkspaceIndex
from coding_agent.llm.client import LLMClient
from coding_agent.llm.streaming import StreamEventType
from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool_registry


class PermissionCallback(Protocol):
    """Signature for permission callbacks."""

    async def __call__(
        self, tool_name: str, args: dict[str, Any], permission_level: str
    ) -> bool: ...


# Tools that are safe to run in parallel (read-only operations)
_PARALLEL_SAFE_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "list_files",
    "search_content",
    "search_files",
    "git_status",
    "git_diff",
    "git_log",
    "create_plan",
    "update_plan",
    "refresh_index",
})


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
        max_cost: float = 5.0,
        max_time: int = 300,
        verify_after_edit: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self.permissions = permission_manager
        self.context = context_manager
        self.workspace = workspace
        self.max_iterations = max_iterations
        self.permission_callback = permission_callback
        self.summary_llm_client = summary_llm_client
        self.max_cost = max_cost
        self.max_time = max_time
        self._start_time: float = 0.0
        self._accumulated_cost: float = 0.0

        # Planning system
        self.plan_manager = PlanManager()
        from coding_agent.tools.planning import set_plan_manager

        set_plan_manager(self.plan_manager)

        # Workspace index
        self.workspace_index = WorkspaceIndex()
        self.workspace_index.scan(workspace)
        from coding_agent.tools.workspace import set_workspace_index

        set_workspace_index(self.workspace_index)

        # Post-edit verification
        self.verifier = PostEditVerifier(workspace=workspace)
        self.verify_after_edit = verify_after_edit

        # Error recovery and stuck detection
        self.error_tracker = ErrorTracker()

        # Build and inject the system prompt
        self.context.system_prompt = build_system_prompt(
            model=llm_client.model,
            provider=llm_client.provider,
            workspace=workspace,
            workspace_index_summary=self.workspace_index.to_summary(),
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
        self._start_time = time.monotonic()
        self._accumulated_cost = 0.0

        logger.debug("user_input", input=user_input[:200], length=len(user_input))

        for iteration in range(self.max_iterations):
            logger.info("agent_iteration", iteration=iteration + 1)

            # --- Check budget ---
            elapsed = time.monotonic() - self._start_time
            if elapsed > self.max_time:
                yield AgentEvent(
                    type=EventType.BUDGET_EXCEEDED,
                    data={"reason": "time", "elapsed": elapsed, "limit": self.max_time},
                )
                return
            if self._accumulated_cost >= self.max_cost:
                yield AgentEvent(
                    type=EventType.BUDGET_EXCEEDED,
                    data={
                        "reason": "cost",
                        "cost": self._accumulated_cost,
                        "limit": self.max_cost,
                    },
                )
                return

            # --- Inject plan state into system prompt ---
            if self.plan_manager.has_plan:
                plan_prompt = self.plan_manager.to_prompt()
                self.context.system_prompt = build_system_prompt(
                    model=self.llm_client.model,
                    provider=self.llm_client.provider,
                    workspace=self.workspace,
                    plan_prompt=plan_prompt,
                    workspace_index_summary=self.workspace_index.to_summary(),
                )

                # Check if replanning is needed
                if self.plan_manager.needs_replan():
                    yield AgentEvent(
                        type=EventType.PLAN_UPDATE,
                        data={
                            "action": "replan_needed",
                            "plan": self.plan_manager.plan.to_dict() if self.plan_manager.plan else None,
                        },
                    )

            # --- Check for stuck state ---
            consecutive = self.error_tracker.get_consecutive_errors()
            if consecutive:
                logger.debug("consecutive_errors", errors=consecutive)

            if self.error_tracker.is_stuck():
                stuck_msg = self.error_tracker.get_stuck_message()
                strategy = self.error_tracker.suggest_strategy()
                logger.warning("agent_stuck_detected", message=stuck_msg, strategy=strategy.value)

                if strategy.value == "ask_user":
                    yield AgentEvent(
                        type=EventType.ASK_USER,
                        data={"message": stuck_msg},
                    )
                    return
                else:
                    yield AgentEvent(
                        type=EventType.STUCK_DETECTED,
                        data={"message": stuck_msg, "strategy": strategy.value},
                    )

            # --- Build messages for LLM ---
            messages = self.context.build_messages()
            tools = tool_registry.get_schemas()

            # Log context state
            msg_count = len(messages)
            ctx_tokens = self.context.estimate_tokens()
            logger.debug(
                "context_state",
                messages=msg_count,
                tokens=ctx_tokens,
                iteration=iteration + 1,
                cost=f"${self._accumulated_cost:.4f}",
            )

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
                    # Track accumulated cost
                    usage_data: dict[str, Any] = event.data  # type: ignore[assignment]
                    if isinstance(usage_data, dict):
                        from coding_agent.llm.tokens import TokenUsage

                        usage = TokenUsage(
                            prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
                            completion_tokens=int(usage_data.get("completion_tokens", 0)),
                            model=self.llm_client.model,
                        )
                        self._accumulated_cost += usage.estimated_cost

                elif event.type == StreamEventType.DONE:
                    break

            # --- Store assistant turn in context ---
            full_text = "".join(text_parts)
            if full_text or tool_calls:
                self.context.add_assistant_message(
                    content=full_text,
                    tool_calls=tool_calls if tool_calls else None,
                )

            # Log LLM response
            logger.debug(
                "llm_response",
                text_length=len(full_text),
                text_preview=full_text[:300] if full_text else "",
                tool_call_count=len(tool_calls),
            )

            # --- No tool calls → done ---
            if not tool_calls:
                yield AgentEvent(type=EventType.DONE)
                return

            # --- Execute tool calls (parallel for read-only, sequential for writes) ---
            # Emit TOOL_START for all tools first
            parsed_calls: list[dict[str, Any]] = []
            for tc in tool_calls:
                fn: dict[str, Any] = tc.get("function", {})
                tool_name: str = fn.get("name", "")
                raw_args: str = fn.get("arguments", "{}")
                tc_id: str = tc.get("id", "")
                try:
                    tool_args: dict[str, Any] = json.loads(raw_args)
                except json.JSONDecodeError:
                    tool_args = {}
                parsed_calls.append({
                    "tc": tc,
                    "name": tool_name,
                    "args": tool_args,
                    "tc_id": tc_id,
                })

            # Emit all TOOL_START events
            for pc in parsed_calls:
                yield AgentEvent(
                    type=EventType.TOOL_START,
                    data={"name": pc["name"], "args": pc["args"]},
                )

            # Group into parallel-safe batch and sequential calls
            parallel_batch: list[dict[str, Any]] = []
            sequential_calls: list[dict[str, Any]] = []
            for pc in parsed_calls:
                if pc["name"] in _PARALLEL_SAFE_TOOLS:
                    parallel_batch.append(pc)
                else:
                    sequential_calls.append(pc)

            logger.debug(
                "tool_execution_plan",
                parallel=[pc["name"] for pc in parallel_batch],
                sequential=[pc["name"] for pc in sequential_calls],
            )

            # Execute parallel-safe tools concurrently
            if parallel_batch:
                for pc in parallel_batch:
                    logger.debug(
                        "tool_call_args",
                        name=pc["name"],
                        args=pc["args"],
                        tc_id=pc["tc_id"],
                    )

                async def _exec_one(pc: dict[str, Any]) -> tuple[dict[str, Any], ToolResult]:
                    return pc, await tool_registry.execute_from_llm(pc["tc"])

                results = await asyncio.gather(
                    *[_exec_one(pc) for pc in parallel_batch],
                    return_exceptions=True,
                )
                for item in results:
                    if isinstance(item, Exception):
                        logger.error("tool_parallel_error", error=str(item))
                        continue
                    pc, result = item
                    event, output = self._process_tool_result(pc, result)
                    yield event
                    self.context.add_tool_result(
                        tool_call_id=pc["tc_id"],
                        name=pc["name"],
                        result=output,
                    )
                    # Log full tool result
                    logger.debug(
                        "tool_result",
                        name=pc["name"],
                        success=result.success,
                        output_preview=output[:300] if output else "",
                        output_length=len(output) if output else 0,
                        error=result.error or "",
                    )
                    # Track tool call in plan
                    if self.plan_manager.has_plan and self.plan_manager.plan:
                        active = self.plan_manager.plan.active_step
                        if active is not None:
                            idx = self.plan_manager.plan.current_step
                            self.plan_manager.add_tool_call(idx, {
                                "name": pc["name"],
                                "args": pc["args"],
                                "success": result.success,
                            })
                    # Record in error tracker
                    self.error_tracker.record_tool_call(
                        pc["name"],
                        pc["args"],
                        success=result.success,
                        error=result.error or "",
                    )
                    # Verify after edit
                    verify_event = await self._verify_after_edit(pc["name"], pc["args"], result)
                    if verify_event is not None:
                        yield verify_event

            # Execute sequential tools one at a time
            for pc in sequential_calls:
                logger.debug(
                    "tool_call_args",
                    name=pc["name"],
                    args=pc["args"],
                    tc_id=pc["tc_id"],
                )
                # Permission check
                try:
                    tool_obj = tool_registry.get(pc["name"])
                    perm_level: str = tool_obj.permission_level
                except KeyError:
                    perm_level = "read"

                if not self.permissions.check(pc["name"], perm_level):
                    yield AgentEvent(
                        type=EventType.PERMISSION_REQUEST,
                        data={
                            "tool_name": pc["name"],
                            "args": pc["args"],
                            "permission_level": perm_level,
                        },
                    )

                    if self.permission_callback is not None:
                        approved = await self.permission_callback(
                            pc["name"], pc["args"], perm_level
                        )
                    else:
                        approved = True

                    if not approved:
                        self.context.add_tool_result(
                            tool_call_id=pc["tc_id"],
                            name=pc["name"],
                            result=(
                                "Permission denied by user. "
                                "Try a different approach that doesn't "
                                "require this operation."
                            ),
                        )
                        yield AgentEvent(
                            type=EventType.TOOL_RESULT,
                            data={
                                "name": pc["name"],
                                "result": "Permission denied by user.",
                            },
                        )
                        continue

                    self.permissions.approve_tool(pc["name"])

                result = await tool_registry.execute_from_llm(pc["tc"])
                event, output = self._process_tool_result(pc, result)
                yield event
                self.context.add_tool_result(
                    tool_call_id=pc["tc_id"],
                    name=pc["name"],
                    result=output,
                )
                # Log full tool result
                logger.debug(
                    "tool_result",
                    name=pc["name"],
                    success=result.success,
                    output_preview=output[:300] if output else "",
                    output_length=len(output) if output else 0,
                    error=result.error or "",
                )
                # Track tool call in plan
                if self.plan_manager.has_plan and self.plan_manager.plan:
                    active = self.plan_manager.plan.active_step
                    if active is not None:
                        idx = self.plan_manager.plan.current_step
                        self.plan_manager.add_tool_call(idx, {
                            "name": pc["name"],
                            "args": pc["args"],
                            "success": result.success,
                        })
                # Record in error tracker
                self.error_tracker.record_tool_call(
                    pc["name"],
                    pc["args"],
                    success=result.success,
                    error=result.error or "",
                )
                # Verify after edit
                verify_event = await self._verify_after_edit(pc["name"], pc["args"], result)
                if verify_event is not None:
                    yield verify_event

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
    # Tool result processing
    # ------------------------------------------------------------------

    def _process_tool_result(
        self, pc: dict[str, Any], result: ToolResult
    ) -> tuple[AgentEvent, str]:
        """Process a tool result: truncate and return event + processed output."""
        event = AgentEvent(
            type=EventType.TOOL_RESULT,
            data={"name": pc["name"], "result": result},
        )

        output = result.output
        if pc["name"] in ("search_content", "search_files"):
            output = truncate_search_results(output)
        else:
            output = truncate_tool_result(output, tool_name=pc["name"])

        # Update workspace index after file-modifying tools
        self._update_index_after_tool(pc["name"], pc["args"], result)

        return event, output

    def _update_index_after_tool(
        self, tool_name: str, args: dict[str, Any], result: ToolResult
    ) -> None:
        """Update workspace index after file-modifying tool calls."""
        if not result.success:
            return

        if tool_name == "write_file":
            path = args.get("path", "")
            if path:
                from pathlib import Path

                self.workspace_index.update_file(
                    Path(path), "created", workspace=self.workspace
                )
        elif tool_name == "edit_file":
            path = args.get("path", "")
            if path:
                from pathlib import Path

                self.workspace_index.update_file(
                    Path(path), "modified", workspace=self.workspace
                )

    async def _verify_after_edit(
        self, tool_name: str, args: dict[str, Any], result: ToolResult
    ) -> AgentEvent | None:
        """Run post-edit verification if enabled. Returns event to yield."""
        if not self.verify_after_edit or not result.success:
            return None
        if tool_name not in ("write_file", "edit_file"):
            return None

        from pathlib import Path

        file_path = Path(args.get("path", "")).resolve()
        if not file_path.exists():
            return None

        verification = await self.verifier.verify(file_path)

        # Log verification result
        logger.debug(
            "verification_result",
            file=str(file_path),
            all_passed=verification.all_passed,
            checks_run=len(verification.checks),
            failed=len(verification.failed_checks),
        )

        if verification.all_passed:
            return None

        # Feed verification failure back to context as user message
        # (not as tool result — there's no matching tool_call_id)
        feedback = verification.to_feedback()
        self.context.add_user_message(
            f"[system] {feedback}"
        )

        return AgentEvent(
            type=EventType.VERIFICATION,
            data={
                "file_path": str(file_path),
                "checks": [
                    {"tool": c.tool, "passed": c.passed, "output": c.output[:200]}
                    for c in verification.failed_checks
                ],
            },
        )

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
        self.plan_manager.reset()
