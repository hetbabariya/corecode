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
from coding_agent.agent.reflector import Assessment, Reflector
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


def _is_context_overflow_error(exc: Exception) -> bool:
    """Detect context overflow errors across providers.

    Returns True if the error indicates the prompt/context is too long.
    """
    msg = str(exc).lower()
    patterns = [
        "prompt_too_long",
        "context_length_exceeded",
        "maximum context length",
        "context window",
        "token limit",
        "request too large",
        "400",  # HTTP 400 often indicates context overflow
    ]
    return any(p in msg for p in patterns)


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
        max_iterations: int = 0,
        max_iterations_safety: int = 500,
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
        self.max_iterations = max_iterations  # 0 = unlimited
        self.max_iterations_safety = max_iterations_safety
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

        # Post-action reflection
        self.reflector = Reflector()

        # Phase B.4: Progress evaluation interval
        self._progress_eval_interval: int = 5

        # Phase A.3: Max tokens recovery
        self._max_tokens_recovery_count: int = 0
        self._max_tokens_recovery_max: int = 3
        self._stop_reason: str = ""

        # Phase A.4: Reactive compact (context overflow recovery)
        self._reactive_compact_count: int = 0
        self._reactive_compact_max: int = 3

        # Phase A metrics
        self.metrics: dict[str, int | float] = {
            "permission_check_count": 0,
            "permission_deny_count": 0,
            "tool_count": 0,
            "summarize_count": 0,
            "summarize_success": 0,
            "summarize_fail": 0,
            "summarize_duration_ms": 0.0,
            "context_suggestion_count": 0,
            "token_estimate_calls": 0,
            "prompt_cache_hits": 0,
            "prompt_cache_misses": 0,
            "micro_compact_count": 0,
        }

        # Smart context engine
        self.context_engine = SmartContextEngine(
            context=self.context,
            error_tracker=self.error_tracker,
        )

        # Background task tracking (prevent fire-and-forget)
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._summarize_lock = asyncio.Lock()

        # Session cleanup guard — ensures one-time cleanup on exit
        self._cleanup_done = False

        # Build and inject the system prompt
        self._cached_system_prompt: str | None = None
        self.context.system_prompt = self._build_system_prompt_cached()

    async def _reactive_compact(self) -> None:
        """Reactive compact — summarize older messages to reduce context size.

        This is called when the context window is full and we need to
        compress the conversation to continue. Keeps the last 3 messages
        and summarizes everything else.
        """
        if len(self.context.messages) <= 3:
            return

        # Get the old messages to summarize
        old_messages = self.context.messages[:-3]
        recent_messages = self.context.messages[-3:]

        # Build a summary prompt
        summary_parts: list[str] = []
        for msg in old_messages:
            if msg.role in ("user", "assistant"):
                content = msg.content[:500] if msg.content else ""
                summary_parts.append(f"{msg.role}: {content}")
            elif msg.role == "tool":
                name = msg.name or "tool"
                content = msg.content[:200] if msg.content else ""
                summary_parts.append(f"  [tool_result: {name}] {content}")

        old_content = "\n".join(summary_parts)

        # Use the summary LLM client if available, otherwise use main client
        summary_client = self.summary_llm_client or self.llm_client

        # Generate summary
        try:
            messages = [
                {"role": "system", "content": "Summarize the following conversation concisely, keeping key facts and decisions:"},
                {"role": "user", "content": old_content},
            ]
            response = await summary_client.complete(messages)
            summary = response.content
        except Exception as exc:
            logger.warning("reactive_compact_summary_failed", error=str(exc)[:200])
            # Fallback: just keep a simple summary
            summary = f"[Previous conversation with {len(old_messages)} messages]"

        # Replace old messages with summary
        self.context._summary = summary
        self.context.messages = recent_messages

        logger.info(
            "reactive_compact_completed",
            old_count=len(old_messages),
            new_count=len(recent_messages),
            summary_length=len(summary),
        )

    async def _run_session_cleanup(
        self, last_text: str = "", iteration: int = 0,
    ) -> None:
        """Run one-time session cleanup: episodic memory, consolidation, pruning, plan save, stats.

        Safe to call multiple times — guarded by ``_cleanup_done``.
        """
        if self._cleanup_done:
            return
        self._cleanup_done = True

        duration = time.monotonic() - self._start_time if self._start_time else 0.0
        logger.info(
            "agent_session_end",
            duration_s=round(duration, 1),
            iterations=iteration,
            tool_count=self._tool_count,
            total_cost=round(self._accumulated_cost, 4),
            status="completed",
        )
        self.metrics["tool_count"] = self._tool_count
        logger.info(
            "session_metrics",
            **{k: v for k, v in self.metrics.items()},  # type: ignore[arg-type]
        )
        print(self.get_metrics_summary())

        # Save episodic memory (session summary)
        if self.memory_manager is not None:
            summary = self._build_session_summary(last_text, iteration)
            await self.memory_manager.save_episodic(
                summary,
                workspace=str(self.workspace),
                session_id=self.session_id,
            )
            # Consolidate similar memories (D.1)
            await self.memory_manager.consolidate_memories(
                workspace=str(self.workspace),
            )
            # Prune low-value memories (D.4)
            await self.memory_manager.prune_memories(
                workspace=str(self.workspace),
            )

        # Save active plan state (D.3)
        if (
            self.plan_manager is not None
            and self.session_manager is not None
            and self.plan_manager.has_plan
        ):
            await self.plan_manager.save(
                self.session_manager,
                str(self.workspace),
            )

        # Update session stats
        if self.session_manager is not None and self.session_id is not None:
            usage = self.llm_client.total_usage
            await self.session_manager.update_session_stats(
                self.session_id,
                tokens=usage.total_tokens,
                cost=usage.estimated_cost,
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
        * Budget (cost/time) is exceeded.
        * The safety net iteration limit is reached (should never happen).
        """
        # Load cross-session memories into the system prompt
        if self.memory_manager is not None:
            memory_content = await self.memory_manager.build_prompt_content(
                workspace=str(self.workspace),
            )
            if memory_content:
                self.context.system_prompt = self._build_system_prompt_cached(
                    memory_content=memory_content,
                )

        # Resume active plan from previous session (D.3)
        if (
            self.plan_manager is not None
            and self.session_manager is not None
            and not self.plan_manager.has_plan
        ):
            plan_data = await self.session_manager.load_active_plan(
                str(self.workspace)
            )
            if plan_data:
                self.plan_manager.load_from_dict(plan_data)
                logger.info(
                    "plan_resumed",
                    goal=plan_data.get("goal", ""),
                    current_step=plan_data.get("current_step", 0),
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
            max_iterations_safety=self.max_iterations_safety,
            max_cost=self.max_cost,
            max_time=self.max_time,
            input_length=len(user_input),
        )

        _iteration = 0
        while True:
            _iteration += 1
            logger.info("agent_iteration", iteration=_iteration)
            yield AgentEvent(
                type=EventType.LOOP_START,
                data={"iteration": _iteration},
            )

            # --- Check safety net ---
            if (
                self.max_iterations_safety > 0
                and _iteration >= self.max_iterations_safety
            ):
                logger.critical(
                    "agent_safety_net_hit",
                    iteration=_iteration,
                    max_safety=self.max_iterations_safety,
                )
                yield AgentEvent(
                    type=EventType.MAX_ITERATIONS,
                    data={"reason": "safety_net", "iteration": _iteration},
                )
                await self._run_session_cleanup("", _iteration)
                return

            # --- Check user-configured limit (0 = unlimited) ---
            if (
                self.max_iterations > 0
                and _iteration >= self.max_iterations
            ):
                logger.warning(
                    "agent_max_iterations",
                    max_iterations=self.max_iterations,
                    iteration=_iteration,
                )
                yield AgentEvent(
                    type=EventType.MAX_ITERATIONS,
                    data={"reason": "user_limit", "iteration": _iteration},
                )
                await self._run_session_cleanup("", _iteration)
                return

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
                    data={
                        "reason": "time",
                        "elapsed": elapsed,
                        "limit": self.max_time,
                        "can_continue": True,
                        "iteration": _iteration,
                    },
                )
                await self._run_session_cleanup("", _iteration)
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
                        "can_continue": True,
                        "iteration": _iteration,
                    },
                )
                await self._run_session_cleanup("", _iteration)
                return

            # --- Inject plan state into system prompt ---
            if self.plan_manager.has_plan:
                plan_prompt = self.plan_manager.to_prompt()
                self.context.system_prompt = self._build_system_prompt_cached(
                    plan_prompt=plan_prompt,
                )

                # Phase B.2: Auto-replanning when a step fails
                if self.plan_manager.needs_replan():
                    new_plan = await self._generate_replan()
                    if new_plan is not None:
                        self.plan_manager.replace_plan(new_plan)
                        self.context.system_prompt = self._build_system_prompt_cached(
                            plan_prompt=self.plan_manager.to_prompt(),
                        )
                        yield AgentEvent(
                            type=EventType.PLAN_UPDATE,
                            data={
                                "action": "replanned",
                                "plan": new_plan.to_dict(),
                            },
                        )
                    else:
                        yield AgentEvent(
                            type=EventType.PLAN_UPDATE,
                            data={
                                "action": "replan_failed",
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
                    await self._run_session_cleanup("", _iteration)
                    return
                else:
                    yield AgentEvent(
                        type=EventType.STUCK_DETECTED,
                        data={"message": stuck_msg, "strategy": strategy.value},
                    )

            # --- Build messages for LLM ---
            messages = self.context.build_messages()
            tools = tool_registry.get_schemas()

            # --- Stream LLM response (with context overflow recovery) ---
            tool_calls: list[dict[str, Any]] = []
            text_parts: list[str] = []
            self._stop_reason = ""
            _stream_success = False

            try:
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

                    elif event.type == StreamEventType.STOP_REASON:
                        # Capture stop_reason for max tokens recovery
                        if isinstance(event.data, dict):
                            self._stop_reason = event.data.get("finish_reason", "")

                    elif event.type == StreamEventType.DONE:
                        break

                _stream_success = True

            except Exception as exc:
                # Phase A.4: Context overflow recovery
                if _is_context_overflow_error(exc):
                    self._reactive_compact_count += 1
                    if self._reactive_compact_count <= self._reactive_compact_max:
                        logger.warning(
                            "context_overflow_detected",
                            attempt=self._reactive_compact_count,
                            max_attempts=self._reactive_compact_max,
                            error=str(exc)[:200],
                        )

                        # Step 1: Overflow flush — drop oldest tool results
                        dropped = self.context.drop_oldest_tool_results(count=2)
                        logger.info(
                            "overflow_flush",
                            dropped=dropped,
                            remaining_messages=len(self.context.messages),
                        )

                        # Step 2: If no tool results to drop, summarize older messages
                        if dropped == 0 and len(self.context.messages) > 6:
                            logger.info("reactive_compact_summarize")
                            await self._reactive_compact()

                        # Emit event for TUI visibility
                        yield AgentEvent(
                            type=EventType.REACTIVE_COMPACT,
                            data={
                                "attempt": self._reactive_compact_count,
                                "max_attempts": self._reactive_compact_max,
                                "dropped": dropped,
                            },
                        )

                        # Continue the loop to retry with compressed context
                        continue
                    else:
                        # Max attempts reached
                        logger.error(
                            "reactive_compact_failed",
                            max_attempts=self._reactive_compact_max,
                            error=str(exc)[:200],
                        )
                        yield AgentEvent(
                            type=EventType.ERROR,
                            data={
                                "error": f"Context overflow - max recovery attempts reached: {str(exc)[:200]}",
                            },
                        )
                        await self._run_session_cleanup("", _iteration)
                        return
                else:
                    # Not a context overflow error — re-raise
                    raise

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
                stop_reason=self._stop_reason,
            )

            # --- Phase A.3: Max tokens recovery ---
            # Check if response was truncated due to max tokens
            from coding_agent.llm.client import _normalize_stop_reason
            normalized_stop_reason = _normalize_stop_reason(self._stop_reason)
            if normalized_stop_reason == "max_tokens":
                self._max_tokens_recovery_count += 1
                if self._max_tokens_recovery_count <= self._max_tokens_recovery_max:
                    logger.warning(
                        "max_tokens_recovery",
                        attempt=self._max_tokens_recovery_count,
                        max_attempts=self._max_tokens_recovery_max,
                        text_length=len(full_text),
                    )
                    yield AgentEvent(
                        type=EventType.MAX_TOKENS_RECOVERY,
                        data={
                            "attempt": self._max_tokens_recovery_count,
                            "max_attempts": self._max_tokens_recovery_max,
                            "text_length": len(full_text),
                        },
                    )
                    # Add continuation prompt to context
                    self.context.add_user_message(
                        "Your response was cut off due to token limit. "
                        "Please continue from where you left off."
                    )
                    # Persist continuation prompt
                    if self.session_manager is not None and self.session_id is not None:
                        await self.session_manager.save_message(
                            self.session_id, "user",
                            "Your response was cut off due to token limit. "
                            "Please continue from where you left off.",
                        )
                    # Continue the loop to get the rest of the response
                    continue
                else:
                    logger.error(
                        "max_tokens_recovery_failed",
                        max_attempts=self._max_tokens_recovery_max,
                    )
                    # Reset counter and fall through to normal completion
                    self._max_tokens_recovery_count = 0

            # Reset recovery count on successful completion
            self._max_tokens_recovery_count = 0

            # --- No tool calls → done ---
            if not tool_calls:
                # Run progress evaluation one last time before exiting
                if _iteration > 0 and _iteration % self._progress_eval_interval == 0:
                    progress = self._evaluate_progress()
                    logger.info(
                        "progress_evaluation",
                        completed=progress["completed"],
                        total=progress["total"],
                        ratio=progress["progress_ratio"],
                        stalled=progress["is_stalled"],
                        tool_count=progress["tool_count"],
                    )
                    if progress["is_stalled"]:
                        yield AgentEvent(
                            type=EventType.STUCK_DETECTED,
                            data={
                                "message": (
                                    f"Progress stalled after {progress['tool_count']} tools, "
                                    f"{progress['completed']}/{progress['total']} plan steps done."
                                ),
                                "progress": progress,
                            },
                        )

                await self._run_session_cleanup(full_text, _iteration)
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
                    data={"name": pc["name"], "args": pc["args"], "tc_id": pc["tc_id"]},
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
                # Permission gate for parallel tools
                approved_parallel: list[dict[str, Any]] = []
                for pc in parallel_batch:
                    logger.debug(
                        "tool_call_args",
                        name=pc["name"],
                        args=pc["args"],
                        tc_id=pc["tc_id"],
                    )
                    perm_level = self._resolve_permission_level(pc)

                    if not self.permissions.check(pc["name"], perm_level):
                        logger.info(
                            "permission_check",
                            tool=pc["name"],
                            approved=False,
                            path="parallel",
                        )
                        self.metrics["permission_deny_count"] += 1
                        async for event in self._emit_permission_deny(pc):
                            yield event
                        continue
                    logger.info(
                        "permission_check",
                        tool=pc["name"],
                        approved=True,
                        path="parallel",
                    )
                    self.metrics["permission_check_count"] += 1
                    yield AgentEvent(
                        type=EventType.PERMISSION_CHECK,
                        data={"tool_name": pc["name"], "approved": True},
                    )
                    approved_parallel.append(pc)

                if approved_parallel:
                    async def _exec_one(pc: dict[str, Any]) -> tuple[dict[str, Any], ToolResult]:
                        return pc, await tool_registry.execute_from_llm(pc["tc"])

                    results = await asyncio.gather(
                        *[_exec_one(pc) for pc in approved_parallel],
                        return_exceptions=True,
                    )
                else:
                    results = []

                for item in results:
                    if isinstance(item, Exception):
                        logger.error("tool_parallel_error", error=str(item))
                        continue
                    pc, result = item
                    async for event in self._finalize_tool_execution(pc, result):
                        yield event
                self._tool_count += len(approved_parallel)

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
                perm_level = self._resolve_permission_level(pc)

                if not self.permissions.check(pc["name"], perm_level):
                    logger.info(
                        "permission_check",
                        tool=pc["name"],
                        approved=False,
                        path="sequential",
                    )
                    self.metrics["permission_deny_count"] += 1
                    yield AgentEvent(
                        type=EventType.PERMISSION_CHECK,
                        data={"tool_name": pc["name"], "approved": False},
                    )
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
                        # No callback registered — respect the permission check.
                        # Denied tools must NOT execute silently.
                        approved = False

                    if not approved:
                        logger.warning(
                            "permission_denied",
                            tool=pc["name"],
                            args=pc["args"],
                        )
                        async for event in self._emit_permission_deny(pc):
                            yield event
                        continue

                    self.permissions.approve_tool(pc["name"])
                    yield AgentEvent(
                        type=EventType.PERMISSION_CHECK,
                        data={"tool_name": pc["name"], "approved": True},
                    )
                else:
                    self.metrics["permission_check_count"] += 1
                    yield AgentEvent(
                        type=EventType.PERMISSION_CHECK,
                        data={"tool_name": pc["name"], "approved": True},
                    )

                # Auto-checkpoint before file modifications
                _EDIT_TOOLS = {"write_file", "edit_file", "apply_patch", "multi_edit"}
                if pc["name"] in _EDIT_TOOLS:
                    try:
                        import asyncio
                        from coding_agent.sandbox.checkpoint import CheckpointManager

                        def _create_checkpoint() -> tuple[str, str]:
                            mgr = CheckpointManager(".")
                            cp = mgr.create_checkpoint(f"before {pc['name']}")
                            return cp.id, cp.label

                        checkpoint_id, checkpoint_label = await asyncio.to_thread(
                            _create_checkpoint
                        )
                        logger.info(
                            "auto_checkpoint",
                            checkpoint_id=checkpoint_id,
                            tool=pc["name"],
                        )
                        yield AgentEvent(
                            type=EventType.CHECKPOINT,
                            data={
                                "checkpoint_id": checkpoint_id,
                                "label": checkpoint_label,
                                "tool": pc["name"],
                            },
                        )
                    except Exception as e:
                        logger.warning("auto_checkpoint_failed", error=str(e))

                result = await tool_registry.execute_from_llm(pc["tc"])
                tool_duration_ms = (time.monotonic() - tool_start) * 1000
                self._tool_count += 1
                async for event in self._finalize_tool_execution(pc, result, tool_duration_ms):
                    yield event

            # --- Phase B.1: Micro-compact old tool results ---
            compacted = self.context.compact_old_tool_results(keep_recent=10)
            if compacted > 0:
                logger.info(
                    "micro_compact",
                    compacted=compacted,
                    remaining_messages=len(self.context.messages),
                )
                self.metrics["micro_compact_count"] = (
                    self.metrics.get("micro_compact_count", 0) + compacted
                )
                yield AgentEvent(
                    type=EventType.MICRO_COMPACT,
                    data={
                        "compacted": compacted,
                        "remaining_messages": len(self.context.messages),
                    },
                )

            # --- Check context budget (progressive thresholds) ---
            usage_ratio = await self._check_context_usage()

            # --- Smart context engine: select prioritized context ---
            slices = self.context_engine.select_context(
                include_error_context=True,
                include_verification=True,
                include_plan=self.plan_manager.has_plan,
                plan_text=self.plan_manager.to_prompt() if self.plan_manager.has_plan else "",
            )
            if slices:
                context_summary = self.context_engine.format_selected_context(slices)
                total_est = self.context_engine.get_total_tokens(slices)
                self.metrics["context_suggestion_count"] += 1
                logger.info(
                    "context_engine_selection",
                    slice_count=len(slices),
                    total_tokens=total_est,
                    usage_ratio=f"{usage_ratio:.1%}",
                )
                # Inject as system-level context so the LLM sees prioritized info
                self.context.set_context_summary(context_summary[:2000])
                yield AgentEvent(
                    type=EventType.CONTEXT_HEALTH,
                    data={
                        "usage_ratio": usage_ratio,
                        "slice_count": len(slices),
                        "total_tokens": total_est,
                        "sources": [s.source for s in slices],
                    },
                )

            # --- Phase B.4: Progress evaluation every N iterations ---
            if _iteration > 0 and _iteration % self._progress_eval_interval == 0:
                progress = self._evaluate_progress()
                logger.info(
                    "progress_evaluation",
                    completed=progress["completed"],
                    total=progress["total"],
                    ratio=progress["progress_ratio"],
                    stalled=progress["is_stalled"],
                    tool_count=progress["tool_count"],
                )
                if progress["is_stalled"]:
                    yield AgentEvent(
                        type=EventType.STUCK_DETECTED,
                        data={
                            "message": (
                                f"Progress stalled after {progress['tool_count']} tools, "
                                f"{progress['completed']}/{progress['total']} plan steps done."
                            ),
                            "progress": progress,
                        },
                    )

    # ------------------------------------------------------------------
    # Tool result processing
    # ------------------------------------------------------------------

    def _resolve_permission_level(self, pc: dict[str, Any]) -> str:
        """Look up the permission level for a tool call."""
        try:
            return tool_registry.get(pc["name"]).permission_level
        except KeyError:
            return "read"

    async def _emit_permission_deny(self, pc: dict[str, Any]) -> AsyncIterator[AgentEvent]:
        """Yield events for a permission denial (shared by parallel and sequential paths)."""
        yield AgentEvent(
            type=EventType.PERMISSION_CHECK,
            data={"tool_name": pc["name"], "approved": False},
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
                "tc_id": pc["tc_id"],
            },
        )

    async def _finalize_tool_execution(
        self,
        pc: dict[str, Any],
        result: ToolResult,
        tool_duration_ms: float | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Shared post-execute processing: emit event, add to context, run side effects."""
        event, output = self._process_tool_result(pc, result)
        yield event
        self.context.add_tool_result(
            tool_call_id=pc["tc_id"],
            name=pc["name"],
            result=output,
        )
        async for sub_event in self._post_tool_actions(pc, result, output, tool_duration_ms):
            yield sub_event

    def _process_tool_result(
        self, pc: dict[str, Any], result: ToolResult
    ) -> tuple[AgentEvent, str]:
        """Process a tool result: truncate, inject instructions, return event + output."""
        event = AgentEvent(
            type=EventType.TOOL_RESULT,
            data={"name": pc["name"], "result": result, "tc_id": pc["tc_id"]},
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

    async def _post_tool_actions(
        self,
        pc: dict[str, Any],
        result: ToolResult,
        output: str,
        tool_duration_ms: float | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Shared post-execution side effects for both parallel and sequential paths.

        Handles: logging, plan tracking, error recording, context engine,
        session persistence, and verification.
        """
        # Log full tool result
        log_kwargs: dict[str, Any] = {
            "name": pc["name"],
            "success": result.success,
            "output_preview": output[:300] if output else "",
            "output_length": len(output) if output else 0,
            "error": result.error or "",
        }
        if tool_duration_ms is not None:
            log_kwargs["duration_ms"] = round(tool_duration_ms, 1)
        logger.debug("tool_result", **log_kwargs)

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

        # Post-action reflection (signal-only: assessment + reason + confidence)
        reflection = self.reflector.reflect_on_tool(pc["name"], pc["args"], result)
        logger.debug(
            "tool_reflection",
            tool=pc["name"],
            assessment=reflection.assessment.value,
            confidence=reflection.confidence,
            reason=reflection.reason,
        )
        yield AgentEvent(
            type=EventType.REFLECTION,
            data={
                "tool_name": pc["name"],
                "assessment": reflection.assessment.value,
                "reason": reflection.reason,
                "confidence": reflection.confidence,
            },
        )

        # Phase B.3: Outcome assessment when plan is active
        # Only assess file-modifying tools — read-only and query tools
        # generate false negatives (e.g., read_file "failed" because it
        # didn't create a file).  Shell commands are also excluded because
        # lint-check failures are not meaningful against a creation step.
        _ASSESSMENT_ALLOWLIST = {"write_file", "edit_file", "apply_patch", "multi_edit"}
        if (
            self.plan_manager.has_plan
            and self.plan_manager.plan
            and pc["name"] in _ASSESSMENT_ALLOWLIST
        ):
            active = self.plan_manager.plan.active_step
            if active is not None:
                # Skip LLM call when rule-based heuristic already says success
                # with high confidence — saves ~15-30s per file write
                if (
                    reflection.assessment == Assessment.SUCCESS
                    and reflection.confidence >= 0.8
                ):
                    logger.debug(
                        "outcome_assessment_skipped",
                        tool=pc["name"],
                        reason="rule_based_success",
                    )
                else:
                    outcome_reflection = await self.reflector.assess_outcome(
                        pc["name"], pc["args"], result,
                        expected_outcome=active.description,
                        llm_client=self.llm_client,
                    )
                    if outcome_reflection.assessment.value != reflection.assessment.value:
                        logger.info(
                            "outcome_assessment",
                            tool=pc["name"],
                            assessment=outcome_reflection.assessment.value,
                            reason=outcome_reflection.reason,
                            confidence=outcome_reflection.confidence,
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

    # ------------------------------------------------------------------
    # Phase B.4: Progress evaluation
    # ------------------------------------------------------------------

    def _evaluate_progress(self) -> dict[str, Any]:
        """Evaluate progress toward the goal.

        Returns a dict with completed/failed/total counts, progress_ratio,
        is_stalled flag, cost_per_step, and elapsed time.
        """
        completed = 0
        failed = 0
        total = 0

        if self.plan_manager.has_plan and self.plan_manager.plan:
            plan = self.plan_manager.plan
            completed = len(plan.completed_steps)
            failed = len(plan.failed_steps)
            total = len(plan.steps)

        progress_ratio = completed / total if total > 0 else 0.0

        is_stalled = (
            self._tool_count > 0
            and self.error_tracker.is_stuck()
        )

        elapsed = time.monotonic() - self._start_time
        cost_per_step = self._accumulated_cost / max(completed, 1)

        return {
            "completed": completed,
            "failed": failed,
            "total": total,
            "progress_ratio": progress_ratio,
            "is_stalled": is_stalled,
            "cost_per_step": round(cost_per_step, 4),
            "elapsed": round(elapsed, 1),
            "tool_count": self._tool_count,
        }

    # ------------------------------------------------------------------
    # Phase B.2: Auto-replanning
    # ------------------------------------------------------------------

    async def _generate_replan(self) -> "Plan | None":
        """Generate a new plan using the LLM when a step fails.

        Returns a new Plan or None if replanning fails.
        """
        from coding_agent.agent.planner import Plan, PlanStep, PlanStatus

        current_state = self.plan_manager.to_prompt()
        failed_step = ""
        if self.plan_manager.plan and self.plan_manager.plan.active_step:
            failed_step = self.plan_manager.plan.active_step.description

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a planning assistant. The previous plan had a step that failed. "
                    "Generate a NEW plan that accounts for what was already accomplished. "
                    "Return ONLY a JSON object with this exact format:\n"
                    '{"goal": "...", "steps": ["step 1", "step 2", ...]}\n'
                    "3-10 steps. Be specific and actionable."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Previous plan state:\n{current_state}\n\n"
                    f"Failed step: {failed_step}\n\n"
                    "Generate a new plan."
                ),
            },
        ]

        try:
            response = await self.llm_client.complete(messages)
            return self._parse_plan_response(response.content)
        except Exception as e:
            logger.error("replan_failed", error=str(e))
            return None

    def _parse_plan_response(self, content: str) -> "Plan | None":
        """Parse an LLM response into a Plan object.

        Expects JSON with {"goal": "...", "steps": [...]}.
        """
        import json

        from coding_agent.agent.planner import Plan, PlanStep, PlanStatus

        try:
            # Try to extract JSON from the response (may be wrapped in markdown)
            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            goal = data.get("goal", "Replanned task")
            steps = data.get("steps", [])

            if not steps:
                return None

            plan_steps = [PlanStep(description=desc) for desc in steps]
            return Plan(
                goal=goal,
                steps=plan_steps,
                status=PlanStatus.EXECUTING,
            )
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("replan_parse_failed", error=str(e), content=content[:200])
            return None

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

        # Always record verification in context engine (even when passed)
        # so the context engine has data to report
        for check in verification.checks:
            self.context_engine.record_verification(
                check.tool, passed=check.passed, message=check.output[:200],
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

    def _spawn_summarize(self) -> None:
        """Spawn a tracked summarization task with lock to prevent concurrent runs."""
        if self._summarize_lock.locked():
            logger.debug("summarize_skipped", reason="already_in_progress")
            return
        task = asyncio.create_task(self._summarize_with_lock())
        self._bg_tasks.add(task)
        task.add_done_callback(self._on_summarize_done)

    async def _summarize_with_lock(self) -> None:
        """Summarize context under lock to prevent concurrent mutations."""
        async with self._summarize_lock:
            await self._summarize_context()

    def _on_summarize_done(self, task: asyncio.Task[None]) -> None:
        """Callback when summarization task completes."""
        self._bg_tasks.discard(task)
        self.metrics["summarize_count"] += 1
        if task.cancelled():
            self.metrics["summarize_fail"] += 1
            logger.warning("summarize_cancelled")
        elif task.exception() is not None:
            self.metrics["summarize_fail"] += 1
            logger.error("summarize_failed", error=str(task.exception()))
        else:
            self.metrics["summarize_success"] += 1

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

        start = time.monotonic()
        logger.info("summarize_start")
        try:
            response = await client.complete(summary_messages)
            self.context.summarize_old_messages(response.content)
            duration_ms = (time.monotonic() - start) * 1000
            self.metrics["summarize_duration_ms"] += duration_ms
            logger.info(
                "summarize_complete",
                summary_length=len(response.content),
                duration_ms=round(duration_ms, 1),
            )
        except Exception as e:
            logger.error("summarize_failed", error=str(e))
            raise

    # ------------------------------------------------------------------
    # Context usage checking (progressive thresholds)
    # ------------------------------------------------------------------

    async def _check_context_usage(self) -> float:
        """Check context usage and trigger summarization at progressive thresholds.

        Thresholds:
        - 70%: Soft warning (log only)
        - 85%: Fire-and-forget summarization with lock
        - 95%: Await summarization (blocking) + emit warning event

        Returns the current usage ratio (0.0 - 1.0+).
        """
        tokens = self.context.estimate_tokens()
        self.metrics["token_estimate_calls"] += 1
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
            # Critical: await summarization to prevent context overflow
            async with self._summarize_lock:
                await self._summarize_context()
                self.metrics["summarize_count"] += 1
                self.metrics["summarize_success"] += 1
        elif ratio >= 0.85:
            logger.info(
                "context_usage_high",
                tokens=tokens,
                max=max_tokens,
                ratio=f"{ratio:.1%}",
            )
            # Trigger summarization
            self._spawn_summarize()
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
        # Cancel background tasks
        for task in self._bg_tasks:
            task.cancel()
        self._bg_tasks.clear()

        self.context.clear()
        self.permissions.reset()
        self.plan_manager.reset()
        self.context_engine.clear_history()
        self.undo_stack.clear()
        self.session_id = None
        if self.memory_manager is not None:
            self.memory_manager.clear_working()
        # Reset metrics
        for key in self.metrics:
            self.metrics[key] = 0 if isinstance(self.metrics[key], int) else 0.0

    # ------------------------------------------------------------------
    # System prompt caching
    # ------------------------------------------------------------------

    def _build_system_prompt_cached(
        self, plan_prompt: str = "", memory_content: str = ""
    ) -> str:
        """Build system prompt with caching of static sections.

        The static prompt (identity, tools, safety, etc.) and workspace-dependent
        sections (environment, project context) are cached. Only plan and memory
        changes trigger a rebuild.
        """
        if self._cached_system_prompt is None:
            self._cached_system_prompt = build_system_prompt(
                model=self.llm_client.model,
                provider=self.llm_client.provider,
                workspace=self.workspace,
                workspace_index_summary=self.workspace_index.to_summary(),
            )
            self.metrics["prompt_cache_misses"] += 1
            logger.debug("prompt_cache_miss")
        else:
            self.metrics["prompt_cache_hits"] += 1

        # Append dynamic sections (plan, memory) that may change per iteration
        base = self._cached_system_prompt
        if plan_prompt:
            base += f"\n\n## Current Plan\n\n{plan_prompt}"
        if memory_content:
            base += f"\n\n## Memory\n\n{memory_content}"

        return base

    def invalidate_prompt_cache(self) -> None:
        """Force prompt rebuild on next call (e.g. after workspace changes)."""
        self._cached_system_prompt = None

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

    # ------------------------------------------------------------------
    # Metrics summary report
    # ------------------------------------------------------------------

    def get_metrics_summary(self) -> str:
        """Return a formatted summary of Phase A metrics for this session."""
        m = self.metrics
        lines = [
            "=== Session Metrics ===",
            f"  Permission checks:   {m['permission_check_count']} passed, {m['permission_deny_count']} denied",
            f"  Tools executed:      {m['tool_count']}",
            f"  Summarizations:      {m['summarize_count']} total, {m['summarize_success']} ok, {m['summarize_fail']} failed",
            f"  Summarize avg time:  {m['summarize_duration_ms'] / max(m['summarize_count'], 1):.0f}ms",
            f"  Context suggestions: {m['context_suggestion_count']}",
            f"  Token estimate calls:{m['token_estimate_calls']}",
            f"  Prompt cache:        {m['prompt_cache_hits']} hits, {m['prompt_cache_misses']} misses",
        ]
        return "\n".join(lines)
