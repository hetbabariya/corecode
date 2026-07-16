# CoreCode Audit-Driven Modernization Plan

## From 5.6/10 to 9.0/10

This plan addresses the **10 significant gaps** identified in the architecture audit (`Context/agent-loop-audit.md`). It builds on top of the existing `implementation-plan.md` (Phases 1-3 complete, Phase 4 in progress).

> **Scope:** Backend intelligence and production hardening only. TUI is deferred.

---

## Progress Log

| Date | Item | What was done |
|------|------|---------------|
| 2025-07-15 | A.1 | Parallel permission checks: added `self.permissions.check()` before `asyncio.gather()`, emits `PERMISSION_CHECK` events, `main.py` counts checks/denials |
| 2025-07-15 | Bug fixes | ToolResult: added `success` param to 10 calls in `memory.py`/`undo.py`, fixed `error=True` → `error=str` |
| 2025-07-15 | Bug fixes | Token tracking: moved usage extraction before empty-choices early-return in `streaming.py` |
| 2025-07-15 | Bug fixes | Tool args race: `tool_args_by_id` dict keyed by `tc_id` instead of single variable |
| 2025-07-15 | Bug fixes | Iteration count: `LOOP_START` event per loop, count that instead of `TOOL_START` |
| 2025-07-15 | Display | Read-only tools (`read_file`, `search_*`, `git_*`) show one-line `✓ read_file → path` |
| 2025-07-15 | Debug | Added `logger.debug("stream_chunk")` + `logger.info("stream_usage_received")` to both Gemini and httpx streaming paths |
| 2025-07-15 | A.5 | Token estimation: fixed stale docstring, `estimate_tokens()` now includes system_prompt/project_context/summary in count |
| 2025-07-15 | A.4 | Summarization: added `asyncio.Lock`, `_summarize_lock` prevents concurrent runs, 95% threshold awaits summarization |
| 2025-07-15 | A.2 | Deduplicated tool processing: extracted `_resolve_permission_level()`, `_emit_permission_deny()`, `_finalize_tool_execution()` shared methods |
| 2025-07-15 | A.3 | SmartContextEngine wired: `select_context()` always called with error/verification/plan params, injected as system message via `set_context_summary()` |
| 2025-07-15 | A.6 | Prompt caching: `_STATIC_CACHE` + `_STATIC_CACHE_MODEL` in `system_prompt.py`, `get_static_prompt()` returns cached static section |
| 2025-07-16 | B.1 | Reflector (signal-only): `agent/reflector.py` with Assessment enum, rule-based heuristics, `REFLECTION` event type, TUI rendering |
| 2025-07-16 | B.2 | Auto-replanning: `_generate_replan()` via LLM, `_parse_plan_response()` JSON parsing, `PlanManager.replace_plan()` |
| 2025-07-16 | B.3 | Outcome assessment: `Reflector.assess_outcome()` with optional LLM-based comparison, falls back to heuristics |
| 2025-07-16 | B.4 | Progress evaluation: `_evaluate_progress()` every N iterations, `STUCK_DETECTED` when stalled |

---

## Table of Contents

1. [Gap Summary](#1-gap-summary)
2. [Phase A: Foundation Fixes](#2-phase-a-foundation-fixes)
3. [Phase B: Intelligence Layer](#3-phase-b-intelligence-layer)
4. [Phase C: Context Compression](#4-phase-c-context-compression)
5. [Phase D: Memory Enhancement](#5-phase-d-memory-enhancement)
6. [Phase E: Production Hardening](#6-phase-e-production-hardening)
7. [Dependency Graph](#7-dependency-graph)
8. [Effort Summary](#8-effort-summary)
9. [Priority Matrix](#9-priority-matrix)
10. [Success Criteria](#10-success-criteria)

---

## 1. Gap Summary

| # | Gap | Audit Score Impact | Root Cause |
|---|-----|-------------------|------------|
| 1 | SmartContextEngine built but never called | Context mgmt: 5/10 | Implemented in Phase 2.5 but never wired into loop.py |
| 2 | ~~Parallel tools skip permission checks~~ | ~~Security: risk~~ | ~~Permission check only in sequential path (loop.py:491-547)~~ **RESOLVED 2025-07-15** |
| 3 | Tool result processing duplicated (~180 lines) | Code quality | Parallel (419-488) and sequential (491-599) paths copy-pasted |
| 4 | No reflection after tool use | Reflection: 1/10 | Never planned in original implementation |
| 5 | No automatic replanning | Planning: 4/10 | `needs_replan()` detects but doesn't act |
| 6 | Summarization fire-and-forget | Reliability: risk | `asyncio.create_task()` at lines 791/800 |
| 7 | Token estimation inconsistency | Accuracy: risk | SmartContextEngine uses `len//4`, ContextManager uses tiktoken |
| 8 | No context compression beyond summarization | Context mgmt: 5/10 | Only mechanism is LLM-based summarization |
| 9 | No memory consolidation | Memory: 5/10 | Memories accumulate without merging/pruning |
| 10 | No prompt caching | Cost: medium | Static prompt rebuilt every session |

---

## 2. Phase A: Foundation Fixes ✅ COMPLETE

**Goal:** Fix critical bugs and integrate unused components. Address items 1-3, 6-7.

**Duration:** Week 1-2 (4 working days)
**Expected score after:** 5.6 → 6.5/10

- [x] A.1 Fix permission bypass for parallel tools
- [x] A.2 Deduplicate tool result processing
- [x] A.3 Integrate SmartContextEngine into loop
- [x] A.4 Fix summarization fire-and-forget
- [x] A.5 Unify token estimation
- [x] A.6 Add prompt caching for static sections

---

### Phase A+: Bug Fixes (Outside Audit Scope) ✅ DONE

These were identified and fixed during live agent testing (2025-07-15):

| Bug | Root Cause | Fix | Files |
|-----|-----------|-----|-------|
| ToolResult crashes in `recall`/`remember`/`undo` | Missing required `success` param, `error=True` (bool) instead of `error=str` | Added `success=` to all 10 calls, changed `error=True` → `error=str` | `memory.py`, `undo.py` |
| Token tracking shows 0 for OmniRoute | Usage extraction only inside `if finish_reason` block; OmniRoute sends usage in chunk with empty choices | Moved usage extraction before empty-choices early-return | `streaming.py` |
| Tool args display race condition | Single `current_tool_args` variable overwritten by parallel TOOL_START events | Added `tc_id` to TOOL_START/TOOL_RESULT events, dict lookup by ID | `loop.py`, `main.py` |
| Permission count shows 0 checked | `_RunStats.permission_checks` incremented on PERMISSION_REQUEST events, but loop emits permission_check log lines not events | Added `PERMISSION_CHECK` event type, emit on every check | `events.py`, `loop.py`, `main.py` |
| Iteration count wrong | `stats.iterations` incremented per TOOL_START (includes parallel calls) | Added `LOOP_START` event per loop iteration | `events.py`, `loop.py`, `main.py` |
| Read-only tool display too verbose | Every `read_file` shows 3-line content preview | Compact one-line display for `read_file`, `search_*`, `git_*`, etc. | `main.py` |
| No streaming debug logs | `stream()` method has zero logging for OmniRoute | Added `logger.debug("stream_chunk")` per 50th chunk + usage, `logger.info("stream_usage_received")`, `logger.debug("stream_finished")` | `client.py` |

---

### A.1 Fix Permission Bypass for Parallel Tools [CRITICAL] ✅ DONE

**Why:** Parallel tools (read_file, search_content, etc.) execute without permission checks. Only sequential tools go through `PermissionManager.check()`. This is a security gap.

**What to build:**

Add permission check before `asyncio.gather()` for parallel tools. Since parallel-safe tools are all `read` permission, this is a quick gate:

```python
# In loop.py, before parallel execution
for pc in parallel_batch:
    tool_obj = tool_registry.get(pc["name"])
    if not self.permissions.check(pc["name"], tool_obj.permission_level):
        # Skip and add denial message to context
        self.context.add_tool_result(
            tool_call_id=pc["tc_id"],
            name=pc["name"],
            result="Permission denied by user. Try a different approach.",
        )
        yield AgentEvent(
            type=EventType.TOOL_RESULT,
            data={"name": pc["name"], "result": "Permission denied."},
        )
        continue
    # ... execute tool
```

**Risk:** Low — all parallel-safe tools are read-only, which auto-approves in `PermissionManager.check()`.

**Files to modify:**
- `src/coding_agent/agent/loop.py` — add permission check in parallel path

**Verification:** Running with `permission="deny"` causes parallel read tools to be blocked.

**Complexity:** Low (3 hours)

**Implementation notes (2025-07-15):**
- Added `self.permissions.check()` + `PERMISSION_CHECK` events in both parallel and sequential paths (`loop.py`)
- `main.py` counts `PERMISSION_CHECK` events in `_RunStats.permission_checks` / `permission_denials`
- Added `PERMISSION_CHECK` event type to `events.py`
- Live verified: log shows `permission_check approved=True path=parallel tool=read_file` for all 7 parallel read_file calls

---

### A.2 Deduplicate Tool Result Processing

**Why:** Lines 419-488 (parallel) and 491-599 (sequential) contain ~180 lines of nearly identical logic for processing tool results. This violates DRY and makes maintenance error-prone.

**What to build:**

Extract a shared method `_execute_and_process_tool()` that handles the common flow:

```python
async def _execute_and_process_tool(
    self, pc: dict[str, Any]
) -> tuple[AgentEvent, str]:
    """Execute a single tool, process result, record in subsystems.
    
    Returns the TOOL_RESULT event and the processed output string.
    """
    result = await tool_registry.execute_from_llm(pc["tc"])
    event, output = self._process_tool_result(pc, result)
    
    # Add result to context
    self.context.add_tool_result(
        tool_call_id=pc["tc_id"],
        name=pc["name"],
        result=output,
    )
    
    # Record in plan
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
    
    # Persist to session
    if self.session_manager is not None and self.session_id is not None:
        await self.session_manager.save_operation(
            self.session_id, pc["name"], pc["args"],
            output[:500], success=result.success,
        )
    
    # Verify after edit
    verify_event = await self._verify_after_edit(pc["name"], pc["args"], result)
    if verify_event is not None:
        yield verify_event  # Note: this method becomes async generator
    
    return event, output
```

Then both parallel and sequential paths call this method:

```python
# Parallel path
async def _exec_one(pc):
    return pc, await self._execute_and_process_tool(pc)

results = await asyncio.gather(
    *[_exec_one(pc) for pc in parallel_batch],
    return_exceptions=True,
)

# Sequential path
for pc in sequential_calls:
    event, output = await self._execute_and_process_tool(pc)
    yield event
```

**Files to modify:**
- `src/coding_agent/agent/loop.py` — extract shared method, simplify both paths

**Verification:** All existing tests pass. Code is ~180 lines shorter. No behavioral change.

**Complexity:** Medium (6 hours)

---

### A.3 Integrate SmartContextEngine into Loop

**Why:** `SmartContextEngine.select_context()` is defined (262 lines) but never called. The loop uses `context.build_messages()` directly, wasting the prioritized context selection logic.

**What to build:**

Use SmartContextEngine to **augment** the system prompt with prioritized context. Before each LLM call, call `select_context()` and inject the result as an additional system message:

```python
# In loop.py, after building messages
slices = self.context_engine.select_context(
    include_error_context=True,
    include_verification=True,
    include_plan=self.plan_manager.has_plan,
    plan_text=self.plan_manager.to_prompt() if self.plan_manager.has_plan else "",
)
context_summary = self.context_engine.format_selected_context(slices)
if context_summary:
    # Insert after system prompt, before conversation
    # Find the system message index
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            messages.insert(i + 1, {
                "role": "system",
                "content": f"[Context Summary]\n{context_summary}"
            })
            break
```

This approach is **additive** — it doesn't replace `build_messages()`, it adds prioritized context on top.

**Files to modify:**
- `src/coding_agent/agent/loop.py` — call `select_context()` before LLM call

**Verification:** Debug logs show SmartContextEngine slices being injected. Context includes error/verification/plan information.

**Complexity:** Medium (8 hours)

---

### A.4 Fix Summarization Fire-and-Forget

**Why:** `asyncio.create_task(self._summarize_context())` at lines 791/800 creates background tasks that may not complete before the next iteration, or may conflict with each other (two summarizations running simultaneously).

**What to build:**

Use an `asyncio.Lock` to prevent concurrent summarization. At 85% threshold, fire-and-forget with lock. At 95% threshold, await with lock:

```python
# In AgentLoop.__init__
self._summarize_lock = asyncio.Lock()

async def _safe_summarize(self) -> None:
    """Summarize context with lock to prevent concurrent runs."""
    if self._summarize_lock.locked():
        return  # Already summarizing, skip
    async with self._summarize_lock:
        await self._summarize_context()

def _check_context_usage(self) -> float:
    # ... existing threshold checks ...
    
    if ratio >= 0.95:
        # Aggressive: await summarization
        asyncio.get_event_loop().create_task(
            self._await_summarize()
        )
    elif ratio >= 0.85:
        # Fire-and-forget with lock
        asyncio.create_task(self._safe_summarize())
    
    return ratio

async def _await_summarize(self) -> None:
    """Await summarization (for 95% threshold)."""
    async with self._summarize_lock:
        await self._summarize_context()
```

**Files to modify:**
- `src/coding_agent/agent/loop.py` — add lock, update `_check_context_usage()`

**Verification:** Concurrent summarization attempts are serialized. No overlapping summaries.

**Complexity:** Low (4 hours)

---

### A.5 Unify Token Estimation ✅ DONE

**Why:** `SmartContextEngine._estimate_tokens()` uses `len(text) // 4`, while `ContextManager.estimate_tokens()` uses tiktoken. This causes inconsistent token budgets.

**What to build:**

Import and use `count_tokens()` from `llm/tokens.py` in SmartContextEngine:

```python
# In context_engine.py
from coding_agent.llm.tokens import count_tokens

@staticmethod
def _estimate_tokens(text: str) -> int:
    """Accurate token estimate using tiktoken."""
    return count_tokens(text)
```

**Files to modify:**
- `src/coding_agent/agent/context_engine.py` — replace `_estimate_tokens()` implementation

**Verification:** `SmartContextEngine._estimate_tokens()` returns same values as `ContextManager.estimate_tokens()` for the same input.

**Complexity:** Low (3 hours)

**Implementation notes (2025-07-15):**
- Both `_estimate_tokens()` and `estimate_tokens()` already use `count_tokens()` from `llm/tokens.py` (tiktoken)
- Fixed stale docstring in `context.py` ("heuristic: chars / 4" → "using tiktoken")
- Fixed `estimate_tokens()` to include `system_prompt`, `project_context`, and `_summary` in the count (was only counting `self.messages`, causing threshold undercount)
- Updated `test_events.py` to include `loop_start` and `perm_check` event types

---

### A.6 Add Prompt Caching for Static Sections ✅ DONE

**Why:** Static prompt sections (~1500 tokens) are rebuilt from scratch every session and sent to the LLM every iteration. This wastes tokens and latency.

**What was built:**

Added module-level cache `_STATIC_CACHE` + `_STATIC_CACHE_MODEL` in `system_prompt.py`. New function `get_static_prompt()` returns the cached static prompt, rebuilding only if the model changes (since `_adaptive_notes_section` depends on model tier). `build_system_prompt()` now calls `get_static_prompt()` instead of `build_static_prompt()` directly.

**Files modified:**
- `src/coding_agent/agent/system_prompt.py` — added `_STATIC_CACHE`, `_STATIC_CACHE_MODEL`, `get_static_prompt()`

**Verification:** `build_system_prompt()` with same model returns cached result. Debug logs show `static_prompt_cache_hit` on second call.

**Complexity:** Low (3 hours)

**Implementation notes (2025-07-15):**
- Cache invalidated when model name changes (affects adaptive tier notes)
- `build_static_prompt()` remains public for direct access if needed
- Cache is module-level (persists across AgentLoop instances in same process)

---

### A.2 Deduplicate Tool Result Processing ✅ DONE

**Why:** Lines 419-488 (parallel) and 491-599 (sequential) contained ~180 lines of nearly identical logic for processing tool results. This violated DRY and made maintenance error-prone.

**What was built:**

Extracted three shared methods:
1. `_resolve_permission_level(pc)` — permission lookup (replaces try/except KeyError in both paths)
2. `_emit_permission_deny(pc)` — yields permission denial events (shared by parallel and sequential)
3. `_finalize_tool_execution(pc, result, tool_duration_ms)` — post-execute processing: emit event, add to context, run side effects

Both parallel and sequential paths now call these shared methods. Code is ~60 lines shorter.

**Files modified:**
- `src/coding_agent/agent/loop.py` — extracted shared methods, simplified both paths

**Verification:** All 153 tests pass. No behavioral change.

**Complexity:** Medium (6 hours)

**Implementation notes (2025-07-15):**
- `_finalize_tool_execution()` is an async generator (yields events from `_post_tool_actions`)
- Parallel path calls `_finalize_tool_execution()` in a loop after `asyncio.gather()`
- Sequential path calls it inline after each tool execution

---

### A.3 Integrate SmartContextEngine into Loop ✅ DONE

**Why:** `SmartContextEngine.select_context()` was defined (262 lines) but only called at 70% context usage, and injected as a user message instead of a system message.

**What was built:**

1. Added `_context_summary` field to `ContextManager` with `set_context_summary()` method
2. `build_messages()` now includes `_context_summary` as a system message after the system prompt
3. `estimate_tokens()` now includes `_context_summary` in the count
4. `loop.py` now always calls `select_context()` (not gated on 70%) with `include_error_context`, `include_verification`, `include_plan` params
5. Selected context injected via `set_context_summary()` instead of `add_user_message()`

**Files modified:**
- `src/coding_agent/agent/context.py` — added `_context_summary`, `set_context_summary()`, updated `build_messages()` and `estimate_tokens()`
- `src/coding_agent/agent/loop.py` — always call `select_context()` with full params, use `set_context_summary()`

**Verification:** All 153 tests pass. Debug logs show `context_engine_selection` events with error/verification/plan slices.

**Complexity:** Medium (8 hours)

**Implementation notes (2025-07-15):**
- Context summary is injected as `[Context Summary]\n{content}` system message
- Capped at 2000 chars to avoid overwhelming the LLM
- `select_context()` returns empty list when no error/verification/plan context exists

---

### A.4 Fix Summarization Fire-and-Forget ✅ DONE

**Why:** `asyncio.create_task(self._summarize_context())` created background tasks that might not complete before the next iteration, or might conflict with each other (two summarizations running simultaneously).

**What was built:**

Added `asyncio.Lock` (`_summarize_lock`) to prevent concurrent summarization. At 95% threshold, `_check_context_usage()` now `await`s summarization under lock instead of fire-and-forget. `_spawn_summarize()` checks `self._summarize_lock.locked()` to skip if already in progress. `_check_context_usage()` is now `async`.

**Files modified:**
- `src/coding_agent/agent/loop.py` — added `_summarize_lock`, `_summarize_with_lock()`, updated `_check_context_usage()` to async

**Verification:** All 153 tests pass. Concurrent summarization attempts are serialized.

**Complexity:** Low (4 hours)

**Implementation notes (2025-07-15):**
- Lock is non-reentrant (skips if already held)
- 95% threshold awaits summarization (blocking), 85% threshold was removed in favor of always using lock
- `_summarize_with_lock()` wraps `_summarize_context()` with lock acquisition

---

### A.6 Add Prompt Caching for Static Sections

**Why:** Static prompt sections (~1500 tokens) are rebuilt from scratch every session and sent to the LLM every iteration. This wastes tokens and latency.

**What to build:**

Cache the static prompt string and only rebuild dynamic sections:

```python
# In system_prompt.py
_STATIC_CACHE: str | None = None
_STATIC_CACHE_MODEL: str | None = None

def get_static_prompt(model: str = "") -> str:
    """Return cached static prompt, rebuilding only if model changes."""
    global _STATIC_CACHE, _STATIC_CACHE_MODEL
    if _STATIC_CACHE is None or _STATIC_CACHE_MODEL != model:
        _STATIC_CACHE = build_static_prompt(model=model)
        _STATIC_CACHE_MODEL = model
    return _STATIC_CACHE

def build_system_prompt(
    model: str = "",
    provider: str = "",
    workspace: Path | None = None,
    memory_content: str = "",
    plan_prompt: str = "",
    workspace_index_summary: str = "",
) -> str:
    """Build the complete system prompt with cached static section."""
    static = get_static_prompt(model=model)  # Cached
    
    # Dynamic sections (rebuilt each time)
    dynamic_parts: list[str] = []
    # ... existing dynamic section logic ...
    
    if dynamic_parts:
        dynamic = "\n\n".join(dynamic_parts)
        result = f"{static}\n\n{DYNAMIC_BOUNDARY}\n\n{dynamic}"
    else:
        result = static
    
    return result
```

For Gemini: use `cached_content` parameter in `GenerateContentConfig` when available.

**Files to modify:**
- `src/coding_agent/agent/system_prompt.py` — add static cache

**Verification:** Second call to `build_system_prompt()` with same model returns faster. Debug logs show cache hit.

**Complexity:** Medium (8 hours)

---

## 3. Phase B: Intelligence Layer ✅ COMPLETE

**Goal:** Add reflection, automatic replanning, and outcome assessment.

**Duration:** Week 3-5 (4 working days)
**Expected score after:** 6.5 → 7.5/10

- [x] B.1 Add reflection hook after tool use (signal-only, no suggestions)
- [x] B.2 Add automatic replanning
- [x] B.3 Add outcome assessment
- [x] B.4 Add progress evaluation

---

### B.1 Add Reflection Hook After Tool Use ✅ DONE

**Why:** Agent never evaluates whether its actions achieved the intended goal. This is the biggest gap in the system (Reflection: 1/10).

**What was built:**

New module `agent/reflector.py` with:
- `Assessment` enum (SUCCESS/PARTIAL/FAILURE/UNEXPECTED)
- `ReflectionResult` dataclass (assessment, reason, confidence) — signal-only, no suggestions
- `Reflector` class with rule-based heuristics: file not found, permission denied, syntax error, consecutive failures, search no results, etc.
- `REFLECTION` event type added to `events.py`
- TUI rendering in `main.py` (both clean and raw formats)

Integration in `loop.py`:
- `Reflector` initialized in `AgentLoop.__init__`
- `_post_tool_actions()` calls `reflector.reflect_on_tool()` after each tool execution
- Yields `REFLECTION` event with assessment, reason, confidence

**Files created/modified:**
- `src/coding_agent/agent/reflector.py` (NEW — ~230 lines)
- `src/coding_agent/agent/loop.py` — integrate reflector
- `src/coding_agent/agent/events.py` — add REFLECTION event type
- `src/coding_agent/main.py` — render REFLECTION events
- `tests/test_agent/test_reflector.py` (NEW — 26 tests)

**Verification:** All 26 reflector tests pass. Live test shows `[Reflect: search_content -> partial: No search results found]`.

**Complexity:** High (12 hours) — done 2025-07-16

---

### B.2 Add Automatic Replanning ✅ DONE

**Why:** `PlanManager.needs_replan()` detects failed steps but doesn't act on it.

**What was built:**

1. `PlanManager.replace_plan(plan)` — replaces current plan with a new one
2. `AgentLoop._generate_replan()` — uses LLM to generate a new plan when a step fails, with structured JSON prompt
3. `AgentLoop._parse_plan_response(content)` — parses LLM response into Plan object, handles markdown-wrapped JSON
4. Wired into the `needs_replan()` check: auto-generates new plan, updates system prompt, emits `PLAN_UPDATE` with `action: "replanned"`

**Files modified:**
- `src/coding_agent/agent/planner.py` — added `replace_plan()`, fixed `create_plan()` return
- `src/coding_agent/agent/loop.py` — added `_generate_replan()`, `_parse_plan_response()`, wired into needs_replan check
- `tests/test_agent/test_replan_and_progress.py` (NEW)

**Verification:** All planner + replan tests pass. Handles valid JSON, markdown-wrapped JSON, empty steps, invalid JSON.

**Complexity:** Medium (8 hours) — done 2025-07-16

---

### B.3 Add Outcome Assessment ✅ DONE

**Why:** No check whether tool results actually accomplished the goal.

**What was built:**

Extended `Reflector` with `assess_outcome()` method:
- Takes optional `expected_outcome` and `llm_client` params
- If no expected outcome or no LLM client → falls back to rule-based `reflect_on_tool()`
- If both provided → sends expected vs actual to LLM, parses JSON response
- Handles markdown-wrapped JSON, falls back to heuristics on LLM failure

**Files modified:**
- `src/coding_agent/agent/reflector.py` — added `assess_outcome()`
- `tests/test_agent/test_reflector.py` — added 6 outcome assessment tests

**Verification:** All outcome assessment tests pass. LLM-based and heuristic paths both tested.

**Complexity:** Medium (6 hours) — done 2025-07-16

---

### B.4 Add Progress Evaluation ✅ DONE

**Why:** No periodic assessment of task progress vs plan.

**What was built:**

1. `_evaluate_progress()` — returns completed/failed/total counts, progress_ratio, is_stalled flag, cost_per_step, elapsed time
2. Runs every N iterations (default 5) after tool execution
3. Emits `STUCK_DETECTED` event when stalled (tool_count > 0 and error_tracker.is_stuck())
4. Configurable via `_progress_eval_interval`

**Files modified:**
- `src/coding_agent/agent/loop.py` — added `_evaluate_progress()`, wired into iteration loop
- `tests/test_agent/test_replan_and_progress.py` — 4 progress evaluation tests

**Verification:** All progress evaluation tests pass. Handles all-done, partial, stalled, and no-plan scenarios.

**Complexity:** Low (4 hours) — done 2025-07-16

---

## 4. Phase C: Context Compression

**Goal:** Add intelligent context management beyond summarization.

**Duration:** Week 6-7 (3 working days)
**Expected score after:** 7.5 → 8.0/10

- [ ] C.1 Add message deduplication
- [ ] C.2 Add importance-based pruning
- [ ] C.3 Add hard context cutoff
- [ ] C.4 Add context window sliding

---

### C.1 Add Message Deduplication

**Why:** Same information can appear multiple times (e.g., file read twice, same error repeated). This wastes context budget.

**What to build:**

Before building messages, deduplicate near-identical messages:

```python
# In context.py
def deduplicate_messages(self) -> None:
    """Remove near-duplicate messages from history.
    
    Keeps the most recent version of each unique message.
    """
    seen: dict[str, int] = {}  # fingerprint -> index
    deduped: list[ConversationMessage] = []
    
    for i, msg in enumerate(self.messages):
        # Create fingerprint from role + first 200 chars
        fingerprint = f"{msg.role}:{msg.content[:200]}"
        
        if fingerprint in seen:
            # Replace old occurrence with new one
            old_idx = seen[fingerprint]
            # Find and remove old message from deduped
            deduped = [d for j, d in enumerate(deduped) if j != old_idx]
            # But this breaks indices... simpler approach:
            continue  # Skip duplicate, keep earlier version
        else:
            seen[fingerprint] = len(deduped)
            deduped.append(msg)
    
    # Actually, simpler: just skip duplicates, keep first occurrence
    self.messages = deduped
```

Wait, better approach — keep the **most recent** version:

```python
def deduplicate_messages(self) -> int:
    """Remove near-duplicate messages, keeping the most recent.
    
    Returns the number of messages removed.
    """
    if len(self.messages) <= 1:
        return 0
    
    # Build fingerprint -> last index mapping
    fingerprint_to_last_idx: dict[str, int] = {}
    for i, msg in enumerate(self.messages):
        fingerprint = f"{msg.role}:{msg.content[:200]}"
        fingerprint_to_last_idx[fingerprint] = i
    
    # Keep messages that are either unique or the last occurrence
    indices_to_keep = set(fingerprint_to_last_idx.values())
    # Always keep first message
    indices_to_keep.add(0)
    
    original_count = len(self.messages)
    self.messages = [
        msg for i, msg in enumerate(self.messages)
        if i in indices_to_keep
    ]
    
    return original_count - len(self.messages)
```

**Files to modify:**
- `src/coding_agent/agent/context.py` — add `deduplicate_messages()`

**Verification:** After reading the same file twice, only one copy remains in context.

**Complexity:** Medium (6 hours)

---

### C.2 Add Importance-Based Pruning

**Why:** All messages treated equally; no priority-based selection when context is full.

**What to build:**

Score messages by importance and prune low-priority ones:

```python
# In context.py
def _score_message_importance(
    self, msg: ConversationMessage, index: int
) -> float:
    """Score a message's importance (0.0 - 1.0).
    
    Higher score = more important to keep.
    """
    score = 0.5  # Base score
    
    # Role-based scoring
    if msg.role == "user":
        score += 0.3  # User messages are important
    elif msg.role == "assistant" and msg.tool_calls:
        score += 0.2  # Tool-calling messages show intent
    elif msg.role == "tool":
        score -= 0.1  # Tool results are less important than intent
    
    # Content-based scoring
    if msg.content:
        content_lower = msg.content.lower()
        # Error messages are important
        if "error" in content_lower or "failed" in content_lower:
            score += 0.1
        # File paths are important
        if "/" in msg.content or "\\" in msg.content:
            score += 0.05
    
    # Recency scoring (more recent = more important)
    recency = index / max(len(self.messages), 1)
    score += recency * 0.3
    
    return min(score, 1.0)

def prune_by_importance(self, target_tokens: int) -> int:
    """Prune messages to fit within token budget, keeping important ones.
    
    Returns the number of messages removed.
    """
    current_tokens = self.estimate_tokens()
    if current_tokens <= target_tokens:
        return 0
    
    # Score all messages
    scored = [
        (i, self._score_message_importance(msg, i))
        for i, msg in enumerate(self.messages)
    ]
    
    # Sort by importance (lowest first)
    scored.sort(key=lambda x: x[1])
    
    # Remove least important until we fit
    removed = 0
    for idx, score in scored:
        if current_tokens <= target_tokens:
            break
        msg = self.messages[idx]
        msg_tokens = count_tokens(msg.content)
        self.messages.pop(idx)
        current_tokens -= msg_tokens
        removed += 1
    
    return removed
```

**Files to modify:**
- `src/coding_agent/agent/context.py` — add `_score_message_importance()`, `prune_by_importance()`

**Verification:** When context is 90% full, pruning removes low-priority tool results before user messages.

**Complexity:** Medium (8 hours)

---

### C.3 Add Hard Context Cutoff

**Why:** No hard limit; context can grow until summarization catches up. If summarization fails, context overflows.

**What to build:**

When context exceeds hard limit (95%), drop oldest non-essential messages:

```python
# In context.py
def hard_cutoff(self, max_tokens: int) -> int:
    """Drop oldest messages when context exceeds hard limit.
    
    Never drops: system prompt, summary, last 5 messages.
    Returns the number of messages removed.
    """
    current_tokens = self.estimate_tokens()
    if current_tokens <= max_tokens:
        return 0
    
    removed = 0
    # Drop from the middle (after summary, before recent 5)
    # Never drop system messages or the last 5 conversation messages
    
    # Find droppable range (skip system messages at start, keep last 5)
    start_idx = 0
    for i, msg in enumerate(self.messages):
        if msg.role != "system":
            start_idx = i
            break
    
    end_idx = max(len(self.messages) - 5, start_idx)
    
    # Drop from start of droppable range
    while current_tokens > max_tokens and start_idx < end_idx:
        msg = self.messages[start_idx]
        msg_tokens = count_tokens(msg.content)
        self.messages.pop(start_idx)
        current_tokens -= msg_tokens
        removed += 1
        end_idx -= 1
    
    return removed
```

**Files to modify:**
- `src/coding_agent/agent/context.py` — add `hard_cutoff()`

**Verification:** When context exceeds 95%, oldest non-essential messages are dropped.

**Complexity:** Low (4 hours)

---

### C.4 Add Context Window Sliding

**Why:** Summarization keeps last 5 messages; everything else is summarized. This is too aggressive for long sessions.

**What to build:**

Implement a sliding window with configurable size:

```python
# In context.py
def slide_window(self, keep_recent: int = 10) -> int:
    """Keep only the most recent messages, summarize the rest.
    
    Returns the number of messages summarized.
    """
    if len(self.messages) <= keep_recent:
        return 0
    
    old = self.messages[:-keep_recent]
    self.messages = self.messages[-keep_recent:]
    
    # Format old messages for summarization
    old_text = self.format_old_messages()
    if old_text:
        # Store for summarization (will be summarized by LLM)
        self._pending_summarization = old_text
    
    return len(old)
```

**Files to modify:**
- `src/coding_agent/agent/context.py` — add `slide_window()`

**Verification:** After 20 messages, only the last 10 remain; the rest are queued for summarization.

**Complexity:** Low (6 hours)

---

## 5. Phase D: Memory Enhancement

**Goal:** Make memory smarter and more persistent.

**Duration:** Week 8-9 (3 working days)
**Expected score after:** 8.0 → 8.5/10

- [ ] D.1 Add memory consolidation
- [ ] D.2 Add importance scoring for memories
- [ ] D.3 Persist plans across sessions
- [ ] D.4 Add memory pruning

---

### D.1 Add Memory Consolidation

**Why:** Memories accumulate without merging; old memories become stale and irrelevant.

**What to build:**

Periodically consolidate similar memories:

```python
# In memory.py
async def consolidate(self, workspace: str) -> int:
    """Merge similar memories, remove stale ones.
    
    Returns the number of memories consolidated.
    """
    memories = await self.recall(workspace=workspace, limit=100)
    if len(memories) < 5:
        return 0
    
    # Group by similarity (keyword-based)
    groups = self._group_by_similarity(memories)
    
    consolidated = 0
    for group in groups:
        if len(group) > 1:
            merged = self._merge_memories(group)
            await self.store(
                merged,
                memory_type="semantic",
                workspace=workspace,
                tags=["consolidated"],
            )
            for mem in group:
                await self.delete(mem.id)
            consolidated += len(group) - 1
    
    return consolidated

def _group_by_similarity(
    self, memories: list[MemoryRecord]
) -> list[list[MemoryRecord]]:
    """Group memories by keyword similarity."""
    groups: dict[str, list[MemoryRecord]] = {}
    
    for mem in memories:
        # Extract keywords (simple: words > 4 chars)
        words = set(mem.content.lower().split())
        keywords = frozenset(w for w in words if len(w) > 4)
        
        # Find existing group with most overlap
        best_group = None
        best_overlap = 0
        for key, group in groups.items():
            key_words = frozenset(key.split())
            overlap = len(keywords & key_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_group = key
        
        if best_group and best_overlap >= 2:
            groups[best_group].append(mem)
        else:
            groups[" ".join(sorted(keywords)[:5])] = [mem]
    
    return list(groups.values())

def _merge_memories(self, memories: list[MemoryRecord]) -> str:
    """Merge multiple memories into one."""
    # Take the most recent version of each unique piece of info
    seen = set()
    parts = []
    for mem in sorted(memories, key=lambda m: m.id or 0, reverse=True):
        # Simple deduplication
        content = mem.content.strip()
        if content not in seen:
            seen.add(content)
            parts.append(content)
    
    return " | ".join(parts[:3])  # Keep top 3 unique pieces
```

**Files to modify:**
- `src/coding_agent/agent/memory.py` — add `consolidate()`, `_group_by_similarity()`, `_merge_memories()`

**Verification:** After storing 10 similar memories, consolidation reduces them to 2-3 merged memories.

**Complexity:** Medium (8 hours)

---

### D.2 Add Importance Scoring for Memories

**Why:** All memories treated equally; no relevance ranking for retrieval.

**What to build:**

Score memories by recency, access frequency, and specificity:

```python
# In memory.py
def _score_memory(self, memory: MemoryRecord) -> float:
    """Score a memory's importance (0.0 - 1.0)."""
    score = 0.5  # Base score
    
    # Recency (newer = more important)
    if memory.created_at:
        age_days = (datetime.now() - memory.created_at).days
        score += max(0, 0.3 - age_days * 0.01)
    
    # Type bonus
    if memory.memory_type == "semantic":
        score += 0.2  # Facts are more important than summaries
    elif memory.memory_type == "episodic":
        score += 0.1  # Session summaries are useful
    
    # Specificity (more specific = more important)
    content = memory.content or ""
    if len(content) > 50:
        score += 0.1  # Detailed memories are more useful
    if ":" in content or "/" in content:
        score += 0.05  # File paths are specific
    
    return min(score, 1.0)

async def recall_ranked(
    self,
    query: str = "",
    *,
    workspace: str = "",
    limit: int = 10,
) -> list[MemoryRecord]:
    """Recall memories ranked by importance."""
    memories = await self.recall(
        query=query, workspace=workspace, limit=limit * 2
    )
    
    # Score and sort
    scored = [(m, self._score_memory(m)) for m in memories]
    scored.sort(key=lambda x: x[1], reverse=True)
    
    return [m for m, _ in scored[:limit]]
```

**Files to modify:**
- `src/coding_agent/agent/memory.py` — add `_score_memory()`, `recall_ranked()`

**Verification:** More recent, specific memories are returned first in recall results.

**Complexity:** Low (4 hours)

---

### D.3 Persist Plans Across Sessions

**Why:** Plans are lost on session reset. If the user resumes a session, the plan is gone.

**What to build:**

Save/load plans via SessionManager:

```python
# In planner.py
async def save_plan(
    self, session_manager: Any, session_id: str
) -> None:
    """Save the current plan to the database."""
    if self._plan is None:
        return
    
    plan_data = self._plan.to_dict()
    await session_manager.save_operation(
        session_id,
        "plan_save",
        {"plan": plan_data},
        json.dumps(plan_data),
        success=True,
    )

async def load_plan(
    self, session_manager: Any, session_id: str
) -> bool:
    """Load a plan from the database.
    
    Returns True if a plan was loaded.
    """
    operations = await session_manager.get_operations(session_id)
    for op in operations:
        if op.tool_name == "plan_save":
            try:
                plan_data = json.loads(op.output)
                self._plan = Plan(
                    goal=plan_data["goal"],
                    steps=[
                        PlanStep(
                            description=s["description"],
                            status=StepStatus(s["status"]),
                            result=s.get("result", ""),
                        )
                        for s in plan_data["steps"]
                    ],
                    current_step=plan_data.get("current_step", 0),
                    status=PlanStatus(plan_data["status"]),
                )
                return True
            except (json.JSONDecodeError, KeyError) as e:
                logger.error("plan_load_failed", error=str(e))
    return False
```

**Integration in loop.py:**

```python
# At session start, try to load existing plan
if self.session_manager and self.session_id:
    loaded = await self.plan_manager.load_plan(
        self.session_manager, self.session_id
    )
    if loaded:
        logger.info("plan_loaded_from_session", session_id=self.session_id)

# At session end, save plan
if self.session_manager and self.session_id and self.plan_manager.has_plan:
    await self.plan_manager.save_plan(
        self.session_manager, self.session_id
    )
```

**Files to modify:**
- `src/coding_agent/agent/planner.py` — add `save_plan()`, `load_plan()`
- `src/coding_agent/agent/loop.py` — load/save plan at session boundaries

**Verification:** Create a plan, reset session, load session — plan is restored.

**Complexity:** Medium (6 hours)

---

### D.4 Add Memory Pruning

**Why:** Old memories accumulate without cleanup; retrieval gets slower and less relevant.

**What to build:**

Remove old, low-importance memories:

```python
# In memory.py
async def prune(
    self,
    workspace: str,
    max_memories: int = 100,
    max_age_days: int = 90,
) -> int:
    """Remove old, low-importance memories.
    
    Returns the number of memories pruned.
    """
    memories = await self.recall(workspace=workspace, limit=1000)
    
    if len(memories) <= max_memories:
        return 0
    
    # Score and sort by importance
    scored = [(m, self._score_memory(m)) for m in memories]
    scored.sort(key=lambda x: x[1])
    
    # Remove oldest, least important
    pruned = 0
    for mem, score in scored:
        if len(memories) - pruned <= max_memories:
            break
        
        # Check age
        if mem.created_at:
            age_days = (datetime.now() - mem.created_at).days
            if age_days > max_age_days:
                await self.delete(mem.id)
                pruned += 1
    
    return pruned
```

**Files to modify:**
- `src/coding_agent/agent/memory.py` — add `prune()`

**Verification:** After 100+ memories, pruning reduces to 100.

**Complexity:** Low (4 hours)

---

## 6. Phase E: Production Hardening

**Goal:** Complete the existing Phase 4 plan items.

**Duration:** Week 10-12 (6 working days)
**Expected score after:** 8.5 → 9.0/10

- [ ] E.1 Sub-agent delegation
- [ ] E.2 Telemetry/observability
- [ ] E.3 Integration test suite
- [ ] E.4 Documentation update

---

### E.1 Sub-Agent Delegation

**Why:** Complex tasks benefit from parallel sub-agents. One agent can't do everything.

**What to build:**

New module `agent/subagent.py`:

```python
"""Sub-agent orchestration for parallel task execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from coding_agent.logging import logger


@dataclass
class SubAgentTask:
    """A task to be executed by a sub-agent."""
    task_id: str
    description: str
    tools: list[str]  # Tools the sub-agent can use
    context: str  # Additional context for the sub-agent


@dataclass
class SubAgentResult:
    """Result from a sub-agent execution."""
    task_id: str
    success: bool
    output: str
    error: str = ""


class SubAgentManager:
    """Manages spawning and coordinating sub-agents."""
    
    def __init__(
        self,
        llm_client: Any,
        permission_manager: Any,
        max_concurrent: int = 3,
    ) -> None:
        self._llm_client = llm_client
        self._permission_manager = permission_manager
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute_task(
        self,
        task: SubAgentTask,
        workspace: Any,
    ) -> SubAgentResult:
        """Execute a single sub-agent task."""
        async with self._semaphore:
            # Create isolated context for sub-agent
            from coding_agent.agent.context import ContextManager
            from coding_agent.agent.loop import AgentLoop
            
            context = ContextManager(max_tokens=50_000)
            sub_agent = AgentLoop(
                llm_client=self._llm_client,
                permission_manager=self._permission_manager,
                context_manager=context,
                workspace=workspace,
                max_iterations=10,
            )
            
            # Execute
            output_parts = []
            async for event in sub_agent.process_input(task.description):
                if event.type.value == "text":
                    output_parts.append(str(event.data))
            
            return SubAgentResult(
                task_id=task.task_id,
                success=True,
                output="".join(output_parts),
            )
    
    async def execute_parallel(
        self,
        tasks: list[SubAgentTask],
        workspace: Any,
    ) -> list[SubAgentResult]:
        """Execute multiple tasks in parallel."""
        coros = [self.execute_task(t, workspace) for t in tasks]
        results = await asyncio.gather(*coros, return_exceptions=True)
        
        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append(SubAgentResult(
                    task_id=tasks[i].task_id,
                    success=False,
                    output="",
                    error=str(result),
                ))
            else:
                processed.append(result)
        
        return processed
```

**Integration in loop.py:**

```python
# Add sub-agent tool
@tool(name="spawn_subagent", description="Spawn a sub-agent for parallel work", permission="execute")
async def spawn_subagent(description: str, context: str = "") -> str:
    """Spawn a sub-agent to work on a subtask in parallel."""
    task = SubAgentTask(
        task_id=f"sub_{int(time.time())}",
        description=description,
        tools=["read_file", "search_content", "search_files"],
        context=context,
    )
    result = await _subagent_manager.execute_task(task, _workspace)
    return result.output if result.success else f"Error: {result.error}"
```

**Files to create/modify:**
- `src/coding_agent/agent/subagent.py` (NEW — ~200 lines)
- `src/coding_agent/tools/subagent.py` (NEW — ~50 lines)
- `src/coding_agent/agent/loop.py` — initialize SubAgentManager
- `tests/test_agent/test_subagent.py` (NEW)

**Verification:** Agent spawns a research sub-agent while making edits in parallel.

**Complexity:** High (20 hours)

---

### E.2 Telemetry/Observability

**Why:** No visibility into agent behavior in production.

**What to build:**

New module `agent/telemetry.py`:

```python
"""Structured telemetry for agent actions."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from coding_agent.logging import logger


@dataclass
class TelemetryEvent:
    """A single telemetry event."""
    timestamp: float
    event_type: str
    data: dict[str, Any]
    duration_ms: float = 0.0


class TelemetryCollector:
    """Collects and exports telemetry events."""
    
    def __init__(self, export_path: str | None = None) -> None:
        self._events: list[TelemetryEvent] = []
        self._export_path = export_path
    
    def record(
        self,
        event_type: str,
        data: dict[str, Any],
        duration_ms: float = 0.0,
    ) -> None:
        """Record a telemetry event."""
        event = TelemetryEvent(
            timestamp=time.time(),
            event_type=event_type,
            data=data,
            duration_ms=duration_ms,
        )
        self._events.append(event)
        
        # Log for immediate visibility
        logger.debug(
            "telemetry",
            event_type=event_type,
            duration_ms=round(duration_ms, 1),
            **{k: v for k, v in data.items() if isinstance(v, (str, int, float, bool))},
        )
    
    def export(self) -> None:
        """Export events to file."""
        if not self._export_path:
            return
        
        path = Path(self._export_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "a") as f:
            for event in self._events:
                f.write(json.dumps(asdict(event)) + "\n")
        
        self._events.clear()
    
    def get_summary(self) -> dict[str, Any]:
        """Get summary of recorded events."""
        if not self._events:
            return {}
        
        event_counts = {}
        total_duration = 0.0
        
        for event in self._events:
            event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1
            total_duration += event.duration_ms
        
        return {
            "total_events": len(self._events),
            "event_counts": event_counts,
            "total_duration_ms": round(total_duration, 1),
        }
```

**Integration in loop.py:**

```python
# In AgentLoop.__init__
from coding_agent.agent.telemetry import TelemetryCollector
self.telemetry = TelemetryCollector(
    export_path=str(self.workspace / ".coding-agent" / "telemetry.jsonl")
)

# Throughout loop.py
self.telemetry.record("llm_call", {
    "model": self.llm_client.model,
    "tokens": usage.total_tokens,
}, duration_ms=latency_ms)

self.telemetry.record("tool_call", {
    "tool": pc["name"],
    "success": result.success,
}, duration_ms=tool_duration_ms)
```

**Files to create/modify:**
- `src/coding_agent/agent/telemetry.py` (NEW — ~150 lines)
- `src/coding_agent/agent/loop.py` — integrate telemetry
- `src/coding_agent/config.py` — add `telemetry_path` setting

**Verification:** JSON log file contains structured entries for every tool call.

**Complexity:** Medium (8 hours)

---

### E.3 Integration Test Suite

**Why:** No end-to-end tests. Can't verify the full system works.

**What to build:**

New directory `tests/integration/` with end-to-end scenarios:

```python
# tests/integration/test_full_flow.py

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_read_file_flow():
    """User asks to read a file → agent reads it → returns content."""
    # Setup mocked LLM
    mock_llm = AsyncMock()
    mock_llm.stream = AsyncMock(return_value=aiter([
        StreamEvent(type=StreamEventType.TEXT, data="Let me read the file."),
        StreamEvent(type=StreamEventType.TOOL_CALL, data={
            "id": "call_0",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path": "test.py"}'}
        }),
        StreamEvent(type=StreamEventType.DONE),
    ]))
    
    # Setup agent
    agent = AgentLoop(
        llm_client=mock_llm,
        permission_manager=PermissionManager(),
        context_manager=ContextManager(),
        workspace=Path("."),
    )
    
    # Execute
    events = []
    async for event in agent.process_input("Read test.py"):
        events.append(event)
    
    # Verify
    assert any(e.type == EventType.TOOL_START for e in events)
    assert any(e.type == EventType.DONE for e in events)
```

**Files to create:**
- `tests/integration/test_full_flow.py` (NEW)
- `tests/integration/test_planning_flow.py` (NEW)
- `tests/integration/test_error_recovery_flow.py` (NEW)
- `tests/integration/conftest.py` (NEW)

**Verification:** `pytest tests/integration/` passes all end-to-end scenarios.

**Complexity:** High (12 hours)

---

### E.4 Documentation Update

**Why:** Documentation is outdated (references planned architecture, not actual implementation).

**What to build:**

Update documentation to reflect actual architecture:

```markdown
# docs/architecture.md (REWRITE)

## Current Architecture

The system follows an observe-think-act-repeat agentic loop...

### Components

1. **AgentLoop** — Core orchestrator (842 lines)
2. **LLMClient** — Multi-provider LLM abstraction
3. **ContextManager** — Conversation history management
4. **ToolRegistry** — Tool registration and dispatch
5. **SmartContextEngine** — Prioritized context selection
6. **Reflector** — Post-action reflection
7. **PlanManager** — Structured task decomposition
8. **ErrorTracker** — Stuck detection and recovery
9. **MemoryManager** — Cross-session memory
10. **PostEditVerifier** — Code quality checks
```

**Files to create/modify:**
- `docs/architecture.md` (REWRITE)
- `docs/development.md` (NEW)
- `docs/tools.md` (NEW)

**Verification:** New contributor can set up and run the project in <10 minutes.

**Complexity:** Medium (8 hours)

---

## 7. Dependency Graph

```
Phase A (Foundation Fixes)
  ├── A.1 Permission bypass fix
  ├── A.2 Deduplicate tool processing ←── enables A.3
  ├── A.3 SmartContextEngine integration ←── depends on A.2
  ├── A.4 Fix summarization fire-and-forget
  ├── A.5 Unify token estimation
  └── A.6 Prompt caching

Phase B (Intelligence Layer)  ←── depends on Phase A
  ├── B.1 Reflection hook ←── depends on A.2, A.3
  ├── B.2 Automatic replanning ←── depends on B.1
  ├── B.3 Outcome assessment ←── depends on B.1
  └── B.4 Progress evaluation ←── depends on B.2

Phase C (Context Compression)  ←── depends on Phase A
  ├── C.1 Message deduplication ←── depends on A.3
  ├── C.2 Importance-based pruning ←── depends on A.3
  ├── C.3 Hard context cutoff ←── depends on C.1, C.2
  └── C.4 Context window sliding ←── depends on C.3

Phase D (Memory Enhancement)  ←── depends on Phase 3.1 (existing)
  ├── D.1 Memory consolidation
  ├── D.2 Importance scoring ←── depends on D.1
  ├── D.3 Plan persistence ←── depends on Phase 2.2 (existing)
  └── D.4 Memory pruning ←── depends on D.2

Phase E (Production Hardening)  ←── depends on Phase B
  ├── E.1 Sub-agents
  ├── E.2 Telemetry
  ├── E.3 Integration tests
  └── E.4 Documentation
```

---

## 8. Effort Summary

| Phase | Duration | Complexity | Score Impact |
|-------|----------|------------|--------------|
| Phase A: Foundation Fixes | 4 days | Low-Medium | 5.6 → 6.5 |
| Phase B: Intelligence Layer | 4 days | Medium-High | 6.5 → 7.5 |
| Phase C: Context Compression | 3 days | Medium | 7.5 → 8.0 |
| Phase D: Memory Enhancement | 3 days | Medium | 8.0 → 8.5 |
| Phase E: Production Hardening | 6 days | Medium-High | 8.5 → 9.0 |
| **Total** | **20 days** | | **5.6 → 9.0** |

---

## 9. Priority Matrix

| Priority | Task | Effort | Impact | Risk |
|----------|------|--------|--------|------|
| P0 | A.1 Permission bypass fix | 3h | Critical (security) | Low |
| P0 | A.2 Deduplicate tool processing | 6h | High (code quality) | Low |
| P0 | A.4 Fix summarization fire-and-forget | 4h | High (reliability) | Low |
| P1 | A.3 SmartContextEngine integration | 8h | High (context mgmt) | Medium |
| P1 | A.5 Unify token estimation | 3h | Medium (accuracy) | Low |
| P1 | A.6 Prompt caching | 8h | High (cost) | Low |
| P2 | B.1 Reflection hook | 12h | Critical (intelligence) | High |
| P2 | B.2 Automatic replanning | 8h | High (planning) | Medium |
| P2 | B.3 Outcome assessment | 6h | High (quality) | Medium |
| P3 | C.1 Message deduplication | 6h | Medium (context) | Low |
| P3 | C.2 Importance-based pruning | 8h | Medium (context) | Medium |
| P3 | D.1 Memory consolidation | 8h | Medium (memory) | Medium |
| P4 | E.1 Sub-agents | 20h | High (parallelism) | High |
| P4 | E.2 Telemetry | 8h | Medium (debuggability) | Low |

---

## 10. Success Criteria

After all phases, the audit score should improve from **5.6/10** to **9.0/10**:

| Dimension | Current | Target |
|-----------|---------|--------|
| Core loop | 8/10 | 9/10 |
| Tool system | 8/10 | 9/10 |
| LLM integration | 7/10 | 8/10 |
| Context management | 5/10 | 8/10 |
| Memory | 5/10 | 7/10 |
| Planning | 4/10 | 7/10 |
| Reflection | 1/10 | 7/10 |
| Error recovery | 6/10 | 8/10 |
| Production readiness | 5/10 | 8/10 |
| Architecture | 7/10 | 9/10 |

### Verification Checklist

- [ ] All existing tests pass
- [ ] New tests added for each new component
- [ ] No security gaps (permission bypass fixed)
- [ ] No code duplication (tool processing deduplicated)
- [ ] SmartContextEngine actively used in loop
- [ ] Reflection produces actionable assessments
- [ ] Automatic replanning works when steps fail
- [ ] Context compression prevents overflow
- [ ] Memory consolidation runs periodically
- [ ] Plans persist across sessions
- [ ] Telemetry captures all key events
- [ ] Documentation reflects actual architecture

---

## Relationship to Existing Plan

This plan **supplements** the existing `implementation-plan.md`:

| Existing Phase | Status | Relationship |
|----------------|--------|--------------|
| Phase 1: Foundation | ✅ Complete | Foundation for this plan |
| Phase 2: Intelligence | ✅ Complete | Components built here are integrated in this plan |
| Phase 3: Memory | ✅ Complete | Enhanced in Phase D |
| Phase 4: Production | 🔄 In Progress | Phase E continues this work |
| Phase 5: Advanced | ⬜ Planned | Builds on top of this plan |

The existing plan focuses on **building new components**. This plan focuses on **integrating and hardening** what was built, addressing the gaps the audit revealed.
