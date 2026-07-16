# CoreCode vs Claude Code — Complete Architecture Audit

## Executive Summary

**CoreCode maturity: Alpha** — solid plumbing, missing critical production infrastructure and intelligence layers that make Claude Code a usable daily driver.

**Estimated feature parity with Claude Code: ~35-40%**

CoreCode has the right foundational patterns (agent loop, tool registry, context management, memory, planning, verification) but is missing the production infrastructure that turns a prototype into a tool people can actually use: no real TUI, no hooks, no MCP, no slash commands, no checkpointing/rewind, no subagents, no native sandbox, no prompt caching via API, no streaming-first architecture, and a CLI-only interface that is not interactive.

---

## 1. Architecture — Overall

### Claude Code
- **~512K lines TypeScript**, 1900 files. Custom React renderer (Ink fork) for TUI.
- Architecture: **LLM + Loop + Tools**. Only 1.6% AI decision logic; 98.4% deterministic infrastructure.
- Streaming-first async generator. Every component yields events.
- QueryEngine is session-scoped, holds mutable message history, abort controller, file state cache (LRU, 100 files, 25MB).
- Layered: `main.tsx → init() → loadAuth() → getSystemContext() → getUserContext() → getAllBaseTools() → getCommands() → launchRepl()`

### CoreCode
- **~8500 lines Python**, 44 source files across 6 packages.
- Architecture: `AgentLoop` class in `agent/loop.py` (1300+ lines). Async iterator yielding `AgentEvent`s.
- CLI via Typer (`main.py`, 676 lines). No interactive REPL — runs once and exits.
- 5 LLM providers (Gemini, OpenRouter, Cerebras, ZenMux, OmniRoute) with key pool rotation.
- Event-based communication (`events.py`, 18 event types).

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Layer separation | 🟢 Mostly Implemented | 7/10 |
| Dependency flow | 🟢 Mostly Implemented | 7/10 |
| Event system | 🟢 Mostly Implemented | 7/10 |
| Pipeline architecture | 🟡 Partially Implemented | 5/10 |
| Modularization | 🟢 Mostly Implemented | 7/10 |
| Plugin architecture | 🔴 Missing | 0/10 |

**Key architectural problems:**

1. **`AgentLoop.__init__` is a god constructor** (`loop.py:88-188`) — initializes 15+ subsystems with module-level `set_*` calls. This is a service locator anti-pattern, not dependency injection.
2. **No interactive REPL** — `main.py` runs `process_input()` once and exits. There's no conversation loop where the user can keep chatting.
3. **`_run_agent_clean` and `_run_agent_raw` are 90% duplicated** (`main.py:136-441` vs `main.py:443-611`) — massive code duplication.
4. **No dependency injection container** — every subsystem is created inline in `main.py`.

---

## 2. Agent Loop

### Claude Code
- Streaming async generator loop. `while(true)` with `response.stop_reason` checks.
- `end_turn` → done. `tool_use` → execute, feed back, loop. `max_tokens` → compact/retry.
- Max-output-tokens recovery: feeds partial response back to model to continue.
- Abort controller for cancellation. 120s bash timeout. 6-hour hard cap.

### CoreCode
- `AgentLoop.process_input()` (`loop.py:258-762`) — async iterator.
- Budget checks: time, cost, max iterations (user + safety net).
- Tool execution: parallel for read-only, sequential for writes.
- Context budget checking at 70%/85%/95% thresholds.
- Stuck detection via `ErrorTracker`.
- Auto-replanning when steps fail.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Core loop | ✅ Fully Implemented | 8/10 |
| Parallel execution | ✅ Fully Implemented | 8/10 |
| Budget controls | ✅ Fully Implemented | 8/10 |
| Early stopping | ✅ Fully Implemented | 7/10 |
| Max output recovery | 🔴 Missing | 0/10 |
| Streaming-first | 🟡 Partially Implemented | 5/10 |
| Cancellation (abort) | 🔴 Missing | 0/10 |

**Missing pieces:**

1. **No `max_tokens` recovery** — if the LLM hits max output tokens, CoreCode just accepts the partial response and loops. Claude Code feeds the partial back and asks the model to continue.
2. **No abort controller** — no way to cancel a running tool call or LLM stream mid-execution.
3. **Streaming is event-buffered, not truly streaming** — `stream()` yields `TEXT` events but the main loop joins them into `text_parts` and only processes after the stream ends for non-tool text.
4. **No `stop_reason` handling** — CoreCode relies on "no tool calls = done" rather than explicit stop reason checking.

---

## 3. Context Engine

### Claude Code
- **Four-layer progressive compression**: micro-compact → auto-compact → session memory compact → reactive compact.
- Context budget: ~200K tokens, reserves 40-45K for response.
- Prompt caching via Anthropic API (stable content first, dynamic last).
- Token counting: API count (exact) + `chars/4` (instant estimate).
- Compaction pipeline: strip images → summarize old → replace with boundary marker → re-inject critical context → hooks.
- Circuit breaker: max 3 consecutive compaction failures.

### CoreCode
- `ContextManager` (`context.py`, 241 lines) — basic message list + summarization.
- `SmartContextEngine` (`context_engine.py`, 264 lines) — priority-based context selection.
- Progressive thresholds: 70% (log), 85% (fire-and-forget summarize), 95% (blocking summarize).
- Tool result truncation via `context_limits.py` (8000 tokens / 500 lines).
- Token estimation via tiktoken (`llm/tokens.py`).
- Static prompt caching via `_STATIC_CACHE` in `system_prompt.py`.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Token estimation | 🟢 Mostly Implemented | 7/10 |
| Progressive compression | 🟡 Partially Implemented | 5/10 |
| Summarization | 🟡 Partially Implemented | 5/10 |
| Micro-compact (old tool results) | 🔴 Missing | 0/10 |
| Session memory compact | 🔴 Missing | 0/10 |
| Reactive compact (API error) | 🔴 Missing | 0/10 |
| Circuit breaker for compaction | 🔴 Missing | 0/10 |
| Prompt caching (API-level) | 🔴 Missing | 0/10 |
| Context prioritization | 🟡 Partially Implemented | 5/10 |
| Context window sliding | 🔴 Missing | 0/10 |

**Critical problems:**

1. **Only 2 compression layers** (fire-and-forget at 85%, blocking at 95%). Claude Code has 4 progressive layers.
2. **No micro-compact** — old tool results (which can be massive) are never cleared or compressed mid-conversation.
3. **No reactive compact** — if the API returns `prompt_too_long`, CoreCode has no recovery path.
4. **SmartContextEngine injects as system message** (`loop.py:730`), which is wasteful — it duplicates information already in the conversation history.
5. **Summarization only keeps last 5 messages** (`context.py:198`) — this is a hard cutoff, not a priority-based selection.

---

## 4. Planning

### Claude Code
- `/plan` enters read-only mode (EnterPlanMode/ExitPlanMode tools).
- Dynamic planning: model decides when to plan, re-plans as it learns.
- TodoWrite (legacy) → Task API (modern) with lifecycle: pending → running → completed/failed/killed.
- Task types: local_bash, local_agent, remote_agent, in_process_teammate, local_workflow, monitor_mcp, dream.

### CoreCode
- `PlanManager` (`planner.py`, 326 lines) — Plan/PlanStep with status tracking.
- `create_plan`/`update_plan` tools for LLM-driven planning.
- Auto-replanning via `_generate_replan()` when steps fail.
- Plan persistence across sessions via SQLite.
- Progress evaluation every N iterations.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Task decomposition | ✅ Fully Implemented | 7/10 |
| Plan persistence | ✅ Fully Implemented | 7/10 |
| Auto-replanning | 🟢 Mostly Implemented | 6/10 |
| Plan mode (read-only) | 🔴 Missing | 0/10 |
| Task API (lifecycle) | 🟡 Partially Implemented | 4/10 |
| Dependency resolution | 🔴 Missing | 0/10 |
| DAG planning | 🔴 Missing | 0/10 |

**Missing:**

1. **No plan mode** — Claude Code can enter a read-only planning mode where it reads/searches without making changes. CoreCode has no such concept.
2. **Plan steps are linear** — no dependency graph, no parallel step execution.
3. **`replace_plan` returns `None`** (`planner.py:148`) — it has `return self._plan` but the method signature says `-> None`. This is a bug.

---

## 5. Tool System

### Claude Code
- 40+ tools. Core 8: Bash, Read, Edit, Write, Grep, Glob, Agent, TodoWrite.
- ToolSearchTool for deferred schema loading (saves tokens with 100+ MCP tools).
- Concurrency-safe batching: partition by `isConcurrencySafe`, parallel reads, serial writes.
- Sibling abort: if one parallel tool fails, cancel siblings.
- Edit tool: exact match + fuzzy fallback + MultiEdit.

### CoreCode
- 15+ tools: read_file, write_file, edit_file, list_files, search_content, search_files, execute_command, git_status/diff/log/commit, create_plan, update_plan, remember, recall, undo, refresh_index, count_tokens.
- `@tool` decorator with auto-schema inference from type hints.
- Parallel-safe set: `_PARALLEL_SAFE_TOOLS` frozenset (`loop.py:50-61`).
- Permission levels per tool: read/write/execute/dangerous.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Tool registry | ✅ Fully Implemented | 8/10 |
| Schema generation | ✅ Fully Implemented | 8/10 |
| Parallel execution | 🟢 Mostly Implemented | 7/10 |
| Permission system | 🟡 Partially Implemented | 5/10 |
| Deferred tool loading | 🔴 Missing | 0/10 |
| Sibling abort | 🔴 Missing | 0/10 |
| Fuzzy edit matching | 🔴 Missing | 0/10 |
| MultiEdit | 🔴 Missing | 0/10 |
| Tool cancellation | 🔴 Missing | 0/10 |
| Tool timeouts | 🔴 Missing | 0/10 |
| Tool deduplication | 🔴 Missing | 0/10 |
| WebFetch/WebSearch | 🔴 Missing | 0/10 |
| Notebook tools | 🔴 Missing | 0/10 |
| Screenshot/Click/Type | 🔴 Missing | 0/10 |

**Critical problems:**

1. **No sibling abort** — if parallel tools run and one fails, others continue wastefully (`loop.py:620-636`). Claude Code cancels siblings on failure.
2. **No tool timeouts** — `execute_command` has a sandbox timeout but other tools (read_file on network mounts, search_content on huge repos) can hang forever.
3. **Permission system is too simple** — `PermissionManager` (`permissions.py:70-98`) only tracks write approvals by tool name, not by file path. Claude Code has path-based, pattern-based, and mode-based permissions.
4. **No `isConcurrencySafe` per-call** — CoreCode uses a static frozenset. Claude Code determines concurrency safety per individual call based on arguments.

---

## 6. Memory

### Claude Code
- 5-scope CLAUDE.md hierarchy (enterprise → user → project → local → rules).
- Auto-memory with 4 types: user, feedback, project, reference.
- DreamTask: background memory consolidation when user is idle.
- Memory taxonomy with frontmatter metadata.
- 200-line index cap. Grep-only retrieval.

### CoreCode
- `MemoryManager` (`memory.py`, 429 lines) — episodic + semantic + working memory.
- SQLite-backed via `SessionManager`.
- Importance scoring: base + recency decay + access frequency + tag bonus.
- Consolidation: Jaccard similarity grouping, merge, prune.
- `remember`/`recall` tools for LLM.
- Pruning: age-based and count-based.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Episodic memory | ✅ Fully Implemented | 7/10 |
| Semantic memory | ✅ Fully Implemented | 7/10 |
| Working memory | 🟢 Mostly Implemented | 6/10 |
| Importance scoring | ✅ Fully Implemented | 7/10 |
| Consolidation | 🟢 Mostly Implemented | 6/10 |
| Pruning | 🟢 Mostly Implemented | 6/10 |
| CLAUDE.md hierarchy | 🔴 Missing | 0/10 |
| User/feedback/reference types | 🔴 Missing | 0/10 |
| DreamTask (background consolidation) | 🔴 Missing | 0/10 |
| Semantic search | 🔴 Missing | 0/10 |

**Missing:**

1. **No CLAUDE.md / AGENTS.md hierarchy** — CoreCode reads `AGENTS.md` and `README.md` (`system_prompt.py:354-367`) but doesn't support the multi-scope hierarchy or `@path` imports.
2. **No user/feedback/reference memory types** — only episodic and semantic. Claude Code's 4-type taxonomy enables much richer personalization.
3. **Memory search is LIKE-based** (`manager.py:517-559`) — `content LIKE %query%`. No semantic search, no embeddings.
4. **No background consolidation** — consolidation only happens at session end (`loop.py:226-232`), not during idle time.

---

## 7. Sandbox & Security

### Claude Code
- **Native OS sandbox**: bubblewrap (Linux), Seatbelt (macOS). 84% fewer permission prompts.
- Dangerous pattern detection: protected files, directories, bash patterns.
- Three-tier permissions: always allow → require confirmation → never allow.
- 5 permission modes: default, acceptEdits, plan, bypassPermissions, auto.
- Circuit breaker for auto-mode. Denial tracking.
- MCP tools cannot execute shell commands (security boundary).

### CoreCode
- **Docker sandbox** (`sandbox/docker.py`) — persistent container, volume mount, resource limits.
- **Host fallback** (`sandbox/executor.py`) — routes between sandbox and direct execution.
- 4 permission levels: read/write/execute/dangerous.
- `PermissionCallback` protocol: AutoApprove, Queue, Prompt.
- No dangerous pattern detection. No protected files/directories.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Docker sandbox | 🟢 Mostly Implemented | 6/10 |
| Host fallback | ✅ Fully Implemented | 7/10 |
| Permission levels | 🟡 Partially Implemented | 5/10 |
| Dangerous pattern detection | 🔴 Missing | 0/10 |
| Protected files/dirs | 🔴 Missing | 0/10 |
| Native OS sandbox | 🔴 Missing | 0/10 |
| Permission modes | 🔴 Missing | 0/10 |
| Circuit breaker | 🔴 Missing | 0/10 |
| Denial tracking | 🔴 Missing | 0/10 |

**Critical problems:**

1. **No dangerous command detection** — `rm -rf /`, `git push --force`, `DROP TABLE` are not blocked.
2. **No protected files** — `.gitconfig`, `.bashrc`, `.ssh/` can be modified.
3. **Docker sandbox is optional** — defaults to `sandbox` mode but falls back to host. No enforcement.
4. **Permission system is binary** — once a tool is approved, it's approved for the session. No per-path, per-command granularity.

---

## 8. Git Integration

### Claude Code
- Git context injection: branch, recent 50 commits, modified/untracked files.
- Conventional commit generation from diffs.
- Branch management: feature branches, branch-per-agent.
- Conflict resolution: reads markers, explains both sides.
- Git worktree isolation for parallel agents.
- Checkpointing: every user prompt = checkpoint, 100 most recent, rewind menu.

### CoreCode
- Git tools: `git_status`, `git_diff`, `git_log`, `git_commit` (`tools/git.py`).
- Git branch detection in system prompt (`system_prompt.py:482-494`).
- No commit message generation (user must provide message).
- No branch management. No conflict resolution. No worktrees.
- No checkpointing. No rewind.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Git status/diff/log | ✅ Fully Implemented | 7/10 |
| Git commit | 🟡 Partially Implemented | 4/10 |
| Branch awareness | 🟡 Partially Implemented | 3/10 |
| Commit generation | 🔴 Missing | 0/10 |
| Conflict resolution | 🔴 Missing | 0/10 |
| Worktree isolation | 🔴 Missing | 0/10 |
| Checkpointing | 🔴 Missing | 0/10 |
| Rewind | 🔴 Missing | 0/10 |
| Session forking | 🔴 Missing | 0/10 |

---

## 9. TUI / CLI

### Claude Code
- Custom Ink fork (React renderer). Virtual scrolling. Frame scheduling.
- REPL component (~3000 lines): PromptInput, Messages, PermissionPrompt, StatusBar.
- Vim mode (motions, operators, text objects).
- Keybinding system with chord sequences. 15+ keyboard shortcuts.
- Transcript viewer (Ctrl+O). History search (Ctrl+R).
- Diff viewer with colored additions/deletions.
- Permission prompts inline with Allow/Deny.

### CoreCode
- **Typer CLI** (`main.py`) — not interactive. Runs once and exits.
- `_run_agent_clean`: box-drawing characters, tool result display, summary box.
- `_run_agent_raw`: inline log output.
- No REPL. No keyboard shortcuts. No streaming display. No diff viewer.
- Textual TUI was attempted but reverted due to black screen regression.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| CLI entry point | 🟢 Mostly Implemented | 6/10 |
| Interactive REPL | 🔴 Missing | 0/10 |
| Streaming display | 🔴 Missing | 0/10 |
| Keyboard shortcuts | 🔴 Missing | 0/10 |
| Vim mode | 🔴 Missing | 0/10 |
| Diff viewer | 🔴 Missing | 0/10 |
| Permission prompts (interactive) | 🔴 Missing | 0/10 |
| Status bar | 🔴 Missing | 0/10 |
| Transcript viewer | 🔴 Missing | 0/10 |
| Virtual scrolling | 🔴 Missing | 0/10 |
| Progress indicators | 🟡 Partially Implemented | 3/10 |

**This is the biggest gap.** CoreCode has no usable interactive interface. The current CLI runs a single prompt and exits. Claude Code's TUI is a production-grade React application with virtual scrolling, vim mode, and real-time streaming.

---

## 10. Streaming

### Claude Code
- Streaming-first architecture. Generator yields events as they arrive.
- Custom Ink renderer with frame scheduling (throttled).
- Token-by-token text rendering. Thinking deltas. Tool use blocks.
- Differential terminal writes (only redraw changed cells).

### CoreCode
- `LLMClient.stream()` yields `StreamEvent`s (TEXT, TOOL_CALL, USAGE, DONE).
- `AgentLoop.process_input()` yields `AgentEvent`s.
- CLI display: text is buffered in `stats.text_buffer` and printed at the end (`main.py:416-420`).
- No real-time token display in clean mode. Raw mode prints inline.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| LLM streaming | 🟢 Mostly Implemented | 6/10 |
| Event-based streaming | 🟢 Mostly Implemented | 6/10 |
| Real-time token display | 🔴 Missing | 0/10 |
| Tool streaming | 🔴 Missing | 0/10 |
| Thinking/reasoning display | 🔴 Missing | 0/10 |
| Differential rendering | 🔴 Missing | 0/10 |

---

## 11. Hooks System

### Claude Code
- 12+ hook events: SessionStart, Stop, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFail, SubagentStart, SubagentStop, TaskCreated, TaskCompleted, PermissionDenied, ConfigChange, CwdChanged, FileChanged, Notification.
- 5 hook types: Command, Prompt, Agent, HTTP, Function.
- 7-layer configuration: user → project → local → flag → policy → plugin → builtin.
- Dead loop guards. Exit code semantics (0=ok, 2=block).

### CoreCode
- **No hooks system.** 🔴 Missing entirely.

**This is a critical gap.** Hooks are the extensibility backbone. They let teams enforce formatting, security rules, testing, and audit logging deterministically.

---

## 12. MCP Integration

### Claude Code
- MCP client connects to external servers (stdio/sse/ws/sdk).
- Tool discovery at session start. `mcp__{server}__{tool}` naming.
- Deferred schema loading via ToolSearchTool.
- Security: MCP tools cannot execute shell commands.

### CoreCode
- **No MCP integration.** 🔴 Missing entirely.

---

## 13. Slash Commands

### Claude Code
- 25+ built-in commands: /cost, /usage, /compact, /model, /plan, /vim, /commit, /review, /rewind, /resume, /clear, /help, /doctor, /stats, /debug, /effort, /context, /tasks, /sandbox, /rename, /pr_comments.
- Custom commands via `.claude/commands/*.md` with `$ARGUMENTS` parameterization.
- Skill-scoped commands.

### CoreCode
- **No slash commands.** The CLI has `run`, `config`, `version`, `history` subcommands but no in-session slash commands.

---

## 14. Sessions & Checkpointing

### Claude Code
- Session storage: `~/.claude/projects/<project-hash>/sessions/<session-id>.json`.
- Resumable: `claude --resume` or `claude -c`.
- Checkpointing: every user prompt = checkpoint, 100 most recent.
- Rewind: restore code only, conversation only, both, or summarize.
- Session forking: independent branch of conversation.
- Auto-cleanup after 30 days.

### CoreCode
- `SessionManager` (`session/manager.py`, 690 lines) — SQLite-backed.
- Sessions, messages, operations, memories, plans CRUD.
- No session resumption (no `--resume` flag).
- No checkpointing. No rewind. No session forking.
- No auto-cleanup.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Session persistence | ✅ Fully Implemented | 7/10 |
| Message history | ✅ Fully Implemented | 7/10 |
| Session resumption | 🔴 Missing | 0/10 |
| Checkpointing | 🔴 Missing | 0/10 |
| Rewind | 🔴 Missing | 0/10 |
| Session forking | 🔴 Missing | 0/10 |
| Auto-cleanup | 🔴 Missing | 0/10 |

---

## 15. Error Recovery & Retry

### Claude Code
- API retry: exponential backoff (500ms base, doubles, cap 5min), max 10 retries.
- Error-specific budgets: 529 (3 retries), 429 (10 retries + retry-after headers).
- `prompt_too_long` recovery: overflow flush → reactive compact → circuit breaker.
- `max_output_tokens` recovery: escalate cap, feed partial back.
- Errors as input signals (not termination). Self-healing via model.
- Dead loop prevention.

### CoreCode
- `ErrorTracker` (`error_recovery.py`, 292 lines) — stuck detection, error categorization.
- Strategies: retry, alternative, replan, ask_user.
- Consecutive error tracking per tool.
- LLM client has basic retry (`llm/client.py`).

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Stuck detection | 🟢 Mostly Implemented | 6/10 |
| Error categorization | 🟢 Mostly Implemented | 6/10 |
| Recovery strategies | 🟡 Partially Implemented | 5/10 |
| API retry with backoff | 🟡 Partially Implemented | 4/10 |
| prompt_too_long recovery | 🔴 Missing | 0/10 |
| max_output_tokens recovery | 🔴 Missing | 0/10 |
| Circuit breaker | 🔴 Missing | 0/10 |
| Dead loop prevention | 🟡 Partially Implemented | 4/10 |

---

## 16. Prompt System

### Claude Code
- System prompt assembled fresh per request. Stable content first (cache-friendly).
- CLAUDE.md hierarchy injected. Auto-memory learnings.
- Tool descriptions as prompt engineering. Deferred tool schemas.
- Prompt caching breakpoints. Cache hit/miss tracking.
- 50-80% cost reduction via server-side caching.

### CoreCode
- `system_prompt.py` (521 lines) — static + dynamic sections.
- Static: identity, principles, tool rules, editing, execution, safety, communication, errors, planning, model-tier notes.
- Dynamic: environment, project context (AGENTS.md, README.md), memory, plan state, workspace index.
- `_STATIC_CACHE` for static section. `DYNAMIC_BOUNDARY` marker.
- No CLAUDE.md hierarchy. No `@path` imports. No prompt caching via API.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| System prompt construction | 🟢 Mostly Implemented | 7/10 |
| Static/dynamic split | 🟢 Mostly Implemented | 7/10 |
| Adaptive model-tier notes | 🟢 Mostly Implemented | 6/10 |
| Prompt caching (API-level) | 🔴 Missing | 0/10 |
| CLAUDE.md hierarchy | 🔴 Missing | 0/10 |
| `@path` imports | 🔴 Missing | 0/10 |
| Tool description quality | 🟡 Partially Implemented | 5/10 |

---

## 17. Model Layer

### Claude Code
- Opus, Sonnet, Haiku. Per-task model selection.
- `/model` command switches mid-session. `/fast` mode.
- Request signing (HMAC-SHA256). Rate limit handling.
- Cache hit/miss tracking. Usage tracking per turn.

### CoreCode
- 5 providers: Gemini, OpenRouter, Cerebras, ZenMux, OmniRoute.
- Key pool rotation with exhaustion/backoff (`llm/key_pool.py`).
- Separate summary model configuration.
- Token counting via tiktoken. Cost estimation.
- No mid-session model switching. No request signing.

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Multi-provider | ✅ Fully Implemented | 8/10 |
| Key pool rotation | ✅ Fully Implemented | 8/10 |
| Token counting | ✅ Fully Implemented | 7/10 |
| Cost estimation | 🟢 Mostly Implemented | 6/10 |
| Model switching | 🔴 Missing | 0/10 |
| Request signing | 🔴 Missing | 0/10 |
| Cache tracking | 🔴 Missing | 0/10 |

---

## 18. Configuration

### Claude Code
- `~/.claude/settings.json` (user), `.claude/settings.json` (project), `.claude/settings.local.json` (local).
- Environment variables. GrowthBook dynamic config. Enterprise MDM policy.
- 7-layer hook configuration. Feature flags.

### CoreCode
- `config.py` (257 lines) — Pydantic `BaseSettings` with env prefix `CODING_AGENT_`.
- `.env` file support. Single config file.
- No project-level config. No user-level config. No layered configuration.

---

## 19. Observability

### Claude Code
- Structured logging. Request signing. Usage tracking.
- `/stats` HTML report. `/debug` diagnostics. `/doctor` environment check.
- Startup profiler checkpoints.

### CoreCode
- `structlog` logging (`logging.py`). Log file output.
- Metrics dict in `AgentLoop` (`loop.py:159-171`): permission checks, tool count, summarization stats, context suggestions, cache hits.
- `get_metrics_summary()` for session summary.
- No HTML reports. No debug mode. No profiling. No tracing.

---

## 20. Self-Correction & Reflection

### Claude Code
- Errors as input signals (core pattern). Model self-corrects after seeing errors.
- System prompt instructs: verify result, check assumptions, decide next action.
- Compaction recovery: model receives "context was compacted" signal.
- PostToolUse hooks re-inject intent after failures.

### CoreCode
- `Reflector` (`reflector.py`, 305 lines) — rule-based heuristics.
- `Assessment` enum: success, partial, failure, unexpected.
- `assess_outcome()` with optional LLM-based comparison.
- Consecutive failure tracking per tool.
- Verification failures fed back as user messages (`loop.py:1144-1146`).

### Assessment
| Aspect | Status | Score |
|--------|--------|-------|
| Rule-based reflection | 🟢 Mostly Implemented | 6/10 |
| LLM-based outcome assessment | 🟡 Partially Implemented | 5/10 |
| Error-as-input pattern | 🟡 Partially Implemented | 5/10 |
| Intent re-injection after failures | 🔴 Missing | 0/10 |
| Compaction recovery | 🔴 Missing | 0/10 |

---

## 21. Subagents / Parallel Execution

### Claude Code
- AgentTool: spawn child agents with isolated context, filtered tools.
- Depth limit: 1 (prevents recursion).
- Coordinator mode, Team mode (v2.1.32+).
- Fork sub-agent for prompt cache optimization.
- Inter-agent communication: in-process queue, file-based mailbox, broadcast.

### CoreCode
- **No subagent system.** 🔴 Missing entirely.

---

## 22. Search & File Operations

### Claude Code
- Grep (ripgrep): ~20ms, regex search. Primary search tool.
- Glob: file pattern matching.
- Read: max 2000 lines. File state cache (LRU, 100 files, 25MB).
- Edit: exact match + fuzzy fallback. MultiEdit.
- Write: create/overwrite. Must read first if exists.
- "Search, Don't Index" philosophy.

### CoreCode
- `search_content` (ripgrep via subprocess), `search_files` (glob via pathlib).
- `read_file` with line limits and offset/limit params.
- `write_file`, `edit_file` (exact text match).
- `list_files` with .gitignore filtering.
- No file state cache. No fuzzy edit matching. No MultiEdit.

---

## 23. Undo / Checkpoints

### Claude Code
- Checkpointing: every user prompt = snapshot. 100 most recent.
- Rewind: restore code, conversation, both, or summarize.
- Session forking.

### CoreCode
- `UndoStack` (`agent/undo.py`) — 50-entry in-memory stack.
- `undo` tool for LLM.
- File mutation snapshots.
- No checkpointing. No rewind. No session forking. Undo is lost on restart.

---

## Final Scorecard

| Category | Claude Code | CoreCode | Completion % | Quality /10 | Priority |
|----------|------------|----------|-------------|------------|----------|
| Architecture | 10 | 7 | 70% | 7 | High |
| Agent Loop | 10 | 7 | 70% | 7 | High |
| Context Engine | 10 | 4 | 40% | 4 | Critical |
| Planning | 10 | 6 | 60% | 6 | Medium |
| Tool System | 10 | 6 | 60% | 6 | High |
| Memory | 10 | 6 | 60% | 6 | Medium |
| Sandbox & Security | 10 | 3 | 30% | 3 | Critical |
| Git Integration | 10 | 3 | 30% | 3 | High |
| TUI / CLI | 10 | 1 | 10% | 1 | Critical |
| Streaming | 10 | 3 | 30% | 3 | Critical |
| Hooks System | 10 | 0 | 0% | 0 | High |
| MCP Integration | 10 | 0 | 0% | 0 | Medium |
| Slash Commands | 10 | 0 | 0% | 0 | Medium |
| Sessions & Checkpoints | 10 | 4 | 40% | 4 | Critical |
| Error Recovery | 10 | 5 | 50% | 5 | High |
| Prompt System | 10 | 6 | 60% | 6 | Medium |
| Model Layer | 10 | 7 | 70% | 7 | Low |
| Configuration | 10 | 4 | 40% | 4 | Medium |
| Observability | 10 | 3 | 30% | 3 | Medium |
| Self-Correction | 10 | 5 | 50% | 5 | Medium |
| Subagents | 10 | 0 | 0% | 0 | High |
| Search & Files | 10 | 6 | 60% | 6 | Medium |
| Undo / Checkpoints | 10 | 2 | 20% | 2 | Critical |

### Overall Maturity: **Alpha** (estimated 35-40% feature parity)

---

## Missing Feature Matrix

| Feature | Importance | Difficulty | Est. Time | Dependencies | Roadmap |
|---------|-----------|-----------|----------|-------------|---------|
| Interactive REPL | Critical | Large | 3-5 days | Textual TUI | Phase A |
| Streaming display | Critical | Medium | 1-2 days | REPL | Phase A |
| Checkpointing & rewind | Critical | Large | 3-5 days | REPL, session mgmt | Phase A |
| Dangerous command detection | Critical | Small | 3-5 hrs | None | Phase A |
| Protected files/dirs | Critical | Small | 2-3 hrs | None | Phase A |
| prompt_too_long recovery | Critical | Medium | 1 day | Context engine | Phase A |
| max_output_tokens recovery | Critical | Small | 3-5 hrs | None | Phase A |
| Micro-compact (old tool results) | Critical | Medium | 1 day | Context engine | Phase B |
| Sibling abort (parallel tools) | High | Small | 3-5 hrs | None | Phase B |
| Tool timeouts | High | Small | 2-3 hrs | None | Phase B |
| Fuzzy edit matching | High | Medium | 1 day | Edit tool | Phase B |
| Hooks system | High | Large | 3-5 days | None | Phase B |
| Subagent delegation | High | Large | 3-7 days | Agent loop | Phase C |
| Session resumption (--resume) | High | Medium | 1 day | Session manager | Phase C |
| CLAUDE.md hierarchy | High | Medium | 1-2 days | System prompt | Phase C |
| Slash commands | High | Medium | 2-3 days | REPL | Phase C |
| MCP integration | Medium | Large | 5-7 days | Tool system | Phase D |
| Model switching (/model) | Medium | Small | 3-5 hrs | LLM client | Phase D |
| Permission modes | Medium | Medium | 1-2 days | Permission system | Phase D |
| Prompt caching (API) | Medium | Medium | 1 day | System prompt | Phase D |
| Session forking | Medium | Medium | 1-2 days | Session manager | Phase E |
| Plan mode (read-only) | Medium | Medium | 1 day | Agent loop | Phase E |
| Semantic memory search | Medium | Large | 3-5 days | Memory, embeddings | Phase E |
| Vim mode | Low | Large | 3-5 days | REPL | Phase F |
| DreamTask (background consolidation) | Low | Medium | 1-2 days | Memory | Phase F |
| HTML stats report | Low | Small | 3-5 hrs | Metrics | Phase F |
| Request signing | Low | Small | 2-3 hrs | None | Phase F |

---

## Phased Roadmap

### Phase A — Critical Fixes (1-2 weeks)
1. **Dangerous command detection** — block `rm -rf`, `git push --force`, `DROP TABLE` in `shell.py`
2. **Protected files/dirs** — add path checks in `file_ops.py`
3. **`max_output_tokens` recovery** — feed partial response back in `loop.py`
4. **`prompt_too_long` recovery** — add reactive compact path
5. **Interactive REPL** — build Textual-based REPL with streaming display
6. **Checkpointing** — snapshot file state before each edit, 100-entry ring buffer
7. **Rewind** — `/rewind` command to restore checkpoints

### Phase B — Foundation (2-3 weeks)
1. **Micro-compact** — clear old tool results from context at 70% threshold
2. **Sibling abort** — cancel parallel tools on failure via `asyncio.Task.cancel()`
3. **Tool timeouts** — add `asyncio.wait_for()` with configurable timeout per tool
4. **Fuzzy edit matching** — add difflib-based fallback in `edit_file`
5. **Hooks system** — pre/post tool execution hooks (command + prompt types)
6. **Streaming display** — real-time token rendering in TUI
7. **Permission modes** — default, acceptEdits, plan, bypassPermissions

### Phase C — Intelligence (2-3 weeks)
1. **Subagent delegation** — spawn child agents for bounded subtasks
2. **Session resumption** — `--resume` flag, load from SQLite
3. **CLAUDE.md hierarchy** — multi-scope project config with `@path` imports
4. **Slash commands** — `/compact`, `/cost`, `/model`, `/clear`, `/help`, `/plan`
5. **Context window sliding** — drop oldest message groups when approaching limits
6. **Intent re-injection** — PostToolUse hook re-injects task summary on failures

### Phase D — UX (2-3 weeks)
1. **MCP integration** — connect to external tool servers
2. **Model switching** — `/model` command for mid-session model changes
3. **Prompt caching** — structure system prompt for API-level cache hits
4. **Diff viewer** — colored additions/deletions in TUI
5. **Status bar** — model, tokens, cost, context usage, iteration count
6. **Progress indicators** — spinners/progress bars for long operations

### Phase E — Advanced (3-4 weeks)
1. **Plan mode** — read-only planning before execution
2. **Semantic memory search** — embeddings-based memory retrieval
3. **Session forking** — independent conversation branches
4. **Team mode** — multi-agent collaboration with shared scratchpad
5. **Circuit breaker** — for compaction, auto-mode, error recovery

### Phase F — Claude Code Parity (4-6 weeks)
1. **Vim mode** — motions, operators, text objects
2. **DreamTask** — background memory consolidation during idle
3. **HTML stats report** — `/stats` command
4. **Git worktree isolation** — parallel agents in separate worktrees
5. **Conflict resolution** — read markers, explain both sides
6. **Transcript viewer** — Ctrl+O toggle with search

### Phase G — Beyond Claude Code (6-8 weeks)
1. **Autonomous background tasks** — run tasks while user works on other things
2. **Predictive context prefetching** — pre-load likely-needed files
3. **Knowledge graph integration** — codebase structure as graph
4. **Adaptive planning** — ML-based plan quality scoring
5. **Rich observability dashboards** — flame graphs, token flow visualization
6. **Workflow automation** — reusable task templates
7. **Multi-model orchestration** — route subtasks to optimal models automatically

---

## Architectural Risks

1. **`AgentLoop` god object** (`loop.py:64-1315`) — 1300+ lines, 15+ initialized subsystems. Hard to test, hard to extend. Should be decomposed into focused services with a DI container.

2. **Module-level `set_*` calls** (`loop.py:124-143`) — `set_memory_manager()`, `set_undo_stack()`, `set_plan_manager()`, `set_workspace_index()` are global state mutations. This is a service locator anti-pattern that creates hidden dependencies and makes testing fragile.

3. **Duplicated `_run_agent_clean` / `_run_agent_raw`** (`main.py:136-611`) — 475 lines of near-identical code. Should be a single function with a display strategy.

4. **No interactive REPL** — the entire project is unusable as a daily tool without this. Every other feature depends on having a conversation loop.

5. **`replace_plan` return type bug** (`planner.py:138-148`) — declares `-> None` but has `return self._plan`. This will cause a runtime error or silent type mismatch.

6. **SQLite assertions** (`manager.py` throughout) — `assert self._db is not None` on every method. Should use proper null checks or guarantee initialization.

7. **No test coverage for integration paths** — tests exist for individual components but no end-to-end test that runs the full agent loop with a mock LLM.

---

## Top 20 Highest-Impact Improvements (ROI-ranked)

| Rank | Feature | Impact | Effort | ROI |
|------|---------|--------|--------|-----|
| 1 | Interactive REPL | Critical | Medium | ⭐⭐⭐⭐⭐ |
| 2 | Streaming display | Critical | Small | ⭐⭐⭐⭐⭐ |
| 3 | Dangerous command detection | Critical | Small | ⭐⭐⭐⭐⭐ |
| 4 | `max_output_tokens` recovery | Critical | Small | ⭐⭐⭐⭐⭐ |
| 5 | Protected files/dirs | Critical | Small | ⭐⭐⭐⭐⭐ |
| 6 | Checkpointing & rewind | Critical | Medium | ⭐⭐⭐⭐ |
| 7 | `prompt_too_long` recovery | Critical | Medium | ⭐⭐⭐⭐ |
| 8 | Sibling abort | High | Small | ⭐⭐⭐⭐ |
| 9 | Tool timeouts | High | Small | ⭐⭐⭐⭐ |
| 10 | Session resumption | High | Medium | ⭐⭐⭐⭐ |
| 11 | Fuzzy edit matching | High | Medium | ⭐⭐⭐ |
| 12 | Micro-compact | High | Medium | ⭐⭐⭐ |
| 13 | Hooks system | High | Large | ⭐⭐⭐ |
| 14 | Slash commands | High | Medium | ⭐⭐⭐ |
| 15 | CLAUDE.md hierarchy | High | Medium | ⭐⭐⭐ |
| 16 | Subagent delegation | High | Large | ⭐⭐⭐ |
| 17 | Permission modes | Medium | Medium | ⭐⭐ |
| 18 | Model switching | Medium | Small | ⭐⭐ |
| 19 | Diff viewer | Medium | Medium | ⭐⭐ |
| 20 | MCP integration | Medium | Large | ⭐⭐ |

---

## Stretch Goals (Beyond Claude Code)

1. **Semantic project memory with embeddings** — Use local embeddings (e.g., `sentence-transformers`) for code-aware memory retrieval, not just keyword matching.

2. **Predictive context prefetching** — Analyze the current task and pre-load files the agent is likely to need next, reducing latency.

3. **Knowledge graph of codebase** — Build and maintain a graph of file→function→class relationships for faster navigation.

4. **Multi-model orchestration** — Automatically route subtasks to the optimal model (Haiku for simple reads, Opus for complex architecture decisions) without user intervention.

5. **Autonomous background tasks** — Queue tasks that run while the user works on other things, with notification on completion.

6. **Rich observability dashboards** — Token flow visualization, cost breakdowns, latency histograms, context utilization graphs.

7. **Workflow automation** — Save and replay common task sequences (e.g., "create feature → write tests → lint → commit").

8. **Codebase-aware test generation** — Analyze existing test patterns and generate tests that match the project's testing conventions.
