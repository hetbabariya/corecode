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
from coding_agent.agent.context_engine import SmartContextEngine
from coding_agent.agent.context_limits import (
    large_file_instruction,
    truncate_search_results,
    truncate_tool_result,
)
from coding_agent.agent.error_recovery import ErrorTracker
from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.memory import MemoryManager
from coding_agent.agent.permissions import PermissionManager
from coding_agent.agent.planner import PlanManager
from coding_agent.agent.system_prompt import build_system_prompt
from coding_agent.agent.undo import UndoStack
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
        memory_manager: MemoryManager | None = None,
        session_manager: Any | None = None,
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

        # Session persistence
        self.session_manager = session_manager
        self.session_id: str | None = None

        # Memory system
        self.memory_manager = memory_manager
        if memory_manager is not None:
            from coding_agent.tools.memory import set_memory_manager
            set_memory_manager(memory_manager)

        # Undo/redo system
        self.undo_stack = UndoStack()
        from coding_agent.tools.undo import set_undo_stack
        set_undo_stack(self.undo_stack)

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

        # Smart context engine
        self.context_engine = SmartContextEngine(
            context=self.context,
            error_tracker=self.error_tracker,
        )

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
        # Load cross-session memories into the system prompt
        if self.memory_manager is not None:
            memory_content = await self.memory_manager.build_prompt_content(
                workspace=str(self.workspace),
            )
            if memory_content:
                self.context.system_prompt = build_system_prompt(
                    model=self.llm_client.model,
                    provider=self.llm_client.provider,
                    workspace=self.workspace,
                    memory_content=memory_content,
                    workspace_index_summary=self.workspace_index.to_summary(),
                )

        self.context.add_user_message(user_input)
        self._start_time = time.monotonic()
        self._accumulated_cost = 0.0
        self._tool_count = 0

        # Create session if session_manager is available
        if self.session_manager is not None and self.session_id is None:
            self.session_id = await self.session_manager.create_session(
                model=self.llm_client.model,
                provider=self.llm_client.provider,
                workspace=str(self.workspace),
            )
            logger.debug("session_created", session_id=self.session_id)

        # Persist user message
        if self.session_manager is not None and self.session_id is not None:
            await self.session_manager.save_message(
                self.session_id, "user", user_input,
            )

        logger.info(
            "agent_session_start",
            model=self.llm_client.model,
            provider=self.llm_client.provider,
            workspace=str(self.workspace),
            max_iterations=self.max_iterations,
            max_cost=self.max_cost,
            max_time=self.max_time,
            input_length=len(user_input),
        )

        for iteration in range(self.max_iterations):
            logger.info("agent_iteration", iteration=iteration + 1)

            # --- Check budget ---
            elapsed = time.monotonic() - self._start_time
            if elapsed > self.max_time:
                logger.warning(
                    "agent_budget_exceeded",
                    reason="time",
                    elapsed=round(elapsed, 1),
                    limit=self.max_time,
                )
                yield AgentEvent(
                    type=EventType.BUDGET_EXCEEDED,
                    data={"reason": "time", "elapsed": elapsed, "limit": self.max_time},
                )
                return
            if self._accumulated_cost >= self.max_cost:
                logger.warning(
                    "agent_budget_exceeded",
                    reason="cost",
                    cost=round(self._accumulated_cost, 4),
                    limit=self.max_cost,
                )
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

                # Persist assistant message
                if self.session_manager is not None and self.session_id is not None:
                    await self.session_manager.save_message(
                        self.session_id, "assistant", full_text,
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
                duration = time.monotonic() - self._start_time
                logger.info(
                    "agent_session_end",
                    duration_s=round(duration, 1),
                    iterations=iteration + 1,
                    tool_count=self._tool_count,
                    total_cost=round(self._accumulated_cost, 4),
                    status="completed",
                )

                # Save episodic memory (session summary)
                if self.memory_manager is not None:
                    summary = self._build_session_summary(full_text, iteration + 1)
                    await self.memory_manager.save_episodic(
                        summary,
                        workspace=str(self.workspace),
                        session_id=self.session_id,
                    )

                # Update session stats
                if self.session_manager is not None and self.session_id is not None:
                    usage = self.llm_client.total_usage
                    await self.session_manager.update_session_stats(
                        self.session_id,
                        tokens=usage.total_tokens,
                        cost=usage.estimated_cost,
                    )

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
                    # Record in context engine
                    self.context_engine.record_tool_result(
                        pc["name"], output, success=result.success,
                    )
                    # Persist tool operation
                    if self.session_manager is not None and self.session_id is not None:
                        await self.session_manager.save_operation(
                            self.session_id, pc["name"], pc["args"],
                            output[:500], success=result.success,
                        )
                    # Verify after edit
                    verify_event = await self._verify_after_edit(pc["name"], pc["args"], result)
                    if verify_event is not None:
                        yield verify_event
                self._tool_count += len(parallel_batch)

            # Execute sequential tools one at a time
            for pc in sequential_calls:
                tool_start = time.monotonic()
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
                        logger.warning(
                            "permission_denied",
                            tool=pc["name"],
                            args=pc["args"],
                        )
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
                tool_duration_ms = (time.monotonic() - tool_start) * 1000
                event, output = self._process_tool_result(pc, result)
                yield event
                self._tool_count += 1
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
                    duration_ms=round(tool_duration_ms, 1),
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
                # Record in context engine
                self.context_engine.record_tool_result(
                    pc["name"], output, success=result.success,
                )
                # Persist tool operation
                if self.session_manager is not None and self.session_id is not None:
                    await self.session_manager.save_operation(
                        self.session_id, pc["name"], pc["args"],
                        output[:500], success=result.success,
                    )
                # Verify after edit
                verify_event = await self._verify_after_edit(pc["name"], pc["args"], result)
                if verify_event is not None:
                    yield verify_event

            # --- Check context budget (progressive thresholds) ---
            self._check_context_usage()

        # Iteration budget exhausted
        duration = time.monotonic() - self._start_time
        logger.warning(
            "agent_max_iterations",
            max_iterations=self.max_iterations,
            duration_s=round(duration, 1),
            tool_count=self._tool_count,
            total_cost=round(self._accumulated_cost, 4),
        )
        yield AgentEvent(type=EventType.MAX_ITERATIONS)

    # ------------------------------------------------------------------
    # Tool result processing
    # ------------------------------------------------------------------

    def _process_tool_result(
        self, pc: dict[str, Any], result: ToolResult
    ) -> tuple[AgentEvent, str]:
        """Process a tool result: truncate, inject instructions, return event + output."""
        event = AgentEvent(
            type=EventType.TOOL_RESULT,
            data={"name": pc["name"], "result": result},
        )

        output = result.output
        if pc["name"] in ("search_content", "search_files"):
            output = truncate_search_results(output)
        else:
            output = truncate_tool_result(output, tool_name=pc["name"])

        # Inject large-file instructions for read_file results
        if pc["name"] == "read_file" and result.success:
            total_lines = (result.metadata or {}).get("total_lines", 0)
            returned_lines = (result.metadata or {}).get("returned_lines", 0)
            instruction = large_file_instruction(total_lines, returned_lines)
            if instruction:
                output = f"{instruction}\n\n{output}"

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

        # Record verification failure in context engine
        for check in verification.failed_checks:
            self.context_engine.record_verification(
                check.tool, passed=False, message=check.output[:200],
            )

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
    # Context usage checking (progressive thresholds)
    # ------------------------------------------------------------------

    def _check_context_usage(self) -> float:
        """Check context usage and trigger summarization at progressive thresholds.

        Thresholds:
        - 70%: Soft warning (log only)
        - 85%: Trigger summarization of old messages
        - 95%: Aggressive summarization + emit warning event

        Returns the current usage ratio (0.0 - 1.0+).
        """
        tokens = self.context.estimate_tokens()
        max_tokens = self.context.max_tokens
        if max_tokens <= 0:
            return 0.0

        ratio = tokens / max_tokens

        if ratio >= 0.95:
            logger.warning(
                "context_usage_critical",
                tokens=tokens,
                max=max_tokens,
                ratio=f"{ratio:.1%}",
            )
            # Aggressive: summarize immediately
            asyncio.create_task(self._summarize_context())
        elif ratio >= 0.85:
            logger.info(
                "context_usage_high",
                tokens=tokens,
                max=max_tokens,
                ratio=f"{ratio:.1%}",
            )
            # Trigger summarization
            asyncio.create_task(self._summarize_context())
        elif ratio >= 0.70:
            logger.debug(
                "context_usage_elevated",
                tokens=tokens,
                max=max_tokens,
                ratio=f"{ratio:.1%}",
            )
            # Soft warning — no action yet

        return ratio

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear conversation state for a fresh session."""
        self.context.clear()
        self.permissions.reset()
        self.plan_manager.reset()
        self.context_engine.clear_history()
        self.undo_stack.clear()
        self.session_id = None
        if self.memory_manager is not None:
            self.memory_manager.clear_working()

    # ------------------------------------------------------------------
    # Session summary for episodic memory
    # ------------------------------------------------------------------

    def _build_session_summary(self, final_response: str, iterations: int) -> str:
        """Build a concise summary for episodic memory."""
        parts = [
            f"Completed in {iterations} iteration(s), "
            f"cost=${self._accumulated_cost:.4f}.",
        ]
        # Include a preview of what was accomplished
        if final_response:
            preview = final_response[:200].strip()
            if preview:
                parts.append(f"Result: {preview}")
        return " ".join(parts)
