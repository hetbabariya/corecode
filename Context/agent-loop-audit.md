# CoreCode Agent Loop Architecture Audit

**Date:** 2026-07-15
**Scope:** Complete audit of the CoreCode agent loop architecture
**Status:** Read-only analysis — no changes proposed

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [High-Level Architecture Diagram](#2-high-level-architecture-diagram)
3. [Agent Loop Walkthrough](#3-agent-loop-walkthrough)
4. [Component-by-Component Analysis](#4-component-by-component-analysis)
5. [State Management Analysis](#5-state-management-analysis)
6. [Tool Execution Pipeline](#6-tool-execution-pipeline)
7. [Prompt Assembly Flow](#7-prompt-assembly-flow)
8. [Memory Audit](#8-memory-audit)
9. [Planning Audit](#9-planning-audit)
10. [Reflection Audit](#10-reflection-audit)
11. [Context Management Audit](#11-context-management-audit)
12. [Orchestrator Audit](#12-orchestrator-audit)
13. [Feature Matrix](#13-feature-matrix)
14. [Missing Components](#14-missing-components)
15. [Technical Debt](#15-technical-debt)
16. [Bottlenecks](#16-bottlenecks)
17. [Risks](#17-risks)
18. [Strengths](#18-strengths)
19. [Weaknesses](#19-weaknesses)
20. [Readiness Score](#20-readiness-score)

---

## 1. Executive Summary

CoreCode is a Python 3.12+ AI coding agent built on an **observe-think-act-repeat** agentic loop. It integrates Gemini (primary) and OpenRouter (secondary) LLMs, 15+ registered tools, Docker sandbox execution, cross-session memory, structured planning, post-edit verification, and error recovery. The system is functional across Phases 1-3, with Phase 4 (production hardening) in progress.

**Key metrics:**

- 44 source files across 6 packages
- 842-line core agent loop (`loop.py`)
- 15 registered tools (9 parallel-safe, 6 sequential)
- Max 20 iterations, $5 cost cap, 300s time cap
- SQLite session persistence + cross-session memory
- Progressive context management (70%/85%/95% thresholds)

---

## 2. High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Input (CLI)                             │
│                    coding-agent run --prompt "..."                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                v
┌─────────────────────────────────────────────────────────────────────┐
│                     main.py (_run_agent)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ LLMClient    │  │PermissionMgr │  │ ContextManager           │  │
│  │ (Gemini/OR)  │  │              │  │ (messages, tokens, sum)  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────────┘  │
│         │                 │                      │                   │
│         v                 v                      v                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    AgentLoop (loop.py)                        │   │
│  │                     THE HEART — 842 lines                     │   │
│  │                                                               │   │
│  │  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐  │   │
│  │  │SmartContext  │ │ErrorTracker  │ │PlanManager           │  │   │
│  │  │Engine        │ │              │ │                      │  │   │
│  │  └─────────────┘ └──────────────┘ └──────────────────────┘  │   │
│  │                                                               │   │
│  │  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐  │   │
│  │  │UndoStack    │ │PostEdit      │ │WorkspaceIndex        │  │   │
│  │  │             │ │Verifier      │ │                      │  │   │
│  │  └─────────────┘ └──────────────┘ └──────────────────────┘  │   │
│  │                                                               │   │
│  │  ┌─────────────┐ ┌──────────────┐                            │   │
│  │  │MemoryManager│ │SessionManager│                            │   │
│  │  │(cross-sess) │ │(SQLite)      │                            │   │
│  │  └─────────────┘ └──────────────┘                            │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             │                                        │
│                             v                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    ToolRegistry (registry.py)                 │   │
│  │                                                               │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │   │
│  │  │file_ops  │ │search    │ │shell     │ │git           │   │   │
│  │  │read/write│ │content/  │ │execute   │ │status/diff/  │   │   │
│  │  │edit/list │ │files     │ │_command  │ │log/commit    │   │   │
│  │  │apply/multi│ │          │ │          │ │              │   │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │   │
│  │  │memory    │ │planning  │ │undo/redo │ │workspace     │   │   │
│  │  │remember/ │ │create/   │ │undo/redo │ │refresh_index │   │   │
│  │  │recall    │ │update    │ │          │ │              │   │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │   │
│  │  ┌──────────────┐                                           │   │
│  │  │count_tokens  │                                           │   │
│  │  └──────────────┘                                           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                             │                                        │
│                             v                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              SandboxExecutor (executor.py)                    │   │
│  │              DockerSandbox (docker.py)                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Agent Loop Walkthrough

**Entry:** `process_input(user_input)` — async generator yielding `AgentEvent`

**File:** `coding-agent/src/coding_agent/agent/loop.py:167-613`

### Step-by-Step Flow

```
1.  LOAD cross-session memory → rebuild system_prompt with memory content
2.  ADD user message to ContextManager
3.  INIT timers: _start_time, _accumulated_cost, _tool_count
4.  CREATE session in SessionManager (if available)
5.  PERSIST user message to SQLite
6.  LOG session_start event

    FOR iteration in range(max_iterations):   ← LINE 222

    7.  CHECK time budget → BUDGET_EXCEEDED if exceeded
    8.  CHECK cost budget → BUDGET_EXCEEDED if exceeded

    9.  IF plan_manager.has_plan:
        → REBUILD system_prompt with plan state
        → CHECK needs_replan() → emit PLAN_UPDATE event

    10. IF error_tracker.is_stuck():
        → IF strategy == ask_user → emit ASK_USER, RETURN
        → ELSE → emit STUCK_DETECTED

    11. BUILD messages = context.build_messages()
    12. GET tools = tool_registry.get_schemas()

    13. STREAM LLM response:
        → llm_client.stream(messages, tools)
        → Collect TEXT parts, TOOL_CALL parts, USAGE data
        → Accumulate cost from usage

    14. STORE assistant turn in context (content + tool_calls)
    15. PERSIST assistant message to SQLite

    16. IF no tool_calls → DONE:
        → Save episodic memory
        → Update session stats
        → yield DONE, RETURN

    17. PARSE tool_calls:
        → Extract name, args (JSON), id from each tool_call

    18. EMIT TOOL_START for all tools

    19. GROUP into parallel_batch + sequential_calls

    20. EXECUTE PARALLEL tools (asyncio.gather):
        → For each: tool_registry.execute_from_llm()
        → Process result (truncate, inject instructions)
        → Add tool result to context
        → Record in plan, error_tracker, context_engine
        → Persist operation to SQLite
        → Verify after edit (if applicable)

    21. EXECUTE SEQUENTIAL tools (one at a time):
        → Permission check (PermissionManager)
        → If denied → add denial message to context
        → If approved → tool_registry.execute_from_llm()
        → Same processing as parallel tools

    22. CHECK context budget (progressive thresholds):
        → 70%: warning log
        → 85%: trigger summarization (async task)
        → 95%: aggressive summarization + warning event

    END FOR

23. MAX_ITERATIONS exhausted → yield MAX_ITERATIONS
```

### Stopping Conditions

| Condition | Line | Behavior |
|-----------|------|----------|
| No tool calls from LLM | 352 | Normal completion, yields DONE |
| Time budget exceeded | 227 | Yields BUDGET_EXCEEDED, returns |
| Cost budget exceeded | 239 | Yields BUDGET_EXCEEDED, returns |
| Max iterations (20) | 604 | Yields MAX_ITERATIONS |
| Stuck + ask_user | 283 | Yields ASK_USER, returns |

### Retry Behavior

- No automatic retry on LLM failure (exceptions propagate)
- Key-pool rotation on 429/404 (in `LLMClient._call_with_rotation`)
- Error tracker suggests RETRY/ALTERNATIVE/REPLAN/ASK_USER strategies
- No explicit retry loop within an iteration

---

## 4. Component-by-Component Analysis

### 4.1 AgentLoop (`agent/loop.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Orchestrate the observe-think-act-repeat cycle |
| **Responsibilities** | Budget enforcement, LLM streaming, tool dispatch, result processing, context management, verification |
| **Inputs** | `user_input: str` |
| **Outputs** | `AsyncIterator[AgentEvent]` |
| **Dependencies** | LLMClient, ContextManager, PermissionManager, ToolRegistry, PlanManager, PostEditVerifier, ErrorTracker, SmartContextEngine, UndoStack, WorkspaceIndex, MemoryManager, SessionManager |
| **State** | `_start_time`, `_accumulated_cost`, `_tool_count`, `session_id` |
| **Lifecycle** | Created once per session, `reset()` clears all state |
| **Limitations** | Single-threaded orchestrator, no parallel LLM calls, no sub-agent delegation, no streaming of tool results back to LLM mid-iteration |

### 4.2 LLMClient (`llm/client.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Abstract LLM provider differences, handle streaming, key rotation |
| **Responsibilities** | Provider dispatch (Gemini/OpenRouter), message/tool format conversion, streaming, key-pool rotation, retry with backoff |
| **Inputs** | `messages: list[dict]`, `tools: list[dict]` |
| **Outputs** | `LLMResponse` (complete) or `AsyncIterator[StreamEvent]` (stream) |
| **State** | `total_usage`, `_current_api_key`, provider-specific clients |
| **Limitations** | Max output tokens hardcoded to 8192, no prompt caching, no Anthropic support, no multi-modal support |

### 4.3 ContextManager (`agent/context.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Manage conversation history, build message lists, handle summarization |
| **Responsibilities** | Store messages, build OpenAI-format message lists, estimate tokens, summarize old messages |
| **Inputs** | User/assistant/tool messages |
| **Outputs** | `list[dict]` for LLM consumption |
| **State** | `system_prompt`, `project_context`, `messages: list[ConversationMessage]`, `_summary` |
| **Limitations** | Summarization keeps only last 5 messages, no sliding window, no importance-based pruning |

### 4.4 SmartContextEngine (`agent/context_engine.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Prioritize context slices for each LLM iteration |
| **Responsibilities** | Select most relevant context (recent messages, tool results, errors, verification, plan) within token budget |
| **Inputs** | ContextManager, ErrorTracker |
| **Outputs** | `list[ContextSlice]` sorted by priority |
| **State** | `_last_tool_results` (10), `_verification_results` (5), `_pending_tool_calls` |
| **Limitations** | **Not actively used** — `select_context()` is defined but never called in the agent loop. The loop uses `context.build_messages()` directly. |

### 4.5 ToolRegistry (`tools/registry.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Register, lookup, and dispatch tool calls |
| **Responsibilities** | Schema generation (OpenAI format), argument parsing, execution dispatch, error wrapping |
| **State** | `_tools: dict[str, BaseTool]` |
| **Limitations** | No dynamic tool loading, no tool versioning, no tool composition |

### 4.6 PermissionManager (`agent/permissions.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Gate tool execution based on permission levels |
| **Responsibilities** | Check permissions, track session-level approvals |
| **State** | `level`, `_approved_writes: set[str]` |
| **Limitations** | WRITE auto-approves for rest of session after first approval, no per-file granularity, no user confirmation UI (only AutoApproveCallback currently) |

### 4.7 PlanManager (`agent/planner.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Structured task decomposition and progress tracking |
| **Responsibilities** | Create plans, track step status, detect replanning needs, serialize for prompt injection |
| **State** | `_plan: Plan | None` (single plan at a time) |
| **Limitations** | No automatic plan creation (LLM must call `create_plan` tool), no plan persistence across sessions, no priority scheduling |

### 4.8 PostEditVerifier (`agent/verifier.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Run syntax/lint/test checks after file edits |
| **Responsibilities** | Syntax check, lint check, test discovery and execution |
| **State** | Stateless (only holds `workspace` path) |
| **Limitations** | Only supports Python/JS/TS, no Rust/Go/Java support, test file discovery is heuristic |

### 4.9 ErrorTracker (`agent/error_recovery.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Detect stuck patterns, categorize errors, suggest recovery strategies |
| **Responsibilities** | Record tool calls, detect repetition, classify errors (transient/permanent/logic), escalate to ask_user |
| **State** | `_history` (deque, 10), `_consecutive_errors`, `_stuck_count`, `_ask_user_count` |
| **Limitations** | No automatic retry implementation, strategy is only advisory (not enforced) |

### 4.10 MemoryManager (`agent/memory.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Cross-session memory (episodic, semantic, working) |
| **Responsibilities** | Store/recall memories, format for prompt injection, session lifecycle |
| **State** | `_working: dict[str, str]` (ephemeral) |
| **Dependencies** | SessionManager (SQLite) |
| **Limitations** | No embedding-based retrieval, no importance scoring, no memory consolidation, working memory is single-key dict |

### 4.11 UndoStack (`agent/undo.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Track file mutations for undo/redo |
| **Responsibilities** | Push mutations, undo/redo, apply filesystem changes |
| **State** | `_undo_stack` (50 entries), `_redo_stack` |
| **Limitations** | In-memory only (lost on restart), no snapshot compression, full file content stored per entry |

### 4.12 WorkspaceIndex (`agent/workspace_index.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | File tree awareness and language detection |
| **Responsibilities** | Scan workspace, track files/languages, incremental updates |
| **State** | In-memory file tree |
| **Limitations** | No gitignore integration, no file content indexing, no symbol-level awareness |

### 4.13 SessionManager (`session/manager.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | SQLite persistence for sessions, messages, operations, memories |
| **Responsibilities** | Create/list/update sessions, save messages/operations, search/save memories |
| **State** | SQLite database |
| **Limitations** | No WAL mode, no connection pooling, no migration system |

### 4.14 SandboxExecutor (`sandbox/executor.py`)

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Route shell commands through Docker sandbox or host |
| **Responsibilities** | Execute commands, handle timeouts, format results |
| **Limitations** | Single container, no network isolation, no resource limits enforcement |

---

## 5. State Management Analysis

| State | Location | Scope | Persistence | Reset Behavior |
|-------|----------|-------|-------------|----------------|
| Conversation messages | `ContextManager.messages` | Session | SQLite (via SessionManager) | `context.clear()` |
| System prompt | `ContextManager.system_prompt` | Session | Rebuilt each session | Rebuilt |
| Summary | `ContextManager._summary` | Session | In-memory | `context.clear()` |
| Accumulated cost | `AgentLoop._accumulated_cost` | Session | In-memory | Per `process_input()` |
| Start time | `AgentLoop._start_time` | Session | In-memory | Per `process_input()` |
| Tool count | `AgentLoop._tool_count` | Session | In-memory | Per `process_input()` |
| Session ID | `AgentLoop.session_id` | Session | SQLite | `reset()` |
| Approved writes | `PermissionManager._approved_writes` | Session | In-memory | `reset()` |
| Plan state | `PlanManager._plan` | Session | In-memory | `reset()` |
| Error history | `ErrorTracker._history` | Session | In-memory (deque 10) | `reset()` |
| Stuck count | `ErrorTracker._stuck_count` | Session | In-memory | `reset()` |
| Tool results (smart) | `SmartContextEngine._last_tool_results` | Session | In-memory (10) | `clear_history()` |
| Verification results | `SmartContextEngine._verification_results` | Session | In-memory (5) | `clear_history()` |
| Working memory | `MemoryManager._working` | Session | In-memory | `clear_working()` |
| Undo stack | `UndoStack._undo_stack` + `_redo_stack` | Session | In-memory (50) | `clear()` |
| Workspace index | `WorkspaceIndex` | Session | In-memory | Rebuilt on init |
| Token usage | `LLMClient.total_usage` | Session | In-memory | Not reset |
| API key state | `LLMClient._current_api_key` | Session | In-memory | Not reset |
| Session DB | `SessionManager` | Persistent | SQLite file | Never |

---

## 6. Tool Execution Pipeline

### Registration Flow

```
main.py:11 → importlib.import_module("coding_agent.tools")
  → tools/__init__.py imports all tool modules
    → Each module uses @tool decorator at module level
      → @tool calls infer_schema(func) for JSON Schema
      → @tool creates FunctionTool adapter
      → @tool calls tool_registry.register(ft)
```

### Execution Flow

```
LLM returns tool_calls
  → AgentLoop parses: name, args (JSON), id
  → Groups into parallel_batch / sequential_calls
  → For parallel: asyncio.gather([tool_registry.execute_from_llm(tc)])
  → For sequential: tool_registry.execute_from_llm(tc)
    → Parse OpenAI format: extract name + arguments
    → tool_registry.execute(name, arguments)
      → tool.execute(**arguments) → ToolResult
    → Process result: truncate, inject instructions
    → Add tool result to context
    → Record in error_tracker, context_engine, plan_manager
    → Persist to session_manager
    → Verify after edit (if write_file/edit_file)
```

### Tool Inventory

| Module | Tools | Permission |
|--------|-------|------------|
| `file_ops.py` | `read_file`, `write_file`, `edit_file`, `list_files`, `apply_patch`, `multi_edit` | read/write |
| `shell.py` | `execute_command` | execute |
| `search.py` | `search_content` (ripgrep), `search_files` (glob) | read |
| `git.py` | `git_status`, `git_diff`, `git_log`, `git_commit` | read/write |
| `memory.py` | `remember`, `recall` | read |
| `planning.py` | `create_plan`, `update_plan` | read |
| `workspace.py` | `refresh_index` | read |
| `undo.py` | `undo`, `redo` | write |
| `count_tokens.py` | `count_tokens` | read |

### Parallel-Safe Tools

```python
_PARALLEL_SAFE_TOOLS = {
    "read_file", "list_files", "search_content", "search_files",
    "git_status", "git_diff", "git_log",
    "create_plan", "update_plan", "refresh_index",
}
```

### Error Handling

- `tool_registry.execute()` catches all exceptions, wraps in `ToolResult(success=False)`
- `execute_from_llm()` catches JSON decode errors, returns `ToolResult(success=False)`
- Parallel execution uses `return_exceptions=True` in `asyncio.gather()`
- No automatic retry on tool failure
- Error recorded in `ErrorTracker` for stuck detection

---

## 7. Prompt Assembly Flow

### System Prompt Construction (`system_prompt.py`)

**Static sections** (cacheable, ~1500 tokens):

1. **Identity** — "You are a coding agent..."
2. **Core Principles** — 5 rules (think first, read before write, minimal changes, verify, be explicit)
3. **Tool Rules** — Prefer dedicated tools, parallelize, batch reads
4. **Code Editing** — Edit don't rewrite, preserve style, no unnecessary changes
5. **Task Execution** — Be autonomous, persist until done, plan multi-step tasks
6. **Safety** — Read/write/execute/dangerous permission levels
7. **Communication** — Concise, direct, preambles, no emojis
8. **Error Handling** — Read errors, identify root cause, targeted fixes
9. **Planning** — Use create_plan/update_plan for multi-step tasks
10. **Adaptive Notes** — Model-tier-specific guidance (fast/balanced/advanced)

**Dynamic sections** (per-session, ~500-2000 tokens):

1. **Environment** — Working directory, platform, model, provider, git branch, file count
2. **Project Context** — Contents of AGENTS.md and README.md (truncated at 2000 chars)
3. **Memory** — Cross-session semantic + episodic memories
4. **Plan State** — Serialized plan with step statuses
5. **Workspace Index** — File tree summary

**Final assembly** (`system_prompt.py:434`):

```python
result = f"{static}\n\n{DYNAMIC_BOUNDARY}\n\n{dynamic}"
```

### Message List Construction (`context.py:70-98`)

```
[system_prompt] → [project_context] → [summary] → [messages...]
```

### Per-Iteration Prompt Build

```
1. context.build_messages() → system + summary + conversation
2. tool_registry.get_schemas() → all tool JSON schemas
3. LLMClient.stream(messages, tools) → sends to API
```

### Token Estimation per Step

| Step | Estimated Tokens |
|------|-----------------|
| Static system prompt | ~1500 |
| Dynamic sections | ~500-2000 |
| Tool schemas (15 tools) | ~2000 |
| Conversation (per iteration) | grows ~500-2000/iteration |
| Tool results (per call) | up to 8000 each |
| **Total per iteration** | **~5000-15000 initial, growing** |

### Gemini-Specific Handling

- System messages extracted from message list and passed via `config.system_instruction`
- Tool schemas converted from OpenAI format to Google `FunctionDeclaration` objects
- Messages converted from OpenAI format to Google `Content` objects
- Responses normalized back to OpenAI format for uniform handling

---

## 8. Memory Audit

| Memory Type | Status | Implementation |
|-------------|--------|----------------|
| Conversation memory | ✅ Implemented | `ContextManager.messages` — full message history with summarization |
| Session memory | ✅ Implemented | `SessionManager` — SQLite persistence of sessions, messages, operations |
| Working memory | ✅ Implemented (minimal) | `MemoryManager._working` — single-key ephemeral dict, not persisted |
| Persistent memory | ✅ Implemented | `MemoryManager` — semantic (facts) + episodic (summaries) in SQLite |
| Scratchpad | ❌ Not Present | No dedicated scratchpad for intermediate reasoning |
| Reflection memory | ❌ Not Present | No memory of past reflections or self-evaluations |
| Planning memory | ❌ Not Present | Plans are not persisted across sessions |
| Retrieval memory | ❌ Not Present | No embedding-based semantic search, only keyword matching |
| Importance scoring | ❌ Not Present | All memories treated equally, no relevance ranking |
| Memory consolidation | ❌ Not Present | No automatic merging or pruning of old memories |

### Memory Flow

```
Session Start:
  → MemoryManager.build_prompt_content() loads recent memories
  → Injected into system prompt via _memory_section()

During Session:
  → LLM calls "remember" tool → MemoryManager.store("semantic")
  → LLM calls "recall" tool → MemoryManager.recall(query)
  → Working memory: MemoryManager._working (in-memory dict)

Session End:
  → AgentLoop._build_session_summary() creates summary
  → MemoryManager.save_episodic() persists to SQLite
```

### Memory Limits

- Semantic memories: up to 15 in prompt
- Episodic memories: up to 5 in prompt
- Total memory in prompt: truncated at ~2000 tokens (rough estimate)
- Working memory: single key-value pair

---

## 9. Planning Audit

| Feature | Status | Implementation |
|---------|--------|----------------|
| Task planning | ✅ Implemented | `PlanManager` — LLM creates plans via `create_plan` tool |
| Task decomposition | ✅ Partially | LLM decomposes into steps, but no automatic decomposition |
| Task queue | ❌ Not Present | No queue, single plan at a time |
| Execution graph | ❌ Not Present | Linear step sequence only, no DAG |
| Replanning | ✅ Partially | `needs_replan()` detects failed steps, emits PLAN_UPDATE event, but no automatic replan |
| Goal tracking | ❌ Not Present | Plan has a goal string, but no structured goal tracking |
| Subtasks | ❌ Not Present | No nested plan support |
| Priority scheduling | ❌ Not Present | Steps execute in order only |
| Plan persistence | ❌ Not Present | Plans lost on session reset |
| Automatic plan creation | ❌ Not Present | LLM must explicitly call `create_plan` tool |

### Plan Lifecycle

```
1. LLM calls create_plan(goal, steps)
   → PlanManager.create_plan() → Plan(EXECUTING)

2. LLM calls update_plan(step_index, status)
   → PlanManager.start_step() / complete_step() / fail_step()

3. Agent loop checks needs_replan()
   → If active_step.status == FAILED → emit PLAN_UPDATE

4. Plan state injected into system prompt on every iteration
   → PlanManager.to_prompt() → serialized markdown

5. All steps done → PlanStatus.COMPLETED
   → No automatic cleanup or archival
```

### Plan Data Structure

```python
@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]
    current_step: int
    status: PlanStatus  # PLANNING | EXECUTING | COMPLETED | FAILED

@dataclass
class PlanStep:
    description: str
    status: StepStatus  # PENDING | IN_PROGRESS | DONE | FAILED
    tool_calls: list[dict]
    result: str
```

---

## 10. Reflection Audit

| Feature | Status | Implementation |
|---------|--------|----------------|
| Reflection after tool use | ❌ Not Present | No explicit reflection step after tool execution |
| Self evaluation | ❌ Not Present | No self-assessment of response quality |
| Confidence estimation | ❌ Not Present | No confidence scoring on actions |
| Retry reasoning | ❌ Partially | `ErrorTracker.suggest_strategy()` is advisory, not enforced |
| Verification | ✅ Implemented | `PostEditVerifier` runs syntax/lint/tests after file edits |
| Decision making | ❌ Not Present | No explicit decision framework beyond LLM's inherent reasoning |
| Outcome assessment | ❌ Not Present | No check whether tool results actually accomplished the goal |
| Progress evaluation | ❌ Not Present | No periodic assessment of task progress vs plan |

### What Exists

- **PostEditVerifier** checks code quality after file edits (syntax, lint, tests)
- **ErrorTracker** detects stuck patterns and suggests strategies
- **PlanManager** tracks step completion (but doesn't assess quality)

### What's Missing

- No "did this tool call achieve what I intended?" check
- No "am I making progress toward the goal?" assessment
- No "should I continue or change approach?" decision point
- No "what did I learn from this operation?" reflection
- No "is the current state acceptable?" evaluation

---

## 11. Context Management Audit

### How Context is Built

1. `ContextManager.build_messages()` assembles: system_prompt → project_context → summary → messages
2. Every user/assistant/tool message appended to `messages` list
3. No filtering or selection of which messages to include

### How Files are Selected

- `WorkspaceIndex` scans entire workspace on init
- No intelligent file selection based on task relevance
- `SmartContextEngine.select_context()` exists but is **not called** in the loop

### How History is Truncated

- Summarization triggers at 85% token usage
- Keeps last 5 messages, summarizes everything else
- Separate LLM call for summarization (can use cheaper model)
- Aggressive summarization at 95% (same mechanism, no additional truncation)

### How Token Limits are Handled

- `estimate_tokens()` uses tiktoken for accurate counting
- Progressive thresholds: 70% (warn), 85% (summarize), 95% (aggressive)
- Tool results truncated at 8000 tokens or 500 lines
- Search results limited to 20 lines
- No hard cutoff or message dropping

### How Context Grows

- Each iteration adds: 1 assistant message + N tool results
- Average growth: ~1000-3000 tokens per iteration
- At 20 iterations with large tool results: could reach 50k-100k tokens
- Summarization compresses but doesn't prevent growth

### Context Growth Diagram

```
Iteration 0:  system(~2000) + user(~100) = ~2100 tokens
Iteration 1:  + assistant(~500) + 3 tools(~3000) = ~5600 tokens
Iteration 2:  + assistant(~500) + 2 tools(~2000) = ~8100 tokens
Iteration 3:  + assistant(~500) + 4 tools(~4000) = ~12600 tokens
...
Iteration 10: ~30000+ tokens
Iteration 20: ~60000+ tokens (if no summarization)
```

### Limitations

- No sliding window for recent messages
- No importance-based pruning
- No deduplication of repeated information
- No context compression beyond summarization
- `SmartContextEngine` exists but is unused

---

## 12. Orchestrator Audit

The `AgentLoop` class IS the orchestrator. There is no separate orchestrator component.

### Responsibilities

- Initialize all subsystems (lines 87-161)
- Manage the iteration loop (lines 222-603)
- Dispatch LLM calls
- Route tool execution (parallel vs sequential)
- Process tool results
- Enforce budgets
- Manage context
- Emit events to TUI/CLI

### Decision Flow

```
User Input → Add to context → Loop:
  → Check budgets
  → Inject plan state
  → Check stuck state
  → Build messages + tools
  → Stream LLM response
  → If no tool calls → DONE
  → Parse tool calls
  → Group (parallel/sequential)
  → Execute tools
  → Process results
  → Check context usage
  → Next iteration
```

### Internal State

- `_start_time`, `_accumulated_cost`, `_tool_count`, `session_id`
- References to all subsystem instances

### Communication Pattern

| Target | Method | Purpose |
|--------|--------|---------|
| LLM | `LLMClient.stream()` / `LLMClient.complete()` | Get model response |
| Tools | `tool_registry.execute_from_llm()` | Execute tool calls |
| Memory | `MemoryManager.store()` / `MemoryManager.recall()` | Persist/recall memories |
| Session | `SessionManager.save_message()` / `SessionManager.save_operation()` | Persist to SQLite |
| TUI/CLI | `yield AgentEvent()` | Stream events to UI |

### State Transitions

```
IDLE → (user input) → RUNNING
RUNNING → (no tool calls) → DONE
RUNNING → (budget exceeded) → BUDGET_EXCEEDED
RUNNING → (max iterations) → MAX_ITERATIONS
RUNNING → (stuck + ask_user) → AWAITING_USER
RUNNING → (error) → ERROR
```

---

## 13. Feature Matrix

| Feature | Status |
|---------|--------|
| Tool calling | ✅ Implemented (15 tools, OpenAI format) |
| Streaming | ✅ Implemented (SSE for OpenRouter, native for Gemini) |
| File editing | ✅ Implemented (read/write/edit/apply_patch/multi_edit) |
| Parallel execution | ✅ Implemented (9 parallel-safe tools via asyncio.gather) |
| Planning | ✅ Implemented (PlanManager with step tracking) |
| Verification | ✅ Implemented (PostEditVerifier: syntax/lint/tests) |
| Error recovery | ✅ Implemented (ErrorTracker with stuck detection) |
| Cross-session memory | ✅ Implemented (episodic + semantic in SQLite) |
| Undo/redo | ✅ Implemented (UndoStack, 50 entries) |
| Session persistence | ✅ Implemented (SQLite) |
| API key rotation | ✅ Implemented (KeyPool with exponential backoff) |
| Context summarization | ✅ Implemented (progressive thresholds) |
| Workspace awareness | ✅ Implemented (WorkspaceIndex with file tree) |
| Docker sandbox | ✅ Implemented (SandboxExecutor) |
| Multi-provider support | ✅ Implemented (Gemini + OpenRouter) |
| Permission system | ✅ Implemented (4 levels: read/write/execute/dangerous) |
| Model-tier adaptation | ✅ Implemented (fast/balanced/advanced prompt sections) |
| Token counting | ✅ Implemented (tiktoken + cost estimation) |
| CLI interface | ✅ Implemented (Typer with run/config/version/history) |
| Structured logging | ✅ Implemented (structlog) |

---

## 14. Missing Components

| Component | Priority | Notes |
|-----------|----------|-------|
| **Sub-agent delegation** | High | No ability to spawn child agents for parallel tasks |
| **Context compression** | High | Summarization is the only mechanism; no selective pruning |
| **Reflection loop** | High | No self-evaluation after tool use or task completion |
| **Automatic replanning** | High | Replanning is detected but not executed |
| **SmartContextEngine integration** | Medium | Engine exists but is never called in the loop |
| **Task queue / execution graph** | Medium | Only single linear plan supported |
| **Memory consolidation** | Medium | No merging, pruning, or importance scoring of memories |
| **Prompt caching** | Medium | Static prompt sections are rebuilt every time |
| **Hard context cutoff** | Medium | No message dropping when summarization isn't enough |
| **Anthropic/Claude support** | Low | Only Gemini and OpenRouter |
| **Multi-modal support** | Low | No image/audio input handling |
| **Plugin system** | Low | No dynamic tool loading or plugin architecture |
| **Background workflows** | Low | No async task queuing |
| **Git integration depth** | Low | Only status/diff/log/commit, no branching/merging |
| **Test runner integration** | Low | Verification runs ad-hoc pytest, no full test suite awareness |
| **Telemetry / observability** | Low | Structured logging exists but no metrics/tracing |
| **TUI** | Low | Referenced in docs but not in source code |

---

## 15. Technical Debt

1. **SmartContextEngine unused** — 262 lines of code that is never called from the agent loop
2. **Duplicate tool result processing** — Lines 419-488 (parallel) and 491-599 (sequential) have nearly identical logic (~180 lines duplicated)
3. **System prompt rebuilt multiple times** — Rebuilt on init (line 156), on memory load (line 183), on every iteration with plan (line 259) — could be cached
4. **Permission check only for sequential tools** — Parallel tools skip permission checks entirely (line 420-488)
5. **Summarization via fire-and-forget** — `asyncio.create_task()` at lines 791/800 creates tasks that may not complete before the next iteration
6. **Token estimation inconsistency** — `SmartContextEngine._estimate_tokens()` uses `len(text) // 4`, while `ContextManager.estimate_tokens()` uses tiktoken
7. **No type safety for tool results** — Tool results are strings, no structured output schema
8. **Hardcoded thresholds** — Stuck threshold (3), history window (10), parallel-safe set, context limits (8000 tokens, 500 lines) are all hardcoded

---

## 16. Bottlenecks

1. **Sequential tool execution** — Write tools execute one at a time even when independent
2. **Full conversation sent every iteration** — No incremental/differential context building
3. **System prompt rebuilding** — Entire prompt reconstructed on each iteration when plan exists
4. **Token counting per message** — `estimate_tokens()` iterates all messages with tiktoken on every call
5. **Summarization blocks next iteration** — `asyncio.create_task()` for summarization, but no mechanism to wait for it or skip if already running
6. **No streaming tool results** — Tool results are collected fully before being added to context

---

## 17. Risks

1. **Context overflow** — Progressive summarization may not keep up with rapid tool use (e.g., 20 parallel file reads)
2. **Stuck detection false positives** — Same tool with same args may be legitimate (e.g., reading a file multiple times)
3. **Permission bypass** — Parallel tools skip permission checks entirely
4. **Memory corruption** — No locking on SQLite operations, concurrent sessions could conflict
5. **Cost runaway** — Between budget checks, a single LLM call could exceed the remaining budget
6. **Summarization quality** — Using the same model for summarization may produce verbose summaries

---

## 18. Strengths

1. **Clean architecture** — Well-separated concerns, each component has clear responsibilities
2. **Solid tool system** — `@tool` decorator with auto-schema inference is elegant and extensible
3. **Multi-provider support** — Clean abstraction over Gemini and OpenRouter with format normalization
4. **Key-pool rotation** — Automatic handling of rate limits with exponential backoff
5. **Progressive context management** — Three-tier threshold system prevents sudden context explosion
6. **Cross-session memory** — Episodic + semantic memory persists across sessions
7. **Post-edit verification** — Automatic syntax/lint/test checks catch issues early
8. **Comprehensive event system** — 14 event types enable rich TUI integration
9. **Parallel tool execution** — Read-only tools execute concurrently via asyncio.gather
10. **Thorough error recovery** — Stuck detection with escalating strategies (retry → alternative → replan → ask user)

---

## 19. Weaknesses

1. **No reflection** — Agent never evaluates whether its actions achieved the goal
2. **No sub-agents** — Cannot delegate complex subtasks to specialized agents
3. **No context compression** — Only summarization, no selective pruning or deduplication
4. **Unused SmartContextEngine** — Built but never integrated into the loop
5. **No automatic replanning** — Detected but not executed
6. **Permission gap** — Parallel tools bypass permission system
7. **No task queue** — Single linear plan only
8. **No memory consolidation** — Memories accumulate without pruning
9. **No prompt caching** — Static prompt sections rebuilt every session
10. **No TUI** — Terminal-only output despite TUI being a core planned feature

---

## 20. Readiness Score

| Dimension | Score (0-10) | Notes |
|-----------|-------------|-------|
| Core loop | 8/10 | Solid observe-think-act cycle, good exit conditions |
| Tool system | 8/10 | Clean registry, auto-schema, parallel execution |
| LLM integration | 7/10 | Multi-provider, streaming, key rotation; no prompt caching |
| Context management | 5/10 | Basic summarization exists; SmartContextEngine unused |
| Memory | 5/10 | Cross-session works; no consolidation, no retrieval |
| Planning | 4/10 | LLM-driven plans work; no auto-planning, no persistence |
| Reflection | 1/10 | Only verification; no self-evaluation or outcome assessment |
| Error recovery | 6/10 | Stuck detection works; strategies are advisory only |
| Production readiness | 5/10 | Logging, SQLite, budgets exist; no telemetry, no TUI |
| Architecture | 7/10 | Clean separation of concerns; some duplication and unused code |

**Overall: 5.6/10**

---

## Summary

The foundation is solid. The core loop, tool system, and LLM integration are well-built. The main gaps are in intelligence layers (reflection, automatic replanning, context compression) and production features (TUI, sub-agents, telemetry).

### Key Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| `agent/loop.py` | 842 | Core agent loop |
| `agent/context.py` | 212 | Context window management |
| `agent/system_prompt.py` | 494 | System prompt builder |
| `agent/memory.py` | 188 | Cross-session memory |
| `agent/planner.py` | 243 | Planning system |
| `agent/verifier.py` | 318 | Post-edit verification |
| `agent/error_recovery.py` | 276 | Error recovery |
| `agent/context_engine.py` | 262 | Smart context selection (unused) |
| `agent/permissions.py` | 111 | Permission system |
| `agent/undo.py` | 159 | Undo/redo stack |
| `agent/events.py` | 34 | Event types |
| `llm/client.py` | 672 | LLM client |
| `llm/streaming.py` | 163 | Stream parsing |
| `llm/tokens.py` | 134 | Token counting |
| `llm/key_pool.py` | 56 | API key rotation |
| `tools/registry.py` | 271 | Tool registry |
| `main.py` | 226 | CLI entry point |
| `config.py` | 167 | Configuration |
