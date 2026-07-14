# CoreCode Implementation Plan

## From 3.5/10 to Production-Grade

This document is the actionable, phase-by-phase build plan to take CoreCode from its current state to a system that competes with Claude Code, Cursor Agent, Gemini CLI, and OpenCode.

Each phase is ordered by dependency and ROI. No phase depends on something that hasn't been built yet. Every phase produces a measurable improvement.

---

## Phase 1: Critical Fixes & Foundation Hardening (Week 1-2)

**Goal:** Fix bugs that make the agent broken today. Add the basic infrastructure every subsequent phase depends on.

**Expected score after:** 3.5 → 5/10

---

### 1.1 Fix Gemini System Prompt Bug [CRITICAL]

**Why:** The agent sends zero instructions to Gemini. Every Gemini response ignores the system prompt. This is a ship-blocker.

**What to build:**
- Modify `llm/client.py` → `_convert_messages()` to inject system content as the first `user` message with a `model` response following (Google GenAI's system message pattern)
- Alternatively, use Gemini's `system_instruction` parameter in `GenerateContentConfig`
- Add a test that verifies system prompt content appears in the request payload

**Files to modify:**
- `src/coding_agent/llm/client.py` — `_convert_messages()`, `_raw_call_gemini()`
- `tests/test_llm.py` — new test for system prompt injection

**Verification:** Agent follows system prompt rules when running on Gemini.

**Complexity:** Low (1-2 hours)
**Impact:** Critical (agent is currently broken on primary provider)

---

### 1.2 Implement tiktoken-Based Token Counting

**Why:** `chars // 4` is off by 2-3x for code. This causes context overflow or wasted budget.

**What to build:**
- New module `llm/tokens_v2.py` with tiktoken-based counting
- Fall back to `chars // 4` if tiktoken can't load the model's encoding
- Cache encoding objects (they're expensive to create)
- Replace `count_tokens()` calls in `context.py` and anywhere else it's used

**Files to create/modify:**
- `src/coding_agent/llm/tokens_v2.py` (NEW — ~80 lines)
- `src/coding_agent/llm/tokens.py` — replace `count_tokens` implementation
- `pyproject.toml` — add `tiktoken` dependency
- `tests/test_llm.py` — tests for accuracy against known strings

**Verification:** `count_tokens("hello world")` returns ~2, not ~2.

**Complexity:** Low (2-3 hours)
**Impact:** High (prevents context overflow)

---

### 1.3 Add Tool Result Truncation

**Why:** A single `read_file` on a 10k-line file dumps everything into context. One tool call can consume 50% of the context window.

**What to build:**
- New module `agent/context_limits.py` with configurable limits
- `MAX_TOOL_RESULT_TOKENS = 8000` (configurable)
- `MAX_TOOL_RESULT_LINES = 500`
- Truncation function that preserves the first and last N lines with a `[truncated: X lines omitted]` message
- Apply in `agent/loop.py` before adding tool results to context
- For `read_file`: always include first 50 and last 50 lines, truncate middle
- For `search_content`: limit to 20 results
- For `execute_command`: limit stdout to 200 lines

**Files to create/modify:**
- `src/coding_agent/agent/context_limits.py` (NEW — ~60 lines)
- `src/coding_agent/agent/loop.py` — apply truncation before `add_tool_result()`
- `tests/test_agent/test_context_limits.py` (NEW)

**Verification:** `read_file` on a 1000-line file returns ~100 lines with truncation notice.

**Complexity:** Medium (3-4 hours)
**Impact:** High (prevents context explosion)

---

### 1.4 Implement Parallel Tool Execution

**Why:** Sequential execution wastes 5x time when LLM requests multiple independent tool calls.

**What to build:**
- In `agent/loop.py`, replace the sequential `for tc in tool_calls` with `asyncio.gather()`
- Group tool calls: reads can be parallel, writes to the same file must be sequential
- Simple heuristic: all `read_*` and `search_*` tools are parallel-safe; all `write_*`, `edit_*`, `execute_*` are sequential
- Emit `TOOL_START` events for all tools before any execution begins

**Files to modify:**
- `src/coding_agent/agent/loop.py` — replace sequential loop with parallel dispatch
- `tests/test_agent/test_agent_loop.py` — test parallel execution

**Verification:** Two `read_file` calls in the same LLM turn execute concurrently (measurable wall-clock improvement).

**Complexity:** Medium (4-6 hours)
**Impact:** High (5x speed on multi-file reads)

---

### 1.5 Add Streaming Tool Call Emission

**Why:** Tool calls are only emitted after the entire stream finishes. Should emit as soon as each tool call is fully parsed.

**What to build:**
- Modify `StreamParser.feed()` to emit `TOOL_CALL` events incrementally (as soon as name + args are complete)
- Modify `AgentLoop.process_input()` to handle tool calls arriving mid-stream
- Start executing completed tool calls while the stream is still producing text

**Files to modify:**
- `src/coding_agent/llm/streaming.py` — incremental tool call emission
- `src/coding_agent/agent/loop.py` — handle mid-stream tool calls

**Verification:** Tool execution starts before the LLM finishes generating text.

**Complexity:** Medium (4-6 hours)
**Impact:** Medium (faster perceived response)

---

### 1.6 Add Session Persistence (SQLite)

**Why:** Zero persistence means every session starts from scratch. This blocks memory, undo, and history.

**What to build:**
- Implement `session/manager.py` with actual SQLite operations
- `SessionManager.create_session()` — create new session record
- `SessionManager.save_message()` — persist each message
- `SessionManager.save_operation()` — persist tool calls for undo
- `SessionManager.list_sessions()` — show past sessions
- `SessionManager.load_session()` — resume a session
- `SessionManager.get_operations()` — get operation history for undo
- Run schema migrations on startup

**Files to create/modify:**
- `src/coding_agent/session/manager.py` (REWRITE — ~200 lines)
- `src/coding_agent/session/history.py` (NEW — ~100 lines for undo)
- `src/coding_agent/agent/loop.py` — call session manager after each message/tool
- `tests/test_session.py` (REWRITE — comprehensive tests)

**Verification:** Can create session, add messages, close, reopen, resume.

**Complexity:** High (6-8 hours)
**Impact:** High (enables memory, undo, history)

---

### 1.7 Add Cost & Time Budget Limits

**Why:** No way to stop the agent from burning money or time.

**What to build:**
- `max_cost_per_session` config (default: $5.00)
- `max_time_per_task` config (default: 300 seconds)
- Check budget at the start of each iteration
- Yield `BUDGET_EXCEEDED` event and stop
- Track cumulative cost and time in the agent loop

**Files to create/modify:**
- `src/coding_agent/agent/loop.py` — budget checks
- `src/coding_agent/config.py` — new settings
- `src/coding_agent/agent/events.py` — new `BUDGET_EXCEEDED` event type

**Verification:** Agent stops after spending $5 or running 5 minutes.

**Complexity:** Low (2-3 hours)
**Impact:** Medium (prevents runaway costs)

---

## Phase 2: Intelligence Layer (Week 3-6)

**Goal:** Add the subsystems that make the agent actually smart — planning, verification, workspace understanding, and error recovery.

**Expected score after:** 5 → 7/10

---

### 2.1 Workspace Index (File Tree + Basic Symbols)

**Why:** The agent has zero awareness of what's in the workspace. It discovers everything through tools, which is slow and wasteful.

**What to build:**
- New module `agent/workspace_index.py`
- On startup, scan workspace: build file tree, count files, detect languages
- Maintain a lightweight in-memory index:
  ```
  {
    "tree": { "src/": { "agent/": ["loop.py", "context.py"], "llm/": [...] } },
    "languages": { "python": 45, "markdown": 12 },
    "total_files": 57,
    "total_lines": 4200
  }
  ```
- Inject file tree summary into system prompt (first 100 files, grouped by directory)
- Update index when files are created/deleted
- Add `refresh_index` tool for the agent to re-scan when needed

**Files to create/modify:**
- `src/coding_agent/agent/workspace_index.py` (NEW — ~150 lines)
- `src/coding_agent/agent/system_prompt.py` — inject file tree
- `src/coding_agent/agent/loop.py` — initialize and refresh index
- `tests/test_agent/test_workspace_index.py` (NEW)

**Verification:** System prompt contains accurate file tree. Agent can list files without calling `list_files`.

**Complexity:** Medium (6-8 hours)
**Impact:** High (agent knows what exists)

---

### 2.2 Planning System

**Why:** The agent dives into execution without a plan. It wastes iterations on wrong approaches.

**What to build:**
- New module `agent/planner.py`
- New tool `create_plan` — agent calls this to create an explicit step-by-step plan
- New tool `update_plan` — agent marks steps as done/in-progress/failed
- Plan is stored in a `Plan` dataclass:
  ```python
  @dataclass
  class Plan:
      goal: str
      steps: list[PlanStep]
      current_step: int
      status: str  # "planning" | "executing" | "completed" | "failed"

  @dataclass
  class PlanStep:
      description: str
      status: str  # "pending" | "in_progress" | "done" | "failed"
      tool_calls: list[dict]  # tools used for this step
      result: str
  ```
- Inject current plan into system prompt on each iteration
- When all steps are done → yield DONE
- When a step fails → replan (regenerate from current step)

**Files to create/modify:**
- `src/coding_agent/agent/planner.py` (NEW — ~200 lines)
- `src/coding_agent/agent/loop.py` — integrate planner
- `src/coding_agent/agent/system_prompt.py` — add planning instructions
- `src/coding_agent/agent/events.py` — add PLAN_UPDATE event
- `tests/test_agent/test_planner.py` (NEW)

**Verification:** Agent creates a plan before executing, updates it as it works, stops when plan is complete.

**Complexity:** High (10-12 hours)
**Impact:** Critical (structured task decomposition)

---

### 2.3 Post-Edit Verification System

**Why:** The agent makes changes and hopes they work. No verification = broken code shipped.

**What to build:**
- New module `agent/verifier.py`
- After every `edit_file` or `write_file` call, automatically:
  1. Run syntax check (for Python: `py_compile`; for JS/TS: `node --check`)
  2. Run project linter if configured (`ruff check` for Python)
  3. Run relevant tests if a test file exists for the changed file
- Verification results fed back to LLM as a tool result
- If verification fails, agent is told to fix the issue
- Configurable: `verify_after_edit = true/false`

**Files to create/modify:**
- `src/coding_agent/agent/verifier.py` (NEW — ~180 lines)
- `src/coding_agent/agent/loop.py` — call verifier after file writes
- `src/coding_agent/config.py` — `verify_after_edit` setting
- `tests/test_agent/test_verifier.py` (NEW)

**Verification:** After editing a Python file with a syntax error, agent receives error feedback and attempts to fix it.

**Complexity:** High (8-10 hours)
**Impact:** Critical (prevents broken code)

---

### 2.4 Error Recovery Strategies

**Why:** Currently, errors are just fed back to the LLM with no strategy. The agent often loops on the same failing approach.

**What to build:**
- New module `agent/error_recovery.py`
- Track error history per iteration: what tool failed, what error, what was tried
- Detect "stuck" state: same tool + same error 3 times in a row
- On stuck detection:
  1. Summarize what was tried
  2. Ask the LLM to try a completely different approach
  3. If still stuck after 2 attempts, ask the user for help
- Categorize errors:
  - **Transient**: rate limit, timeout → retry with backoff
  - **Permanent**: file not found, permission denied → don't retry, try alternative
  - **Logic**: wrong file, wrong approach → suggest different strategy
- Feed structured error context to LLM (not just the error message)

**Files to create/modify:**
- `src/coding_agent/agent/error_recovery.py` (NEW — ~150 lines)
- `src/coding_agent/agent/loop.py` — integrate error tracking
- `tests/test_agent/test_error_recovery.py` (NEW)

**Verification:** After 3 failed attempts to edit a file, agent switches strategy or asks user.

**Complexity:** Medium (6-8 hours)
**Impact:** High (prevents infinite loops)

---

### 2.5 Smart Context Selection

**Why:** The agent dumps entire files into context. For large files, this wastes the entire context window.

**What to build:**
- New module `agent/context_engine.py`
- When `read_file` is called on a large file (>200 lines):
  1. Only return requested lines (already implemented via offset/limit)
  2. Add instruction: "File is N lines. Use offset/limit to read specific sections."
- When multiple files are read, prioritize by relevance:
  - Files mentioned by name in the user's request → highest priority
  - Files recently read → higher priority
  - Files with errors → higher priority
- Implement `context_budget` tracking: estimate remaining context budget after each message
- Before each LLM call, check if context is getting full:
  - If >70% full: suggest the agent focus on recent context
  - If >85% full: trigger summarization
  - If >95% full: force summarization and warn the agent

**Files to create/modify:**
- `src/coding_agent/agent/context_engine.py` (NEW — ~120 lines)
- `src/coding_agent/agent/context.py` — integrate budget tracking
- `tests/test_agent/test_context_engine.py` (NEW)

**Verification:** Reading a 5000-line file doesn't consume the entire context budget.

**Complexity:** Medium (6-8 hours)
**Impact:** High (preserves context for real work)

---

### 2.6 Stuck Detection & Backtracking

**Why:** The agent can loop forever on the same failing approach.

**What to build:**
- New module `agent/stuck_detector.py`
- Track a sliding window of the last 10 tool calls
- Detect stuck patterns:
  - Same tool + same arguments called 3+ times
  - Same error 3+ times
  - No progress (no new files read, no edits made) for 5 iterations
- When stuck:
  1. Emit `STUCK_DETECTED` event
  2. Add a system message: "You appear stuck. Previous approaches failed. Try something completely different."
  3. If still stuck after 2 more iterations, yield `ASK_USER` event
- Implement rollback: save context snapshot before risky operations, restore on failure

**Files to create/modify:**
- `src/coding_agent/agent/stuck_detector.py` (NEW — ~100 lines)
- `src/coding_agent/agent/loop.py` — integrate detector
- `src/coding_agent/agent/events.py` — add STUCK_DETECTED, ASK_USER events
- `tests/test_agent/test_stuck_detector.py` (NEW)

**Verification:** After repeating the same failed edit 3 times, agent tries a different approach or asks user.

**Complexity:** Medium (4-6 hours)
**Impact:** High (prevents infinite loops)

---

### 2.7 Apply-Patch Tool (AST-Aware Editing)

**Why:** `edit_file` with exact string replacement is fragile and breaks on whitespace changes.

**What to build:**
- New tool `apply_patch` — accepts unified diff format
- New tool `multi_edit` — applies multiple edits to the same file in one call (like Claude Code's `replace` tool with multiple needles)
- Keep existing `edit_file` for backward compatibility
- Add validation: after applying patch, verify the file is valid (syntax check)

**Files to create/modify:**
- `src/coding_agent/tools/file_ops.py` — add `apply_patch`, `multi_edit`
- `tests/test_tools/test_file_ops.py` — tests for new tools

**Verification:** Can apply a multi-hunk diff to a file in one call.

**Complexity:** Medium (6-8 hours)
**Impact:** High (more reliable editing)

---

## Phase 3: Memory & Learning (Week 7-9)

**Goal:** Make the agent remember things across sessions. Learn project conventions. Support undo.

**Expected score after:** 7 → 8.5/10

---

### 3.1 Cross-Session Memory

**Why:** The agent forgets everything between sessions. It can't learn project conventions.

**What to build:**
- New module `agent/memory.py`
- Three memory types:
  1. **Episodic** — what was done in past sessions (stored in SQLite)
     - "Session abc123: Fixed bug in parser.py, added tests"
     - Auto-generated summary at session end
  2. **Semantic** — learned facts about the project
     - "This project uses pytest, not unittest"
     - "The main entry point is src/main.py"
     - "Config is in pyproject.toml"
     - Stored in `~/.coding-agent/memory.json`
  3. **Working** — current task state
     - "Currently fixing the login bug, have read auth.py and user.py"
     - Ephemeral, cleared at session start
- Memory retrieval: inject relevant past session summaries into system prompt
- Memory update: after each session, extract key learnings and store them
- New tools: `remember` (store a fact), `recall` (search past memories)

**Files to create/modify:**
- `src/coding_agent/agent/memory.py` (NEW — ~250 lines)
- `src/coding_agent/agent/system_prompt.py` — inject memory
- `src/coding_agent/agent/loop.py` — memory read/write at session boundaries
- `src/coding_agent/session/manager.py` — session summary storage
- `tests/test_agent/test_memory.py` (NEW)

**Verification:** After session 1 edits `config.py`, session 2 knows about the config file without being told.

**Complexity:** High (12-15 hours)
**Impact:** Critical (persistent learning)

---

### 3.2 Undo/Redo System

**Why:** Users can't safely let the agent make changes if there's no undo.

**What to build:**
- New module `agent/undo.py`
- `UndoStack` class:
  - `push(operation)` — save operation with before/after state
  - `undo()` — revert last operation
  - `redo()` — re-apply last undone operation
  - `can_undo()` / `can_redo()` — check availability
- Operations to track:
  - `edit_file`: save before_content and after_content
  - `write_file`: save before_content (None if new file)
  - `git_commit`: save commit hash for `git revert`
- New tool `undo` — agent can undo its own changes
- New tool `redo` — agent can redo
- User can also trigger undo via TUI keybinding (Ctrl+Z)

**Files to create/modify:**
- `src/coding_agent/agent/undo.py` (NEW — ~150 lines)
- `src/coding_agent/tools/file_ops.py` — capture before-state
- `src/coding_agent/agent/loop.py` — integrate undo stack
- `src/coding_agent/tui/app.py` — Ctrl+Z binding
- `tests/test_agent/test_undo.py` (NEW)

**Verification:** Agent edits a file, user presses Ctrl+Z, file reverts.

**Complexity:** Medium (6-8 hours)
**Impact:** High (safe experimentation)

---

### 3.3 Session History Viewer

**Why:** No way to see what the agent did in past sessions.

**What to build:**
- New TUI screen `screens/history.py`
- List past sessions with: date, model, tokens used, cost, summary
- Select a session to see: full conversation, tool calls, file changes
- Can resume a past session (load context)
- New CLI command: `coding-agent history` — list past sessions

**Files to create/modify:**
- `src/coding_agent/tui/screens/history.py` (NEW — ~200 lines)
- `src/coding_agent/tui/app.py` — add history screen
- `src/coding_agent/main.py` — add `history` command
- `src/coding_agent/session/manager.py` — query methods

**Verification:** `coding-agent history` shows list of past sessions.

**Complexity:** Medium (6-8 hours)
**Impact:** Medium (visibility into agent behavior)

---

### 3.4 Adaptive System Prompt

**Why:** Same prompt regardless of task complexity, model, or project.

**What to build:**
- Modify `agent/system_prompt.py` to be dynamic:
  - **Simple tasks** (single file read): skip detailed editing rules
  - **Complex tasks** (multi-file changes): include full planning instructions
  - **Gemini-specific**: adjust prompt style (Gemini prefers shorter, more direct instructions)
  - **Claude-specific**: leverage Claude's instruction-following strengths
- Add prompt compression: remove redundant sections based on task type
- Cache static sections per model (use `DYNAMIC_BOUNDARY` marker)

**Files to create/modify:**
- `src/coding_agent/agent/system_prompt.py` — rewrite builder
- `tests/test_agent/test_system_prompt.py` — test variants

**Verification:** Prompt for "read this file" is shorter than "refactor the auth module."

**Complexity:** Medium (6-8 hours)
**Impact:** Medium (better LLM performance)

---

## Phase 4: Production Hardening (Week 10-14)

**Goal:** Make it production-ready. Add extensibility, security, monitoring, and polish.

**Expected score after:** 8.5 → 9.5/10

---

### 4.1 Prompt Caching

**Why:** 50-80% cost reduction on repeated calls. Free performance.

**What to build:**
- Gemini: use `cached_content` parameter for system prompt + tool schemas
- Anthropic: use `cache_control` breakpoint on system prompt
- OpenRouter: cache key based on system prompt hash
- Cache invalidation: when system prompt changes (new session, different project)
- Track cache hit/miss metrics

**Files to create/modify:**
- `src/coding_agent/llm/client.py` — cache integration
- `src/coding_agent/llm/prompt_cache.py` (NEW — ~100 lines)

**Verification:** Second call to same model shows cached token count.

**Complexity:** Medium (6-8 hours)
**Impact:** High (50-80% cost reduction)

---

### 4.2 Anthropic SDK Support

**Why:** Native Claude access with extended thinking, prompt caching, tool use.

**What to build:**
- Add `anthropic` SDK as a provider option
- Implement `AnthropicClient` with native tool use
- Support extended thinking (Claude's chain-of-thought)
- Support prompt caching with `cache_control`
- Update config: `llm_provider` can be `"anthropic"`

**Files to create/modify:**
- `src/coding_agent/llm/anthropic_client.py` (NEW — ~300 lines)
- `src/coding_agent/config.py` — add `anthropic` provider
- `pyproject.toml` — add `anthropic` dependency

**Verification:** Agent runs on Claude with native tool use and prompt caching.

**Complexity:** High (10-12 hours)
**Impact:** High (access to Claude's best features)

---

### 4.3 MCP Tool Integration

**Why:** Extensibility. Users can add custom tools.

**What to build:**
- New module `tools/mcp.py`
- MCP client that connects to MCP servers via stdio or SSE
- Dynamic tool registration: MCP server tools added to `tool_registry`
- Support for custom MCP servers via config:
  ```toml
  [[mcp_servers]]
  name = "database"
  command = "uvx"
  args = ["mcp-server-sqlite", "--db-path", "./data.db"]
  ```
- MCP tools get permission levels based on their declared capabilities

**Files to create/modify:**
- `src/coding_agent/tools/mcp.py` (NEW — ~200 lines)
- `src/coding_agent/config.py` — MCP server config
- `src/coding_agent/agent/loop.py` — initialize MCP connections
- `pyproject.toml` — add `mcp` dependency

**Verification:** Can connect to an MCP server and use its tools.

**Complexity:** High (12-15 hours)
**Impact:** High (extensibility)

---

### 4.4 Sub-Agent Orchestration

**Why:** Complex tasks benefit from parallel sub-agents. One agent can't do everything.

**What to build:**
- New module `agent/subagent.py`
- `SubAgent` class:
  - Has its own context, tools, and LLM client
  - Can be spawned for specific subtasks
  - Reports progress back to parent agent
- Parent agent can spawn sub-agents for:
  - Research: "explore the codebase and report findings"
  - Testing: "run the test suite and report failures"
  - Verification: "check that all edits compile"
- Sub-agents run in parallel (asyncio.Task)
- Results aggregated and fed back to parent

**Files to create/modify:**
- `src/coding_agent/agent/subagent.py` (NEW — ~200 lines)
- `src/coding_agent/agent/loop.py` — sub-agent spawning
- `tests/test_agent/test_subagent.py` (NEW)

**Verification:** Agent spawns a research sub-agent while making edits in parallel.

**Complexity:** High (15-20 hours)
**Impact:** Medium (parallel task execution)

---

### 4.5 Network-Isolated Sandbox

**Why:** The sandbox has full network access. Security risk.

**What to build:**
- Modify Docker run command to add `--network none` option
- Config option: `sandbox_network = "none" | "host" | "bridge"`
- For commands that need network (npm install, pip install), allow explicit network access per command
- Add `--cap-drop=ALL` and only add necessary capabilities

**Files to create/modify:**
- `src/coding_agent/sandbox/docker.py` — network config
- `src/coding_agent/config.py` — `sandbox_network` setting

**Verification:** `curl http://example.com` fails in sandbox with `--network none`.

**Complexity:** Low (2-3 hours)
**Impact:** Medium (security)

---

### 4.6 Structured Logging & Monitoring

**Why:** No visibility into agent behavior in production.

**What to build:**
- Structured event logging for every agent action:
  - LLM request/response (model, tokens, latency, cost)
  - Tool call (name, args, result, duration)
  - Permission check (tool, result)
  - Context state (messages, tokens, summarization events)
  - Errors (type, recovery action)
- New module `agent/telemetry.py`
- Export to file or stdout in JSON format
- New TUI panel showing recent events (debug mode)

**Files to create/modify:**
- `src/coding_agent/agent/telemetry.py` (NEW — ~150 lines)
- `src/coding_agent/agent/loop.py` — emit telemetry events
- `src/coding_agent/tui/widgets/debug.py` (NEW — optional debug panel)

**Verification:** JSON log file contains structured entries for every tool call.

**Complexity:** Medium (6-8 hours)
**Impact:** Medium (debuggability)

---

### 4.7 TUI Polish & UX Improvements

**Why:** The TUI is functional but rough.

**What to build:**
- **Diff viewer**: syntax-highlighted side-by-side diff for file edits
- **Progress indicators**: show which plan step is executing, time elapsed
- **Keyboard shortcuts**: Ctrl+Y to approve permission, Ctrl+N to deny, Ctrl+Z for undo
- **In-place streaming**: update widget text without remove/remount
- **Session selector**: quick switch between recent sessions
- **Cost warning**: show warning when approaching budget limit
- **Theme system**: light/dark mode support

**Files to create/modify:**
- `src/coding_agent/tui/widgets/diff_viewer.py` (NEW)
- `src/coding_agent/tui/widgets/chat.py` — in-place streaming
- `src/coding_agent/tui/app.py` — keyboard shortcuts
- `src/coding_agent/tui/theme.py` — dark/light themes

**Verification:** Streaming doesn't cause flicker. Diff viewer shows syntax-highlighted changes.

**Complexity:** Medium (8-10 hours)
**Impact:** Medium (user experience)

---

### 4.8 Integration Test Suite

**Why:** No end-to-end tests. Can't verify the full system works.

**What to build:**
- New directory `tests/integration/`
- Tests that exercise the full flow with mocked LLM:
  1. User asks to read a file → agent reads it → returns content
  2. User asks to fix a bug → agent plans → reads code → edits → verifies
  3. User asks to run tests → agent executes → reports results
  4. Agent hits an error → recovers → completes task
  5. Agent creates a plan → executes steps → marks done
  6. Agent undoes a change → file reverts
- Performance benchmarks:
  - Context build time < 100ms
  - Tool dispatch < 10ms
  - Stream parse < 5ms per chunk

**Files to create/modify:**
- `tests/integration/` (NEW directory with ~10 test files)
- `tests/benchmarks/` (NEW directory)

**Verification:** `pytest tests/integration/` passes all end-to-end scenarios.

**Complexity:** High (10-12 hours)
**Impact:** High (confidence in system)

---

### 4.9 Documentation & Onboarding

**Why:** No developer documentation for contributing.

**What to build:**
- `docs/architecture.md` — rewrite with actual architecture (not the planned one)
- `docs/development.md` — how to set up dev environment, run tests, contribute
- `docs/tools.md` — how to add new tools (with examples)
- `docs/config.md` — all config options explained
- Inline docstrings for all public APIs
- Type annotations complete and passing pyright strict

**Files to create/modify:**
- `docs/` (REWRITE all documentation)

**Verification:** New contributor can set up and run the project in <10 minutes.

**Complexity:** Medium (6-8 hours)
**Impact:** Medium (maintainability)

---

## Dependency Graph

```
Phase 1 (Foundation)
  ├── 1.1 Fix Gemini bug
  ├── 1.2 tiktoken counting
  ├── 1.3 Tool result truncation
  ├── 1.4 Parallel execution
  ├── 1.5 Streaming tool calls
  ├── 1.6 Session persistence ←── blocks Phase 3
  └── 1.7 Cost/time budgets

Phase 2 (Intelligence)  ←── depends on Phase 1
  ├── 2.1 Workspace index
  ├── 2.2 Planning system ←── blocks 2.3, 2.6
  ├── 2.3 Verification ←── depends on 2.2
  ├── 2.4 Error recovery ←── depends on 2.2
  ├── 2.5 Context engine
  ├── 2.6 Stuck detection ←── depends on 2.2
  ├── 2.7 Apply-patch tool

Phase 3 (Memory)  ←── depends on Phase 1.6
  ├── 3.1 Cross-session memory
  ├── 3.2 Undo/redo ←── depends on 1.6
  ├── 3.3 History viewer ←── depends on 1.6, 3.1
  └── 3.4 Adaptive prompt

Phase 4 (Production)  ←── depends on Phase 2
  ├── 4.1 Prompt caching
  ├── 4.2 Anthropic SDK
  ├── 4.3 MCP integration
  ├── 4.4 Sub-agents
  ├── 4.5 Network isolation
  ├── 4.6 Telemetry
  ├── 4.7 TUI polish
  ├── 4.8 Integration tests
  └── 4.9 Documentation
```

---

## Effort Summary

| Phase | Duration | Complexity | Score Impact |
|---|---|---|---|
| Phase 1: Foundation | 10-15 days | Low-Medium | 3.5 → 5.0 |
| Phase 2: Intelligence | 20-25 days | Medium-High | 5.0 → 7.0 |
| Phase 3: Memory | 15-18 days | Medium-High | 7.0 → 8.5 |
| Phase 4: Production | 25-30 days | Medium-High | 8.5 → 9.5 |
| **Total** | **70-88 days** | | **3.5 → 9.5** |

---

## Priority Matrix (Quick Reference)

| Priority | Task | Effort | Impact |
|---|---|---|---|
| P0 | Fix Gemini system prompt bug | 2h | Critical |
| P0 | Tool result truncation | 4h | High |
| P0 | tiktoken token counting | 3h | High |
| P1 | Parallel tool execution | 6h | High |
| P1 | Session persistence | 8h | High |
| P1 | Planning system | 12h | Critical |
| P1 | Verification system | 10h | Critical |
| P2 | Workspace index | 8h | High |
| P2 | Error recovery | 8h | High |
| P2 | Context engine | 8h | High |
| P2 | Cross-session memory | 15h | Critical |
| P2 | Undo/redo | 8h | High |
| P3 | Stuck detection | 6h | High |
| P3 | Apply-patch tool | 8h | High |
| P3 | Prompt caching | 8h | High |
| P3 | Anthropic SDK | 12h | High |
| P3 | MCP integration | 15h | High |
| P3 | Sub-agents | 20h | Medium |
| P4 | Network isolation | 3h | Medium |
| P4 | Telemetry | 8h | Medium |
| P4 | TUI polish | 10h | Medium |
| P4 | Integration tests | 12h | High |
| P4 | Documentation | 8h | Medium |

---

## What Success Looks Like

After all 4 phases, CoreCode will:

1. **Plan before executing** — creates explicit step-by-step plans
2. **Execute in parallel** — reads multiple files concurrently
3. **Verify every change** — runs linter/tests after edits
4. **Recover from errors** — detects stuck states, switches strategies
5. **Remember across sessions** — learns project conventions
6. **Support undo** — safe experimentation
7. **Manage context intelligently** — truncates results, prioritizes relevant files
8. **Cost-conscious** — prompt caching, budget limits, model routing
9. **Extensible** — MCP tools, custom plugins
10. **Production-ready** — monitoring, logging, testing, documentation

This will be a system that competes with Claude Code and Cursor Agent, not just a portfolio piece.
