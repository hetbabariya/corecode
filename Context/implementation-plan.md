# CoreCode — Phase-by-Phase Implementation Plan

> This document details every missing feature from the Claude Code audit, organized into phases. Each feature includes: what it is, why it matters, how it should work, what components to create/modify, dependencies, acceptance criteria, and estimated effort.

## Implementation Checklist

### Phase A — Critical Fixes
- [x] A.1 Dangerous Command Detection
- [x] A.2 Protected Files and Directories
- [x] A.3 Max Output Tokens Recovery
- [x] A.4 Prompt Too Long Recovery (Reactive Compact)
- [x] A.5 Interactive REPL
- [x] A.6 Checkpointing and Rewind *(implemented as Undo/Redo system with file snapshots, disk persistence, CLI tools)*

### Phase B — Foundation
- [x] B.1 Micro-Compact (Old Tool Results)
- [x] B.2 Sibling Abort (Parallel Tool Cancellation)
- [x] B.3 Tool Timeouts
- [x] B.4 Fuzzy Edit Matching
- [x] B.5 Hooks System
- [x] B.6 Streaming Display in REPL *(built into REPL during A.5)*
- [x] B.7 Permission Modes

### Phase C — Intelligence
- [ ] C.1 Subagent Delegation
- [x] C.2 Session Resumption
- [x] C.3 CLAUDE.md Hierarchy (AGENTS.md Hierarchy)
- [x] C.4 Slash Commands
- [x] C.5 Context Window Sliding
- [x] C.6 Intent Re-injection After Failures

### Phase D — UX
- [ ] D.1 MCP Integration
- [ ] D.2 Model Switching
- [ ] D.3 Prompt Caching (API-Level)
- [ ] D.4 Diff Viewer
- [ ] D.5 Status Bar
- [ ] D.6 Progress Indicators

### Phase E — Advanced
- [ ] E.1 Plan Mode (Read-Only)
- [ ] E.2 Semantic Memory Search
- [ ] E.3 Session Forking
- [ ] E.4 Team Mode (Multi-Agent Collaboration)
- [ ] E.5 Circuit Breaker

### Phase F — Claude Code Parity
- [ ] F.1 Vim Mode
- [ ] F.2 DreamTask (Background Memory Consolidation)
- [ ] F.3 HTML Stats Report
- [ ] F.4 Git Worktree Isolation
- [ ] F.5 Conflict Resolution
- [ ] F.6 Transcript Viewer

### Phase G — Beyond Claude Code
- [ ] G.1 Autonomous Background Tasks
- [ ] G.2 Predictive Context Prefetching
- [ ] G.3 Knowledge Graph of Codebase
- [ ] G.4 Multi-Model Orchestration
- [ ] G.5 Workflow Automation
- [ ] G.6 Rich Observability Dashboards

---

## Table of Contents

- [Phase A — Critical Fixes (1-2 weeks)](#phase-a--critical-fixes-1-2-weeks)
- [Phase B — Foundation (2-3 weeks)](#phase-b--foundation-2-3-weeks)
- [Phase C — Intelligence (2-3 weeks)](#phase-c--intelligence-2-3-weeks)
- [Phase D — UX (2-3 weeks)](#phase-d--ux-2-3-weeks)
- [Phase E — Advanced (3-4 weeks)](#phase-e--advanced-3-4-weeks)
- [Phase F — Claude Code Parity (4-6 weeks)](#phase-f--claude-code-parity-4-6-weeks)
- [Phase G — Beyond Claude Code (6-8 weeks)](#phase-g--beyond-claude-code-6-8-weeks)

---

## Phase A — Critical Fixes (1-2 weeks)

These are the highest-impact, lowest-effort items. They fix security holes, prevent data loss, and make the agent actually usable as a daily tool.

---

### A.1 Dangerous Command Detection

**What:** Block shell commands that can cause irreversible damage before they execute.

**Why:** CoreCode currently passes any command to the Docker sandbox or host shell. A prompt injection in a cloned repo could execute `rm -rf /` or `git push --force origin main`. This is a security-critical gap.

**How it should work:**

1. Create a new file `src/coding_agent/sandbox/danger_patterns.py` containing:
   - A list of blocked command patterns (regex-based): `rm -rf /`, `rm -rf ~`, `git push --force`, `DROP TABLE`, `DELETE FROM`, `FORMAT`, `mkfs`, `dd if=`, `shutdown`, `reboot`, `:(){ :|:& };:` (fork bomb), etc.
   - Case-insensitive matching with whitespace normalization to prevent bypasses like `rm  -rf  /`.
   - A function `check_dangerous_command(command: str) -> tuple[bool, str]` that returns `(is_dangerous, reason)`.

2. Integrate into `tools/shell.py`:
   - Before executing any command via `execute_command`, run it through `check_dangerous_command()`.
   - If dangerous, return a `ToolResult(success=False, error="Blocked: <reason>")` without executing.
   - Log the blocked command as a warning.

3. Add a config option `CODING_AGENT_BLOCK_DANGEROUS=true` (default) in `config.py` to allow users to disable the check if needed.

**Components to create/modify:**
- Create: `src/coding_agent/sandbox/danger_patterns.py`
- Modify: `src/coding_agent/tools/shell.py`
- Modify: `src/coding_agent/config.py`

**Acceptance criteria:**
- `rm -rf /` is blocked regardless of spacing/casing.
- `git push --force origin main` is blocked.
- `DROP TABLE users` is blocked.
- `echo "rm -rf /"` is NOT blocked (it's inside quotes, not a real command — but note this is a limitation; the check should be on the raw command string, not parsed).
- Safe commands like `ls`, `git status`, `python -m pytest` pass through.
- The check adds less than 1ms overhead.

**Effort:** 3-5 hours

---

### A.2 Protected Files and Directories

**What:** Prevent the agent from modifying critical configuration files and directories.

**Why:** Without this, the agent could overwrite `.gitconfig`, `.bashrc`, `.ssh/authorized_keys`, or `.env` files containing secrets. This is especially dangerous because the agent operates autonomously.

**How it should work:**

1. Create `src/coding_agent/sandbox/protected_paths.py` containing:
   - A set of protected file patterns: `.gitconfig`, `.bashrc`, `.zshrc`, `.profile`, `.ssh/*`, `.gnupg/*`, `.env`, `.env.*`, `.mcp.json`, `.claude.json`, etc.
   - A set of protected directories: `.git/`, `.vscode/`, `.idea/`, `.claude/`, `node_modules/`, `.venv/`, etc.
   - A function `is_protected_path(path: str) -> tuple[bool, str]` that returns `(is_protected, reason)`.
   - Case-insensitive normalization for cross-platform safety.

2. Integrate into `tools/file_ops.py`:
   - Before `write_file` and `edit_file`, check if the target path is protected.
   - If protected, return `ToolResult(success=False, error="Protected path: <reason>")`.
   - Add a config option `CODING_AGENT_PROTECTED_PATHS=true` (default) to allow override.

3. The protected paths list should be extensible via a config file or environment variable so users can add their own protected paths.

**Components to create/modify:**
- Create: `src/coding_agent/sandbox/protected_paths.py`
- Modify: `src/coding_agent/tools/file_ops.py`
- Modify: `src/coding_agent/config.py`

**Acceptance criteria:**
- Writing to `~/.gitconfig` is blocked.
- Writing to `.env` is blocked.
- Writing to `.ssh/authorized_keys` is blocked.
- Writing to `.git/` directory is blocked.
- Writing to `src/main.py` (normal file) is allowed.
- The check is path-normalized (handles `../`, `./`, absolute vs relative).

**Effort:** 2-3 hours

---

### A.3 Max Output Tokens Recovery

**What:** When the LLM hits its max output token limit mid-response, feed the partial response back and ask the model to continue.

**Why:** Without this, if a response is cut off at 4096 tokens, the agent loses the rest of the response and may produce incomplete work. Claude Code handles this by feeding the partial back and asking the model to continue where it left off.

**How it should work:**

1. In `agent/loop.py`, after the streaming loop completes, check the `stop_reason` from the LLM response.
   - If `stop_reason == "max_tokens"` (or equivalent for non-Anthropic providers), the response was truncated.
   - Store the partial text and partial tool calls.

2. If truncated:
   - Append the partial assistant message to the context.
   - Add a user message: "Your response was cut off. Please continue from where you left off."
   - Loop again (the next iteration will continue the response).
   - Track a `_max_tokens_recovery_count` to prevent infinite loops (max 3 retries).

3. For providers that don't expose `stop_reason`:
   - Heuristic: if the last message ends mid-sentence or mid-JSON, treat it as truncated.
   - Or: if `completion_tokens >= model_max_output_tokens`, treat as truncated.

**Components to modify:**
- Modify: `src/coding_agent/agent/loop.py` (add stop_reason checking and recovery loop)
- Modify: `src/coding_agent/llm/streaming.py` (expose stop_reason in StreamEvent)
- Modify: `src/coding_agent/llm/client.py` (return stop_reason from complete())

**Acceptance criteria:**
- When a response is truncated at max tokens, the agent automatically continues.
- The continuation is seamless (no visible gap in the response).
- Maximum 3 continuation attempts before giving up.
- The recovery is logged with a `max_tokens_recovery` event.

**Effort:** 3-5 hours

---

### A.4 Prompt Too Long Recovery (Reactive Compact)

**What:** When the API returns a `prompt_too_long` or `context_length_exceeded` error, compress the context and retry instead of failing.

**Why:** Without this, long sessions that exceed the context window crash the agent. Claude Code has a layered recovery: try overflow flush first, then reactive compact, with a circuit breaker.

**How it should work:**

1. In `agent/loop.py`, catch the specific API error for context overflow.
   - Error patterns: `prompt_too_long`, `context_length_exceeded`, `maximum context length`, HTTP 400 with context-related message.

2. When caught:
   - **Step 1 (cheap):** Drop the oldest tool results from the conversation history (keep only their summaries). This is the "overflow flush."
   - **Step 2 (heavier):** If Step 1 isn't enough, trigger a full summarization of all messages except the last 3 (not 5 — be more aggressive).
   - **Step 3:** Retry the API call with the compressed context.

3. Track `_reactive_compact_count`. If it fails 3 times consecutively, give up and surface the error to the user.

4. Add a `REACTIVE_COMPACT` event type to `events.py` for TUI visibility.

**Components to modify:**
- Modify: `src/coding_agent/agent/loop.py` (add try/catch around LLM call, reactive compact logic)
- Modify: `src/coding_agent/agent/context.py` (add `drop_oldest_tool_results()` method)
- Modify: `src/coding_agent/agent/events.py` (add `REACTIVE_COMPACT` event type)

**Acceptance criteria:**
- When the API returns context overflow, the agent recovers automatically.
- The recovery is logged and visible in the TUI.
- Maximum 3 recovery attempts before failing.
- The compressed context preserves the most recent messages and the system prompt.

**Effort:** 1 day

---

### A.5 Interactive REPL

**What:** A persistent, interactive terminal interface where the user can send multiple messages in a conversation loop, see streaming responses, and interact with the agent in real time.

**Why:** This is the single most critical missing feature. Without a REPL, CoreCode is a one-shot script, not a tool. Every other feature (slash commands, checkpointing, vim mode, etc.) depends on having a conversation loop.

**How it should work:**

1. Create `src/coding_agent/tui/repl.py` — the main REPL component.
   - Uses Textual for the TUI framework (already attempted, needs proper implementation).
   - Main loop: prompt user → send to agent → stream response → display results → prompt again.
   - The agent's `process_input()` is an async iterator — the REPL consumes events and renders them.

2. Component structure:
   ```
   REPL
   ├── Header (model, provider, workspace, branch)
   ├── MessageArea (scrollable conversation history)
   │   ├── UserMessage
   │   ├── AssistantMessage (streaming text)
   │   ├── ToolCallBlock (tool name, args, result)
   │   ├── ThinkingBlock (if reasoning model)
   │   └── SystemMessage (errors, warnings)
   ├── InputArea (user input with history)
   └── StatusBar (tokens, cost, context %, iteration)
   ```

3. Input handling:
   - Enter sends the message.
   - Shift+Enter or Alt+Enter inserts a newline.
   - Up/Down navigates input history.
   - Ctrl+C interrupts the current agent turn (keeps work done so far).
   - Ctrl+D exits.

4. Streaming display:
   - Text tokens are rendered character-by-character as they arrive.
   - Tool calls show a spinner while executing.
   - Tool results appear inline with syntax highlighting for code.

5. The REPL should handle the agent's async event stream and render each event type appropriately.

**Components to create/modify:**
- Create: `src/coding_agent/tui/repl.py`
- Create: `src/coding_agent/tui/widgets.py` (message components)
- Create: `src/coding_agent/tui/theme.py` (colors, styles)
- Modify: `src/coding_agent/main.py` (add `repl` command that launches the TUI)
- Modify: `src/coding_agent/agent/loop.py` (ensure clean async iterator protocol)

**Dependencies:** Textual library (already in project history, needs re-integration).

**Acceptance criteria:**
- User can start a REPL session with `coding-agent repl`.
- User can type messages and see streaming responses.
- Tool calls are displayed with progress indicators.
- The conversation persists across multiple turns.
- Ctrl+C interrupts gracefully without crashing.
- The REPL handles terminal resize events.

**Effort:** 3-5 days

---

### A.6 Checkpointing and Rewind

**What:** Automatically snapshot file state before each edit, and provide a `/rewind` command to restore previous states.

**Why:** Without checkpointing, users are afraid to let the agent make large-scale changes because there's no undo beyond the in-memory UndoStack (which is lost on restart). Claude Code's checkpointing system is what makes users comfortable letting the agent work autonomously.

**How it should work:**

1. Create `src/coding_agent/agent/checkpoint.py`:
   - `Checkpoint` dataclass: `id`, `timestamp`, `file_snapshots: dict[str, bytes]`, `message_index`.
   - `CheckpointManager` class:
     - `create_checkpoint()` — captures current content of all modified files since last checkpoint.
     - `restore_checkpoint(checkpoint_id)` — reverts files to their state at that checkpoint.
     - `list_checkpoints()` — returns recent checkpoints (max 100).
     - Ring buffer: automatically evicts checkpoints beyond 100.

2. Integration into `agent/loop.py`:
   - Before each file-modifying tool call (`write_file`, `edit_file`), create a checkpoint.
   - Store the checkpoint alongside the message index so rewinding can restore both code and conversation.

3. Rewind command:
   - `/rewind` — shows a numbered list of recent checkpoints with timestamps and descriptions.
   - `/rewind <n>` — restores checkpoint n, reverting both files and conversation to that point.
   - Options: "Restore code only", "Restore conversation only", "Restore both".

4. Persistence:
   - Store checkpoint metadata in SQLite (via `SessionManager`).
   - Store file snapshots as blobs in SQLite or as files in `~/.coding-agent/checkpoints/`.
   - Checkpoints survive session restart.

**Components to create/modify:**
- Create: `src/coding_agent/agent/checkpoint.py`
- Modify: `src/coding_agent/agent/loop.py` (create checkpoints before edits)
- Modify: `src/coding_agent/session/manager.py` (add checkpoint tables)
- Modify: `src/coding_agent/agent/events.py` (add `CHECKPOINT` event type)

**Acceptance criteria:**
- Before every file edit, a checkpoint is created.
- `/rewind` shows the last 10 checkpoints.
- `/rewind 3` restores the 3rd checkpoint, reverting files and conversation.
- Checkpoints survive session restart.
- The ring buffer caps at 100 checkpoints.
- Restoring a checkpoint correctly reverts file contents (verified by checksum).

**Effort:** 3-5 days

---

## Phase B — Foundation (2-3 weeks)

These features improve robustness, extensibility, and correctness of the existing systems.

---

### B.1 Micro-Compact (Old Tool Results)

**What:** Clear or compress old tool results in the conversation history to free up context space.

**Why:** Tool results can be massive (a `read_file` of a 500-line file = ~5000 tokens). Over many iterations, these accumulate and fill the context window. Claude Code's micro-compact replaces old tool results with `[Old tool result content cleared]` to reclaim space.

**How it should work:**

1. In `agent/loop.py`, after each iteration, identify tool results that are:
   - More than 10 messages old (not in the recent window).
   - Larger than 500 tokens.

2. Replace their content with a compact marker:
   ```
   [Old tool result for read_file(src/main.py) cleared to save context space]
   ```

3. The marker preserves: tool name, arguments (truncated), success/failure status.

4. This runs as a lightweight pass — no LLM call required.

5. Track how many tokens were reclaimed via metrics.

**Components to modify:**
- Modify: `src/coding_agent/agent/context.py` (add `compact_old_tool_results()` method)
- Modify: `src/coding_agent/agent/loop.py` (call compact after each iteration)

**Acceptance criteria:**
- Tool results older than 10 messages are replaced with compact markers.
- The compaction preserves tool name, path/args, and success status.
- No LLM call is needed for micro-compact.
- At least 20% of context is reclaimed in a typical 20-iteration session.
- Recent tool results (last 10 messages) are never compacted.

**Effort:** 1 day

---

### B.2 Sibling Abort (Parallel Tool Cancellation)

**What:** When a parallel tool call fails, cancel all sibling parallel tool calls that are still running.

**Why:** Without this, if one parallel read fails (e.g., file not found), the others continue wastefully. Claude Code uses an abort controller to cancel siblings, which saves time and tokens.

**How it should work:**

1. In `agent/loop.py`, wrap parallel tool execution in a try/catch:
   ```python
   async def _exec_one(pc, abort_event):
       if abort_event.is_set():
           return pc, ToolResult(success=False, error="Cancelled")
       result = await tool_registry.execute_from_llm(pc["tc"])
       return pc, result
   ```

2. Create an `asyncio.Event` as the abort signal.
   - If any tool in the parallel batch fails, set the abort event.
   - Remaining tools check the event before executing and after each await point.
   - Tools that are already running continue to completion (can't interrupt synchronous operations) but their results are discarded.

3. For tools that support cancellation (async I/O operations), add an optional `cancel()` method to `BaseTool`.

**Components to modify:**
- Modify: `src/coding_agent/agent/loop.py` (add abort event to parallel execution)
- Modify: `src/coding_agent/tools/base.py` (add optional `cancel()` method)

**Acceptance criteria:**
- If one parallel tool fails, siblings that haven't started yet are skipped.
- Siblings that are already running continue but their results are marked as cancelled.
- The abort event is properly cleaned up after each parallel batch.
- No resource leaks (tasks are properly awaited or cancelled).

**Effort:** 3-5 hours

---

### B.3 Tool Timeouts

**What:** Add configurable timeouts to all tool executions, not just shell commands.

**Why:** `read_file` on a network mount, `search_content` on a massive monorepo, or a hung `git diff` can block the agent indefinitely. Claude Code has a 120-second default timeout for bash and applies timeouts to other operations.

**How it should work:**

1. Add a `timeout_seconds` field to the `@tool` decorator:
   ```python
   @tool(name="read_file", timeout=30)
   async def read_file(path: str) -> str:
       ...
   ```

2. Default timeout: 30 seconds for file operations, 60 seconds for search, 120 seconds for shell.

3. In `tools/registry.py`, wrap tool execution with `asyncio.wait_for()`:
   ```python
   result = await asyncio.wait_for(
       tool.execute(**arguments),
       timeout=tool.timeout_seconds
   )
   ```

4. On timeout, return `ToolResult(success=False, error="Tool timed out after Xs")`.

5. Make timeouts configurable via `config.py` (global defaults that tools can override).

**Components to modify:**
- Modify: `src/coding_agent/tools/base.py` (add `timeout_seconds` field)
- Modify: `src/coding_agent/tools/registry.py` (wrap execution with timeout)
- Modify: `src/coding_agent/config.py` (add timeout defaults)
- Modify: `src/coding_agent/tools/shell.py` (use configurable timeout instead of hardcoded)

**Acceptance criteria:**
- Every tool call has a timeout (configurable, with sensible defaults).
- On timeout, a clear error message is returned to the LLM.
- Timeouts are logged for debugging.
- Shell commands still use the existing sandbox timeout (whichever is shorter).

**Effort:** 2-3 hours

---

### B.4 Fuzzy Edit Matching

**What:** When the `edit_file` tool's exact text match fails, fall back to fuzzy matching to find the closest match.

**Why:** The current `edit_file` requires byte-exact matching of `old_text`. If the file has slightly different whitespace, encoding, or the user provides slightly wrong text, the edit fails. Claude Code uses fuzzy matching as a fallback.

**How it should work:**

1. In `tools/file_ops.py`, when `old_text` is not found exactly:
   - Normalize whitespace (collapse multiple spaces, strip trailing whitespace) and try again.
   - If still not found, use `difflib.get_close_matches()` to find the closest substring.
   - If a close match is found (similarity > 0.8), use it and log a warning.
   - If no close match is found, return the original error.

2. The fuzzy fallback should:
   - Never silently change code that wasn't requested to change.
   - Show the matched text in the response so the user can verify.
   - Be opt-in via a `fuzzy: true` parameter (default: false for safety).

**Components to modify:**
- Modify: `src/coding_agent/tools/file_ops.py` (add fuzzy matching fallback in `edit_file`)

**Acceptance criteria:**
- Exact matches work as before (no regression).
- With `fuzzy: true`, whitespace differences are tolerated.
- With `fuzzy: true`, close matches are found with >80% similarity.
- Fuzzy matches are logged with the matched text for transparency.
- Fuzzy matching never silently changes unrelated code.

**Effort:** 1 day

---

### B.5 Hooks System

**What:** Let users inject deterministic code at lifecycle events — shell commands that fire automatically before/after tool calls, on session start, etc.

**Why:** "You can't hope the AI remembers to lint your files." Hooks give deterministic control over a probabilistic system. They enforce formatting, security rules, testing requirements, and audit logging without relying on the model.

**How it should work:**

1. Create `src/coding_agent/hooks/` package:
   - `manager.py` — `HookManager` class that loads, validates, and executes hooks.
   - `types.py` — Hook event types, hook configurations, hook results.
   - `executor.py` — Runs hook commands with timeout and error handling.

2. Hook events (start with the most useful):
   - `PreToolUse` — fires before a tool executes. Exit code 2 = block the tool.
   - `PostToolUse` — fires after a tool executes. Can modify the result.
   - `SessionStart` — fires when the REPL starts.
   - `SessionEnd` — fires when the REPL exits.
   - `UserPromptSubmit` — fires when the user submits a prompt. Exit code 2 = block submission.

3. Hook configuration (stored in `~/.coding-agent/hooks.json`):
   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "write_file|edit_file",
           "hooks": [
             {
               "type": "command",
               "command": "ruff check $TOOL_PATH",
               "timeout": 10000
             }
           ]
         }
       ]
     }
   }
   ```

4. Hook execution:
   - Environment variables passed to the hook: `$TOOL_NAME`, `$TOOL_ARGS`, `$TOOL_PATH`, `$TOOL_RESULT`, `$WORKSPACE`.
   - Exit code 0 = success, 1 = warning (log but continue), 2 = block (prevent the action).
   - Timeout: configurable per hook (default 10s).

5. Integration into `agent/loop.py`:
   - Before tool execution: run PreToolUse hooks. If any returns exit code 2, block the tool.
   - After tool execution: run PostToolUse hooks. If any returns exit code 2, mark the result as blocked.

**Components to create/modify:**
- Create: `src/coding_agent/hooks/__init__.py`
- Create: `src/coding_agent/hooks/manager.py`
- Create: `src/coding_agent/hooks/types.py`
- Create: `src/coding_agent/hooks/executor.py`
- Modify: `src/coding_agent/agent/loop.py` (integrate hook calls)
- Modify: `src/coding_agent/config.py` (add hooks config path)

**Acceptance criteria:**
- Hooks are loaded from `~/.coding-agent/hooks.json`.
- PreToolUse hook with exit code 2 blocks the tool call.
- PostToolUse hook runs after every tool call.
- Hooks have a configurable timeout (default 10s).
- Hook failures are logged but don't crash the agent.
- Environment variables are passed to hooks correctly.

**Effort:** 3-5 days

**Status:** ✅ Complete (2026-07-17)
- Created `hooks/types.py` — `HookEvent`, `HookConfig`, `HookResult` dataclasses
- Created `hooks/executor.py` — `run_hook()` async subprocess with timeout, exit code handling
- Created `hooks/manager.py` — `HookManager` loads `~/.coding-agent/hooks.json`, matches tool names via regex, runs pre/post hooks
- Created `hooks/__init__.py` — public exports
- Updated `config.py` — `hooks_enabled` and `hooks_config_path` fields
- Updated `loop.py` — `HookManager` init, pre-hook blocking (exit code 2 → skip tool), post-hook logging
- Updated `events.py` — `HOOK_BLOCK` event type
- Updated `repl.py` — renders hook-blocked tool warnings in TUI

---

### B.6 Streaming Display in REPL

**What:** Render LLM response tokens character-by-character in real time as they arrive from the API.

**Why:** Without streaming display, users stare at a blank screen for seconds waiting for responses. Streaming provides immediate feedback that the agent is working.

**How it should work:**

1. The REPL consumes the agent's async event stream.
2. When a `TEXT` event arrives, append the token to the current assistant message widget.
3. Use Textual's `Timer` or `call_later` to batch token updates (every 50ms) to avoid excessive re-renders.
4. Tool calls show a spinner widget while executing, replaced by the result when done.
5. Thinking/reasoning tokens (if available) are displayed in a dimmed style.

**Components to modify:**
- Modify: `src/coding_agent/tui/repl.py` (consume streaming events)
- Modify: `src/coding_agent/tui/widgets.py` (streaming message widget)

**Acceptance criteria:**
- Text appears character-by-character as tokens arrive.
- No visible flicker or lag.
- Tool calls show progress indicators.
- The display updates at least every 100ms during streaming.

**Effort:** 1-2 days

---

### B.7 Permission Modes

**What:** Multiple permission modes that control how aggressively the agent auto-approves tool calls.

**Why:** The current system has a binary approve/deny per tool name. Claude Code has 5 modes that give users fine-grained control over agent autonomy.

**How it should work:**

1. Add permission modes to `agent/permissions.py`:
   - `default` (`>`) — Ask for all non-read tools. Current behavior.
   - `acceptEdits` (`>>`) — Auto-allow file edits in the current workspace. Only ask for shell commands.
   - `plan` (`?`) — Pause after every tool call. Show the result and ask "Continue?"
   - `bypassPermissions` (`!`) — Skip all permission checks. (Dangerous, requires confirmation to enter.)
   - `auto` (future) — LLM classifier decides based on risk assessment.

2. The mode is set at REPL startup and can be changed via `/permissions` slash command.

3. `acceptEdits` mode:
   - Auto-allow `write_file`, `edit_file` when the path is within the workspace directory.
   - Still ask for `execute_command`, `git_commit`, and tools with `dangerous` permission level.

4. `plan` mode:
   - After every tool call, yield a `PERMISSION_REQUEST` event and wait for user input.
   - The REPL shows the tool result and prompts "Continue? [Y/n]".

5. `bypassPermissions` mode:
   - Enter with `!` prefix or `/permissions bypass`.
   - Show a warning: "All permission checks are disabled. The agent can modify any file and run any command."
   - Auto-disable after session end.

**Components to modify:**
- Modify: `src/coding_agent/agent/permissions.py` (add modes)
- Modify: `src/coding_agent/agent/loop.py` (check mode before permission gate)

**Acceptance criteria:**
- `/permissions` shows the current mode.
- `/permissions default` switches to default mode.
- `/permissions acceptEdits` auto-allows file edits in workspace.
- `/permissions plan` pauses after every tool call.
- `/permissions bypass` shows a warning and disables all checks.
- Mode changes take effect immediately.

**Effort:** 1-2 days

---

## Phase C — Intelligence (2-3 weeks)

These features make the agent smarter about how it works — better context management, session continuity, and task decomposition.

---

### C.1 Subagent Delegation

**What:** Allow the main agent to spawn child agents that work on bounded subtasks in parallel, each with their own isolated context.

**Why:** A single agent working on a large refactor fills its context with exploration before getting to the actual task. Subagents isolate exploration, preserve the main agent's context for synthesis, and enable true parallelism.

**How it should work:**

1. Create `src/coding_agent/agent/subagent.py`:
   - `SubAgent` class that wraps an `AgentLoop` instance.
   - Each subagent gets:
     - A fresh `ContextManager` (or forked from parent up to a point).
     - Filtered tool set (no `git_commit`, no `create_plan` — read-only tools only by default).
     - A unique agent ID.
     - A separate undo stack.
     - A bounded iteration limit (default: 20).

2. Create `src/coding_agent/tools/subagent.py`:
   - `delegate_task` tool: the LLM calls this to spawn a subagent.
   - Parameters: `prompt` (what to do), `tools` (optional tool filter), `max_iterations` (optional).
   - Returns the subagent's final text response.

3. Execution model:
   - Subagents run as `asyncio.Task`s.
   - Maximum 3 concurrent subagents (configurable).
   - Depth limit: 1 (subagents cannot spawn sub-subagents).
   - Each subagent has its own LLM client (can share API keys).

4. Result integration:
   - When a subagent completes, its final response is injected into the parent's context as a tool result.
   - The parent can then synthesize the subagent's findings.

**Components to create/modify:**
- Create: `src/coding_agent/agent/subagent.py`
- Create: `src/coding_agent/tools/subagent.py`
- Modify: `src/coding_agent/agent/loop.py` (track subagent tasks)
- Modify: `src/coding_agent/config.py` (add subagent limits)

**Acceptance criteria:**
- The LLM can spawn a subagent via `delegate_task`.
- Subagents run in parallel (up to 3 concurrent).
- Subagents have isolated context (don't pollute parent).
- Subagent results are returned to the parent as tool results.
- Depth limit of 1 is enforced.
- Subagent iterations are capped at 20 by default.

**Effort:** 3-7 days

---

### C.2 Session Resumption

**What:** Allow users to resume a previous session from where they left off, with full conversation history and context.

**Why:** Without this, every new session starts from scratch. The user has to re-explain the task and re-explore the codebase. Claude Code's `--resume` flag loads the previous session's conversation history and continues.

**How it should work:**

1. Add `--resume` flag to the CLI:
   ```
   coding-agent repl --resume
   coding-agent repl --resume <session-id>
   ```

2. When `--resume` is used:
   - Load the session's messages from SQLite via `SessionManager.load_session()`.
   - Reconstruct the `ContextManager` message list from the loaded messages.
   - Reload the system prompt (including memory, plan state).
   - Display a summary: "Resumed session <id> from <date>. <N> messages loaded."

3. `--continue` (`-c`) flag: resume the most recent session automatically.
   - Find the most recent session for the current workspace.
   - If no session exists, start a new one.

4. Session listing:
   - `coding-agent history` already lists sessions.
   - Add `coding-agent resume` that shows a numbered list and lets the user pick.

**Components to modify:**
- Modify: `src/coding_agent/main.py` (add `--resume` and `--continue` flags)
- Modify: `src/coding_agent/agent/loop.py` (add `load_session()` method)
- Modify: `src/coding_agent/session/manager.py` (add `load_session_messages()` that returns full message list)

**Acceptance criteria:**
- `coding-agent repl --resume` loads the most recent session.
- `coding-agent repl --resume <id>` loads a specific session.
- The conversation history is fully restored.
- The system prompt is rebuilt with current environment info.
- Plan state and memory are restored from the database.

**Effort:** 1 day

---

### C.3 CLAUDE.md Hierarchy (AGENTS.md Hierarchy)

**What:** Support a multi-scope hierarchy of project configuration files that are loaded at session start and injected into the system prompt.

**Why:** Claude Code's 5-scope CLAUDE.md hierarchy (enterprise → user → project → local → rules) lets teams encode project conventions, user preferences, and local overrides in structured files. CoreCode only reads `AGENTS.md` and `README.md` from the workspace root.

**How it should work:**

1. Define the hierarchy (broadest to narrowest):
   ```
   ~/.coding-agent/AGENTS.md           (user global preferences)
   ./AGENTS.md                          (project root, versioned with git)
   ./.coding-agent/AGENTS.md            (project alternative location)
   ./.coding-agent/rules/*.md           (project rules, modular)
   ./AGENTS.local.md                    (local, gitignored, personal)
   ```

2. Load order: broadest first, narrowest last. Narrower files can override broader ones.

3. Support `@path/to/file` import syntax:
   - `@./path/to/file.md` — resolves relative to the importing file.
   - Maximum nesting depth: 4 hops.
   - Prevent circular imports.

4. In `system_prompt.py`, replace the current `_project_context_section()` with a new `_agents_md_section()` that:
   - Walks the hierarchy and loads all matching files.
   - Concatenates them in order (broadest first).
   - Respects `@path` imports.
   - Truncates the total to 2000 tokens (configurable).

5. File format: plain markdown with optional frontmatter:
   ```markdown
   ---
   scope: project
   description: Project coding conventions
   ---
   
   ## Code Style
   - Use snake_case for Python
   - Use double quotes for strings
   ```

**Components to modify:**
- Modify: `src/coding_agent/agent/system_prompt.py` (replace `_project_context_section` with hierarchy loader)
- Create: `src/coding_agent/agent/agents_md.py` (hierarchy loader with import resolution)

**Acceptance criteria:**
- `~/.coding-agent/AGENTS.md` is loaded for all projects.
- `./AGENTS.md` is loaded for the current project.
- `.coding-agent/rules/*.md` files are loaded as modular rules.
- `@path/to/file.md` imports resolve correctly (max 4 hops).
- Circular imports are detected and prevented.
- The total loaded content is truncated at 2000 tokens.

**Effort:** 1-2 days

---

### C.4 Slash Commands

**What:** In-session `/` commands for controlling the agent's behavior, checking status, and performing common operations.

**Why:** Slash commands are the primary control surface for Claude Code. They let users switch models, compact context, check costs, and manage sessions without leaving the conversation flow.

**How it should work:**

1. Create `src/coding_agent/commands/` package:
   - `registry.py` — `CommandRegistry` class that maps command names to handlers.
   - `types.py` — `Command` dataclass with name, description, handler function, parameters.

2. Built-in commands (start with the most useful):

   | Command | Description |
   |---------|-------------|
   | `/help` | List available commands |
   | `/clear` | Reset conversation (keep session) |
   | `/compact` | Force summarization of context |
   | `/cost` | Show current session cost |
   | `/tokens` | Show token usage breakdown |
   | `/model` | Switch model mid-session |
   | `/permissions` | Show/change permission mode |
   | `/plan` | Show current plan state |
   | `/memory` | Show/manage memories |
   | `/rewind` | Restore a checkpoint |
   | `/history` | Show session history |

3. Command parsing:
   - Detect input starting with `/` at the REPL level (before sending to agent).
   - Parse command name and arguments.
   - Execute the command handler.
   - Display the result in the TUI.
   - If the command is not recognized, send it to the agent as a regular message.

4. Custom commands:
   - Load from `~/.coding-agent/commands/*.md` and `.coding-agent/commands/*.md`.
   - Each markdown file defines a command: filename = command name, content = prompt template.
   - Support `$ARGUMENTS` placeholder.

**Components to create/modify:**
- Create: `src/coding_agent/commands/__init__.py`
- Create: `src/coding_agent/commands/registry.py`
- Create: `src/coding_agent/commands/types.py`
- Create: `src/coding_agent/commands/builtin.py` (implementations)
- Modify: `src/coding_agent/tui/repl.py` (parse `/` commands before sending to agent)

**Acceptance criteria:**
- `/help` lists all available commands.
- `/cost` shows the current session cost.
- `/compact` forces context summarization.
- `/model` switches the active model.
- `/rewind` shows checkpoints and lets the user restore one.
- Unrecognized `/` commands are sent to the agent as messages.
- Custom commands are loaded from `.coding-agent/commands/`.

**Effort:** 2-3 days

---

### C.5 Context Window Sliding

**What:** Drop the oldest message groups when the context window is approaching its limit, rather than waiting for full summarization.

**Why:** Summarization is expensive (requires an LLM call). Sometimes a cheaper approach is to simply drop the oldest messages. Claude Code uses this as a fallback before reactive compact.

**How it should work:**

1. In `agent/context.py`, add a `drop_oldest_messages(count: int)` method:
   - Remove the oldest `count` messages from `self.messages`.
   - Preserve the system prompt and summary.
   - Log the dropped messages for debugging.

2. Trigger in `agent/loop.py`:
   - At 90% context usage, drop the oldest 20% of messages.
   - At 95%, drop the oldest 40% (if summarization hasn't helped).
   - This is a cheaper alternative to summarization.

3. The dropped messages are not lost — they were already summarized (if summarization ran earlier) or they are old enough that the model has moved past them.

**Components to modify:**
- Modify: `src/coding_agent/agent/context.py` (add `drop_oldest_messages()`)
- Modify: `src/coding_agent/agent/loop.py` (trigger sliding at thresholds)

**Acceptance criteria:**
- At 90% context, oldest 20% of messages are dropped.
- System prompt and summary are never dropped.
- The drop is logged with the number of messages removed and tokens reclaimed.
- The agent continues functioning normally after the drop.

**Effort:** 1 day

**Status:** ✅ Complete (2026-07-17)
- Added `drop_oldest_messages(fraction)` to `context.py` — drops oldest N% of messages, preserves at least 1
- Added 90% threshold in `_check_context_usage()` — drops oldest 20% before summarization
- Added 95% threshold in `_check_context_usage()` — drops oldest 40% before summarization
- Logs `context_sliding` events with dropped count, remaining count, and threshold
- Cheaper alternative to LLM summarization

---

### C.6 Intent Re-injection After Failures

**What:** When tool calls fail repeatedly, re-inject the original task description into the context to prevent the agent from losing sight of its goal.

**Why:** Repeated tool failures dilute the original intent with error noise. The agent may start chasing error messages instead of the original task. Claude Code uses PostToolUse hooks to re-inject intent.

**How it should work:**

1. In `agent/loop.py`, after each tool failure:
   - Check the error tracker for consecutive failures (same tool, same error).
   - If 2+ consecutive failures, inject a system message:
     ```
     [system] REMINDER: Your current task is: <original user prompt>.
     You have failed <N> times. Try a different approach.
     ```

2. The reminder is injected as a user message (not a tool result) so the model sees it as context.

3. Track `_last_reminder_iteration` to avoid injecting the reminder every iteration (max once per 3 iterations).

**Components to modify:**
- Modify: `src/coding_agent/agent/loop.py` (add reminder injection after consecutive failures)

**Acceptance criteria:**
- After 2+ consecutive failures, the original task is re-injected.
- The reminder is injected at most once per 3 iterations.
- The reminder includes the failure count and a suggestion to try a different approach.
- The agent visibly changes its approach after the reminder.

**Effort:** 3-5 hours

**Status:** ✅ Complete (2026-07-17)
- Added `_original_user_input`, `_last_reminder_iteration`, `_reminder_cooldown`, `_current_iteration` state vars to `AgentLoop.__init__`
- Stored original user input in `process_input()` for re-injection access
- Tracked `_current_iteration` in main loop for cooldown checks
- Added re-injection logic in `_post_tool_actions()`: when `error_tracker.is_stuck()` and cooldown elapsed, injects `[system] REMINDER: Your current task is: <original prompt>. You have failed <N> times.` as a user message
- Uses existing `ErrorTracker.is_stuck()`, `get_consecutive_errors()`, `context.add_user_message()`, and `EventType.STUCK_DETECTED`

---

## Phase D — UX (2-3 weeks)

These features improve the user experience — making the agent feel polished, professional, and pleasant to use.

---

### D.1 MCP Integration

**What:** Connect to external MCP (Model Context Protocol) servers that provide additional tools — database access, GitHub operations, Slack integration, browser automation, etc.

**Why:** CoreCode cannot build every possible integration into its core. MCP provides infinite extensibility. Any team can create an MCP server to expose their internal tools.

**How it should work:**

1. Create `src/coding_agent/mcp/` package:
   - `client.py` — `MCPClient` class that connects to MCP servers via stdio transport.
   - `transport.py` — StdioTransport for communicating with MCP server processes.
   - `types.py` — MCP message types (JSON-RPC based).

2. MCP configuration:
   - Stored in `~/.coding-agent/mcp.json` or `.coding-agent/mcp.json` (project-level).
   - Format:
     ```json
     {
       "servers": {
         "github": {
           "command": "npx",
           "args": ["-y", "@modelcontextprotocol/server-github"],
           "env": { "GITHUB_TOKEN": "..." }
         }
       }
     }
     ```

3. Tool discovery:
   - At session start, connect to all configured MCP servers.
   - Call `tools/list` on each server to discover available tools.
   - Wrap each MCP tool as a `FunctionTool` with name `mcp__{server}__{tool}`.
   - Register in the tool registry.

4. Tool execution:
   - When the LLM calls an MCP tool, route the call to the appropriate MCP server.
   - Pass arguments via `tools/call`.
   - Return the result as a `ToolResult`.

5. Security boundary:
   - MCP tools are marked with `permission_level = "execute"` (require confirmation).
   - MCP tools cannot execute shell commands (blocked by design).
   - MCP tools cannot access files outside the workspace.

**Components to create/modify:**
- Create: `src/coding_agent/mcp/__init__.py`
- Create: `src/coding_agent/mcp/client.py`
- Create: `src/coding_agent/mcp/transport.py`
- Create: `src/coding_agent/mcp/types.py`
- Modify: `src/coding_agent/main.py` (load MCP servers at startup)
- Modify: `src/coding_agent/config.py` (add MCP config path)

**Acceptance criteria:**
- MCP servers are loaded from config at session start.
- MCP tools appear in the tool registry with `mcp__` prefix.
- MCP tools can be called by the LLM and results returned.
- MCP tools require permission confirmation.
- MCP servers that fail to connect are logged and skipped.

**Effort:** 5-7 days

---

### D.2 Model Switching

**What:** Allow the user to switch between models mid-session via a `/model` command.

**Why:** Different tasks benefit from different models. Opus for architecture decisions, Sonnet for routine edits, Haiku for quick lookups. Without mid-session switching, the user must restart the agent.

**How it should work:**

1. `/model` command (no args) shows available models:
   ```
   Current: gemini-2.5-flash
   Available: gemini-2.5-flash, openai/gpt-4o, anthropic/claude-3.5-sonnet
   ```

2. `/model <name>` switches to the specified model:
   - Validate the model name against available providers.
   - Create a new `LLMClient` with the new model.
   - Replace `self.llm_client` in the agent loop.
   - Log the switch.

3. Model aliases:
   - `/fast` → cheapest/fastest available model.
   - `/smart` → most capable available model.

**Components to modify:**
- Modify: `src/coding_agent/commands/builtin.py` (add `/model` command)
- Modify: `src/coding_agent/agent/loop.py` (add `switch_model()` method)
- Modify: `src/coding_agent/llm/client.py` (make model swappable)

**Acceptance criteria:**
- `/model` shows the current model and available options.
- `/model <name>` switches the model for subsequent calls.
- The switch is logged and visible in the status bar.
- Token counting and cost tracking continue correctly after the switch.

**Effort:** 3-5 hours

---

### D.3 Prompt Caching (API-Level)

**What:** Structure the system prompt so that stable content (behavioral instructions, tool definitions) is cached by the API provider, reducing costs for long sessions.

**Why:** The system prompt is rebuilt every request but 80% of it is identical across requests. Anthropic's prompt caching API can cache this content, reducing costs by 50-80%.

**How it should work:**

1. The current `system_prompt.py` already has a static/dynamic split with `DYNAMIC_BOUNDARY`.
   - Static: behavioral rules, tool usage policy, safety guardrails.
   - Dynamic: environment info, project context, memory, plan state.

2. For Anthropic models: use the `cache_control` parameter in the API request:
   ```python
   {
     "role": "system",
     "content": [
       {"type": "text", "text": static_prompt, "cache_control": {"type": "ephemeral"}},
       {"type": "text", "text": dynamic_prompt}
     ]
   }
   ```

3. For other providers: structure the prompt so the static part is first and longest, maximizing the chance of implicit caching.

4. Track cache hit/miss in the usage data and display in the status bar.

**Components to modify:**
- Modify: `src/coding_agent/llm/client.py` (add cache_control for Anthropic provider)
- Modify: `src/coding_agent/agent/system_prompt.py` (ensure static/dynamic boundary is clean)

**Acceptance criteria:**
- Static prompt content is marked as cacheable for Anthropic models.
- Cache hits are tracked and displayed.
- Cost savings from caching are visible in the `/cost` output.
- Non-Anthropic providers are unaffected.

**Effort:** 1 day

---

### D.4 Diff Viewer

**What:** Display file changes as colored diffs in the TUI, with additions in green and deletions in red.

**Why:** Without a diff viewer, users can't see what the agent changed. They have to manually run `git diff`. A built-in diff viewer makes the agent transparent and trustworthy.

**How it should work:**

1. Create `src/coding_agent/tui/diff_viewer.py`:
   - Takes `old_content` and `new_content` (or a unified diff string).
   - Renders with colored output: green for additions, red for deletions, white for context.
   - Supports scrolling for large diffs.
   - Shows file path and change summary (N additions, N deletions).

2. Integration:
   - After `edit_file` or `write_file`, show the diff inline.
   - For `write_file` (new file), show the full content in green.
   - For `edit_file`, show only the changed lines.

3. The diff viewer should be a Textual widget that can be embedded in the message area.

**Components to create/modify:**
- Create: `src/coding_agent/tui/diff_viewer.py`
- Modify: `src/coding_agent/tui/repl.py` (show diffs after file edits)

**Acceptance criteria:**
- After file edits, a colored diff is shown.
- Additions are green, deletions are red.
- Large diffs are scrollable.
- The diff shows file path and change count.

**Effort:** 1-2 days

---

### D.5 Status Bar

**What:** A persistent bar at the bottom of the TUI showing current model, token usage, cost, context usage percentage, and iteration count.

**Why:** Users need to see at a glance how much of their budget they've used, what model is active, and how full the context window is. Without this, they have no visibility into the agent's state.

**How it should work:**

1. Create `src/coding_agent/tui/status_bar.py`:
   - Fixed at the bottom of the screen.
   - Shows:
     - Model name and provider (left).
     - Token count: `12.5K / 100K` (context usage).
     - Cost: `$0.23` (accumulated).
     - Iteration: `iter 5`.
     - Permission mode: `>` (default) or `>>` (acceptEdits).

2. Updates in real time as the agent processes.

3. Color coding:
   - Context < 70%: green.
   - Context 70-85%: yellow.
   - Context > 85%: red.

**Components to create/modify:**
- Create: `src/coding_agent/tui/status_bar.py`
- Modify: `src/coding_agent/tui/repl.py` (add status bar to layout)

**Acceptance criteria:**
- Status bar is always visible at the bottom.
- Model, tokens, cost, and iteration are displayed.
- Context usage is color-coded.
- Updates happen in real time.

**Effort:** 3-5 hours

---

### D.6 Progress Indicators

**What:** Show spinners, progress bars, or other visual feedback during long operations.

**Why:** Without progress indicators, users don't know if the agent is working or stuck. This is especially important for tool calls that take several seconds.

**How it should work:**

1. Tool execution indicators:
   - When a tool starts, show a spinner next to the tool name.
   - When the tool completes, replace the spinner with a checkmark or X.
   - For known-duration operations (e.g., running tests), show a progress bar.

2. LLM streaming indicator:
   - Show a pulsing dot while tokens are being generated.
   - Stop when the response is complete.

3. Implementation:
   - Use Textual's `LoadingIndicator` or custom widget.
   - The REPL manages spinner state based on agent events.

**Components to create/modify:**
- Create: `src/coding_agent/tui/widgets.py` (spinner, progress bar widgets)
- Modify: `src/coding_agent/tui/repl.py` (manage indicator state)

**Acceptance criteria:**
- Spinners appear when tools are executing.
- Spinners are replaced by results when done.
- The LLM streaming indicator pulses during generation.
- No visual flicker or layout jumps.

**Effort:** 3-5 hours

---

## Phase E — Advanced (3-4 weeks)

These features add sophisticated capabilities that differentiate CoreCode from basic coding agents.

---

### E.1 Plan Mode (Read-Only)

**What:** Enter a read-only mode where the agent can read files, search code, and analyze the codebase without making any changes. Once a plan is formed, the user approves and the agent switches to execution mode.

**Why:** Without plan mode, the agent may start making changes before fully understanding the codebase. Plan mode forces the agent to think before acting. Claude Code's `/plan` command is one of its most important features.

**How it should work:**

1. `/plan` command enters plan mode:
   - Set a `plan_mode` flag on the agent loop.
   - In plan mode, all write/exec tools are blocked (return error: "In plan mode. Use /plan to exit and start execution.").
   - Read-only tools (read_file, search_content, search_files, list_files, git_*) are allowed.

2. The agent creates a plan using the existing `create_plan` tool.

3. `/plan` again (or `/execute`) exits plan mode:
   - Clear the `plan_mode` flag.
   - The agent begins executing the plan.

4. The plan is displayed in the TUI as a numbered checklist with status indicators.

**Components to modify:**
- Modify: `src/coding_agent/agent/loop.py` (add `plan_mode` flag, block write tools)
- Modify: `src/coding_agent/commands/builtin.py` (add `/plan` command)

**Acceptance criteria:**
- `/plan` enters read-only mode.
- Write tools are blocked in plan mode.
- Read tools work normally in plan mode.
- `/plan` again exits to execution mode.
- The plan is displayed as a checklist in the TUI.

**Effort:** 1 day

---

### E.2 Semantic Memory Search

**What:** Use embeddings to search memories by meaning, not just keyword matching.

**Why:** The current LIKE-based search (`content LIKE %query%`) only finds exact keyword matches. If a user says "the auth bug" but the memory says "login issue in authentication module", LIKE search won't find it. Semantic search understands that "auth bug" and "login issue" are related.

**How it should work:**

1. Create `src/coding_agent/memory/embeddings.py`:
   - Use a lightweight local embedding model (e.g., `sentence-transformers` with `all-MiniLM-L6-v2` — 80MB, runs on CPU).
   - `embed(text: str) -> list[float]` — generate embedding for a text.
   - `similarity(a: list[float], b: list[float]) -> float` — cosine similarity.

2. Modify `session/manager.py`:
   - Add an `embedding BLOB` column to the `memory` table.
   - When saving a memory, generate its embedding and store it.
   - When searching, compute query embedding and rank by cosine similarity.

3. Modify `agent/memory.py`:
   - `recall()` method uses embedding similarity when available.
   - Falls back to LIKE search if embeddings are not available (graceful degradation).

4. The embedding model is loaded lazily (only when memory search is first used) to avoid startup latency.

**Components to create/modify:**
- Create: `src/coding_agent/memory/embeddings.py`
- Modify: `src/coding_agent/session/manager.py` (add embedding column, similarity search)
- Modify: `src/coding_agent/agent/memory.py` (use embeddings for recall)
- Modify: `src/coding_agent/config.py` (add embedding model config)

**Acceptance criteria:**
- Memories are stored with embeddings.
- Recall ranks by semantic similarity, not just keyword match.
- "auth bug" finds "login issue in authentication module".
- The embedding model loads in < 5 seconds.
- Graceful fallback to LIKE search if embeddings are unavailable.

**Effort:** 3-5 days

---

### E.3 Session Forking

**What:** Create an independent branch of the current conversation, allowing the user to explore alternative approaches without losing the original conversation.

**Why:** Sometimes the user wants to try a different approach but doesn't want to lose the current conversation. Session forking is like `git branch` but for agent sessions.

**How it should work:**

1. `/fork` command:
   - Clone the current message history into a new session.
   - Both the original and fork continue independently.
   - The fork shares the same message history up to the fork point.

2. Implementation:
   - Create a new session in SQLite with a `parent_session_id` field.
   - Copy all messages from the parent session up to the current point.
   - The fork gets a new session ID.
   - Both sessions can be resumed independently.

3. The REPL shows which session is active (e.g., "Session: abc123 (forked from def456)").

**Components to modify:**
- Modify: `src/coding_agent/session/manager.py` (add `parent_session_id` column, `fork_session()` method)
- Modify: `src/coding_agent/commands/builtin.py` (add `/fork` command)
- Modify: `src/coding_agent/tui/repl.py` (show session info)

**Acceptance criteria:**
- `/fork` creates a new session with the same history.
- The fork is independent (changes don't affect the parent).
- Both sessions can be resumed.
- The session ID shows the fork relationship.

**Effort:** 1-2 days

---

### E.4 Team Mode (Multi-Agent Collaboration)

**What:** Create named teams of agents that collaborate on a task, sharing a scratchpad and communicating via messages.

**Why:** Some tasks are naturally collaborative — one agent researches while another implements. Team mode enables this without a single agent filling its context with both research and implementation.

**How it should work:**

1. `TeamCreate` tool:
   - Creates a named team with a shared scratchpad directory.
   - Spawns 2-3 agents with different roles (e.g., "researcher", "implementer", "reviewer").

2. `SendMessage` tool:
   - Route messages between team members.
   - Each agent sees messages from other team members in its context.

3. Shared scratchpad:
   - A temporary directory where agents can write findings for other agents to read.
   - Files are cleaned up when the team is disbanded.

4. Shutdown protocol:
   - When the task is complete, the coordinator agent sends a shutdown request.
   - Team members complete their current work and exit.

**Components to create/modify:**
- Create: `src/coding_agent/agent/team.py`
- Create: `src/coding_agent/tools/team.py`
- Modify: `src/coding_agent/agent/loop.py` (team management)

**Acceptance criteria:**
- A team can be created with 2-3 agents.
- Agents can send messages to each other.
- The shared scratchpad is accessible to all agents.
- The team shuts down cleanly when the task is complete.

**Effort:** 3-5 days

---

### E.5 Circuit Breaker

**What:** Automatically disable features that are failing repeatedly, preventing the agent from getting stuck in error loops.

**Why:** Without circuit breakers, a failing feature (e.g., compaction, auto-mode) can cause the agent to retry indefinitely, wasting time and tokens. Claude Code uses circuit breakers for compaction and auto-mode.

**How it should work:**

1. Create `src/coding_agent/agent/circuit_breaker.py`:
   - `CircuitBreaker` class with states: CLOSED (normal), OPEN (failing), HALF_OPEN (testing).
   - `record_failure()` — increment failure count.
   - `record_success()` — reset failure count, move to CLOSED.
   - `is_open()` — return True if too many failures (threshold: 3 consecutive).
   - `reset()` — manually reset to CLOSED.

2. Apply circuit breakers to:
   - Context summarization (already has a lock, add circuit breaker).
   - Reactive compact (prevent retry loops).
   - Subagent spawning (prevent infinite subagent creation).

3. When a circuit breaker opens:
   - Log a warning.
   - Skip the failing operation.
   - Surface an error to the user.

**Components to create/modify:**
- Create: `src/coding_agent/agent/circuit_breaker.py`
- Modify: `src/coding_agent/agent/loop.py` (apply circuit breakers)

**Acceptance criteria:**
- Circuit breaker opens after 3 consecutive failures.
- When open, the failing operation is skipped.
- Circuit breaker resets after a successful operation.
- All circuit breaker state changes are logged.

**Effort:** 1 day

---

## Phase F — Claude Code Parity (4-6 weeks)

These features bring CoreCode to feature parity with Claude Code.

---

### F.1 Vim Mode

**What:** Full vim keybinding support for the input area — motions (w, b, e, $, 0), operators (d, c, y), and text objects (iw, aw, i", a").

**Why:** Power users expect vim keybindings. Claude Code has a full vim implementation. This is a differentiator for developer-focused tools.

**How it should work:**

1. Create `src/coding_agent/tui/vim.py`:
   - State machine: Normal, Insert, Visual, Command modes.
   - Motions: w (word forward), b (word backward), e (end of word), $ (end of line), 0 (start of line).
   - Operators: d (delete), c (change), y (yank).
   - Text objects: iw (inner word), aw (a word), i" (inner quotes), a" (a quotes).
   - Number prefixes: 3dw = delete 3 words.

2. Integration:
   - `/vim` command toggles vim mode.
   - When enabled, the input area processes keystrokes through the vim state machine.
   - Mode indicator in the status bar: `-- NORMAL --`, `-- INSERT --`, `-- VISUAL --`.

**Components to create/modify:**
- Create: `src/coding_agent/tui/vim.py`
- Modify: `src/coding_agent/tui/repl.py` (integrate vim input handling)
- Modify: `src/coding_agent/tui/status_bar.py` (show vim mode)

**Acceptance criteria:**
- `/vim` toggles vim mode on/off.
- Normal mode motions work (w, b, e, $, 0).
- Delete and change operators work (dw, ciw, etc.).
- Mode indicator is shown in the status bar.
- Vim mode persists across REPL sessions.

**Effort:** 3-5 days

---

### F.2 DreamTask (Background Memory Consolidation)

**What:** A background process that reviews recent session transcripts, identifies patterns and preferences, and updates memory files automatically — running when the user is idle.

**Why:** Memory consolidation currently only happens at session end. DreamTask runs during idle time, keeping memories fresh and relevant without user intervention.

**How it should work:**

1. Create `src/coding_agent/agent/dream.py`:
   - `DreamTask` class that runs as a background `asyncio.Task`.
   - Triggered when the user has been idle for > 2 minutes.
   - Reviews the last 10 messages of the current session.
   - Identifies patterns: repeated file paths, common errors, user preferences.
   - Updates memory via `MemoryManager.store()`.
   - Max 30 "turns" of activity per dream cycle.

2. Dream task types:
   - Extract user preferences (e.g., "user prefers snake_case").
   - Extract project conventions (e.g., "project uses pytest, not unittest").
   - Extract ongoing work context (e.g., "working on auth refactor").

3. The dream task is cancellable (if the user sends a new message, the dream stops).

**Components to create/modify:**
- Create: `src/coding_agent/agent/dream.py`
- Modify: `src/coding_agent/agent/loop.py` (trigger dream on idle)
- Modify: `src/coding_agent/tui/repl.py` (detect idle, cancel dream on input)

**Acceptance criteria:**
- DreamTask triggers after 2 minutes of idle time.
- It reviews recent messages and extracts patterns.
- Extracted memories are stored via MemoryManager.
- The dream stops immediately when the user sends a message.
- Max 30 turns per dream cycle.
- Dream activity is logged but not shown in the TUI.

**Effort:** 1-2 days

---

### F.3 HTML Stats Report

**What:** Generate an HTML report showing session statistics — token usage, cost breakdown, tool usage distribution, and context utilization over time.

**Why:** Users need visibility into how they're using the agent. A visual report helps optimize usage and understand cost patterns.

**How it should work:**

1. `/stats` command generates an HTML file and opens it in the browser.

2. Report sections:
   - **Session summary**: model, provider, duration, total tokens, total cost.
   - **Token usage over time**: line chart showing prompt vs completion tokens per iteration.
   - **Tool usage distribution**: pie chart showing which tools were called most.
   - **Cost breakdown**: bar chart showing cost per tool call.
   - **Context utilization**: line chart showing context window usage over time.

3. Implementation:
   - Create `src/coding_agent/stats/report.py`.
   - Use a templated HTML string (no external dependencies — just inline SVG/JS).
   - Write to a temp file and open with `webbrowser.open()`.

**Components to create/modify:**
- Create: `src/coding_agent/stats/__init__.py`
- Create: `src/coding_agent/stats/report.py`
- Modify: `src/coding_agent/commands/builtin.py` (add `/stats` command)

**Acceptance criteria:**
- `/stats` generates an HTML report and opens it.
- The report shows session summary, token usage, tool distribution, and cost.
- Charts are rendered as inline SVG (no external dependencies).
- The report is saved to `~/.coding-agent/stats/` for later viewing.

**Effort:** 3-5 hours

---

### F.4 Git Worktree Isolation

**What:** When running parallel agents or subagents, each agent works in its own git worktree, preventing file conflicts.

**Why:** Without worktree isolation, two agents editing the same file simultaneously will cause conflicts. Git worktrees provide lightweight isolation.

**How it should work:**

1. Create `src/coding_agent/git/worktree.py`:
   - `create_worktree(branch_name: str) -> Path` — creates a git worktree for the given branch.
   - `remove_worktree(worktree_path: Path)` — removes the worktree.
   - `list_worktrees() -> list[Path]` — lists active worktrees.

2. When a subagent is spawned:
   - Create a new worktree with a unique branch name (e.g., `agent/<agent-id>`).
   - The subagent's workspace is set to the worktree path.
   - When the subagent completes, merge or cherry-pick its changes back.

3. Worktree cleanup:
   - On session end, remove all agent worktrees.
   - Option to keep worktrees for manual review.

**Components to create/modify:**
- Create: `src/coding_agent/git/worktree.py`
- Modify: `src/coding_agent/agent/subagent.py` (use worktrees for isolation)

**Acceptance criteria:**
- Each subagent gets its own worktree.
- File changes in one worktree don't affect others.
- Worktrees are cleaned up on session end.
- The main agent can merge subagent changes.

**Effort:** 3-5 days

---

### F.5 Conflict Resolution

**What:** When git merge conflicts are detected, the agent reads the conflict markers, understands both sides, and helps resolve them.

**Why:** Developers frequently encounter merge conflicts. An agent that can read and resolve conflicts saves significant time.

**How it should work:**

1. Add a `resolve_conflicts` tool:
   - Reads a file with conflict markers.
   - Parses both sides (ours/theirs).
   - For simple conflicts (formatting, imports), resolves automatically.
   - For complex conflicts, presents both sides and asks the user.

2. Integration:
   - After `git_merge` or `git_rebase`, check for conflict markers.
   - If found, invoke the conflict resolution tool.
   - Show the resolution to the user for approval.

**Components to create/modify:**
- Create: `src/coding_agent/tools/conflict.py`
- Modify: `src/coding_agent/tools/git.py` (add merge/rebase tools)

**Acceptance criteria:**
- The agent can read conflict markers.
- Simple conflicts are resolved automatically.
- Complex conflicts are presented to the user.
- The resolution is verified (no conflict markers remain).

**Effort:** 3-5 days

---

### F.6 Transcript Viewer

**What:** A separate view that shows the full conversation transcript with search and navigation.

**Why:** In long sessions, the user needs to scroll back through the conversation. A dedicated transcript view with search is more efficient than scrolling the main TUI.

**How it should work:**

1. `/transcript` command (or Ctrl+O) toggles the transcript view.
2. The transcript shows all messages in chronological order.
3. Search: `/` to enter search mode, type a query, navigate with `n`/`N`.
4. Navigation: `j`/`k` to scroll, `gg`/`G` to go to top/bottom.
5. Exit with `Esc` or `q`.

**Components to create/modify:**
- Create: `src/coding_agent/tui/transcript.py`
- Modify: `src/coding_agent/tui/repl.py` (toggle transcript view)

**Acceptance criteria:**
- `/transcript` opens the transcript view.
- Full conversation history is displayed.
- Search works across all messages.
- Navigation is smooth (no lag with large transcripts).
- `q` or `Esc` returns to the main view.

**Effort:** 3-5 days

---

## Phase G — Beyond Claude Code (6-8 weeks)

These features go beyond what Claude Code currently offers, positioning CoreCode as a next-generation coding agent.

---

### G.1 Autonomous Background Tasks

**What:** Queue tasks that run in the background while the user works on other things, with notification on completion.

**Why:** Some tasks are long-running (e.g., "run the full test suite and fix all failures"). The user shouldn't have to wait for these to complete.

**How it should work:**

1. `/background <prompt>` command queues a task.
2. The task runs in a background agent with its own session.
3. The user can check status with `/tasks`.
4. When the task completes, a notification is shown in the TUI.
5. The user can view the results with `/tasks show <id>`.

**Components to create/modify:**
- Create: `src/coding_agent/agent/background.py`
- Modify: `src/coding_agent/commands/builtin.py` (add `/background` and `/tasks`)

**Effort:** 3-5 days

---

### G.2 Predictive Context Prefetching

**What:** Analyze the current task and pre-load files the agent is likely to need next, reducing latency.

**Why:** Every `read_file` call takes time. If the agent knows it will need certain files, it can load them proactively.

**How it should work:**

1. After each tool call, analyze the result to predict likely next files:
   - If the agent read `auth/login.py` and saw `from auth.logout import logout`, prefetch `auth/logout.py`.
   - If the agent is editing `main.py`, prefetch test files.

2. Prefetch into the file state cache (if implemented) or a prefetch buffer.

3. When the agent requests a prefetched file, return the cached version immediately.

**Components to create/modify:**
- Create: `src/coding_agent/agent/prefetch.py`
- Modify: `src/coding_agent/agent/loop.py` (trigger prefetch after tool calls)

**Effort:** 3-5 days

---

### G.3 Knowledge Graph of Codebase

**What:** Build and maintain a graph of file→function→class→import relationships for faster navigation and understanding.

**Why:** The current workspace index only tracks file names and languages. A knowledge graph understands the relationships between code elements, enabling smarter search and navigation.

**How it should work:**

1. Create `src/coding_agent/agent/knowledge_graph.py`:
   - Parse Python files with `ast` to extract functions, classes, imports.
   - Build a graph: `File → [Function, Class] → [Import, Call, Inheritance]`.
   - Store in-memory (or SQLite for persistence).

2. Query the graph:
   - "Find all callers of function X" → follow call edges.
   - "Find all files that import module Y" → follow import edges.
   - "Find all subclasses of class Z" → follow inheritance edges.

3. Integrate with search tools to provide structurally-aware search.

**Components to create/modify:**
- Create: `src/coding_agent/agent/knowledge_graph.py`
- Modify: `src/coding_agent/tools/search.py` (add graph-aware search)

**Effort:** 5-7 days

---

### G.4 Multi-Model Orchestration

**What:** Automatically route subtasks to the optimal model without user intervention.

**Why:** Not all tasks need the most expensive model. Simple reads can use Haiku, complex architecture decisions need Opus. Manual switching is tedious.

**How it should work:**

1. Classify each tool call by complexity:
   - Low: read_file, list_files, search_files, git_status → use fast/cheap model.
   - Medium: edit_file, write_file, search_content → use balanced model.
   - High: create_plan, complex shell commands → use advanced model.

2. The classification is based on the tool name and arguments.

3. For each tool call, select the appropriate model and create a temporary LLM client.

4. The main response (where the model decides what to do) always uses the user's selected model.

**Components to create/modify:**
- Create: `src/coding_agent/llm/router.py`
- Modify: `src/coding_agent/agent/loop.py` (use router for tool execution)

**Effort:** 3-5 days

---

### G.5 Workflow Automation

**What:** Save and replay common task sequences (e.g., "create feature → write tests → lint → commit").

**Why:** Developers repeat the same sequences frequently. Workflow automation lets them define these once and replay them.

**How it should work:**

1. `/workflow save <name>` — saves the current task sequence as a named workflow.
2. `/workflow run <name>` — replays the workflow with current context.
3. Workflows are stored as JSON files in `~/.coding-agent/workflows/`.
4. Support parameterized workflows with `$ARGUMENTS` placeholders.

**Components to create/modify:**
- Create: `src/coding_agent/workflows/__init__.py`
- Create: `src/coding_agent/workflows/manager.py`
- Modify: `src/coding_agent/commands/builtin.py` (add `/workflow` command)

**Effort:** 3-5 days

---

### G.6 Rich Observability Dashboards

**What:** Token flow visualization, cost breakdowns, latency histograms, and context utilization graphs — accessible from the TUI.

**Why:** Power users need deep visibility into agent performance to optimize their workflows.

**How it should work:**

1. `/dashboard` command opens a full-screen dashboard view.
2. Panels:
   - Token flow: real-time chart of tokens per iteration.
   - Cost tracker: cumulative cost with per-tool breakdown.
   - Latency: histogram of tool execution times.
   - Context: gauge showing context window utilization.
   - Memory: count and importance distribution of stored memories.

3. The dashboard updates in real time as the agent works.

**Components to create/modify:**
- Create: `src/coding_agent/tui/dashboard.py`
- Modify: `src/coding_agent/commands/builtin.py` (add `/dashboard` command)

**Effort:** 5-7 days

---

## Dependency Graph

```
Phase A (Critical Fixes)
├── A.1 Dangerous Command Detection (independent)
├── A.2 Protected Files/Dirs (independent)
├── A.3 Max Output Recovery (independent)
├── A.4 Prompt Too Long Recovery (depends on context.py changes)
├── A.5 Interactive REPL (independent, but largest effort)
├── A.6 Checkpointing & Rewind (depends on A.5 REPL)
│
Phase B (Foundation)
├── B.1 Micro-Compact (depends on A.4 context changes)
├── B.2 Sibling Abort (independent)
├── B.3 Tool Timeouts (independent)
├── B.4 Fuzzy Edit (independent)
├── B.5 Hooks System (independent)
├── B.6 Streaming Display (depends on A.5 REPL)
├── B.7 Permission Modes (independent)
│
Phase C (Intelligence)
├── C.1 Subagents (depends on B.3 tool timeouts)
├── C.2 Session Resumption (depends on A.5 REPL)
├── C.3 AGENTS.md Hierarchy (independent)
├── C.4 Slash Commands (depends on A.5 REPL)
├── C.5 Context Window Sliding (depends on B.1 micro-compact)
├── C.6 Intent Re-injection (independent)
│
Phase D (UX)
├── D.1 MCP Integration (depends on B.5 hooks for security)
├── D.2 Model Switching (independent)
├── D.3 Prompt Caching (independent)
├── D.4 Diff Viewer (depends on A.5 REPL)
├── D.5 Status Bar (depends on A.5 REPL)
├── D.6 Progress Indicators (depends on A.5 REPL)
│
Phase E (Advanced)
├── E.1 Plan Mode (depends on C.4 slash commands)
├── E.2 Semantic Memory (independent)
├── E.3 Session Forking (depends on C.2 session resumption)
├── E.4 Team Mode (depends on C.1 subagents)
├── E.5 Circuit Breaker (independent)
│
Phase F (Claude Code Parity)
├── F.1 Vim Mode (depends on A.5 REPL)
├── F.2 DreamTask (depends on E.2 semantic memory)
├── F.3 HTML Stats (independent)
├── F.4 Git Worktree (depends on C.1 subagents)
├── F.5 Conflict Resolution (independent)
├── F.6 Transcript Viewer (depends on A.5 REPL)
│
Phase G (Beyond Claude Code)
├── G.1 Background Tasks (depends on C.1 subagents, A.5 REPL)
├── G.2 Predictive Prefetch (depends on F.4 worktree or file cache)
├── G.3 Knowledge Graph (independent)
├── G.4 Multi-Model Orchestration (depends on D.2 model switching)
├── G.5 Workflow Automation (depends on C.4 slash commands, A.5 REPL)
├── G.6 Observability Dashboard (depends on A.5 REPL)
```

---

## Estimated Total Effort

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase A | 1-2 weeks | 1-2 weeks |
| Phase B | 2-3 weeks | 3-5 weeks |
| Phase C | 2-3 weeks | 5-8 weeks |
| Phase D | 2-3 weeks | 7-11 weeks |
| Phase E | 3-4 weeks | 10-15 weeks |
| Phase F | 4-6 weeks | 14-21 weeks |
| Phase G | 6-8 weeks | 20-29 weeks |

**Total estimated time: 5-7 months** (assuming single developer, part-time).

---

## Priority Summary

| Priority | Features | Count |
|----------|----------|-------|
| **Critical** | A.1-A.6 (dangerous commands, protected files, max output, prompt overflow, REPL, checkpoints) | 6 |
| **High** | B.1-B.7 (micro-compact, sibling abort, timeouts, fuzzy edit, hooks, streaming, permissions) + C.1-C.4 (subagents, session resumption, AGENTS.md, slash commands) | 11 |
| **Medium** | C.5-C.6 (context sliding, intent re-injection) + D.1-D.6 (MCP, model switching, prompt caching, diff viewer, status bar, progress) + E.1-E.3 (plan mode, semantic memory, session forking) | 11 |
| **Low** | E.4-E.5 (team mode, circuit breaker) + F.1-F.6 (vim, dream, stats, worktrees, conflicts, transcript) + G.1-G.6 (background tasks, prefetch, knowledge graph, orchestration, workflows, dashboard) | 14 |

**Total features: 42**
