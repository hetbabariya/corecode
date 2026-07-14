# CoreCode Architecture Audit

## Executive Summary

You have built a **solid portfolio project** — clean code, good test discipline, well-structured modules. But you are **nowhere near** production-grade coding-agent territory. The gap between what you have and what Claude Code/Cursor/Gemini CLI ship is not incremental — it is **structural**. You have a well-built bicycle; they have jet engines. The core loop is correct in shape but missing every subsystem that makes a coding agent actually useful on real codebases.

**Architecture Score: 3.5/10**

---

## 1. Agent Loop (`agent/loop.py`)

### Current Design
- Simple `for iteration in range(max_iterations)` loop
- Streams LLM response → accumulates tool calls → executes sequentially → feeds results back → repeats
- Stops when LLM returns no tool calls or max iterations hit
- Summarization check at end of each iteration

### Architectural Problems

**The loop is a naive ReAct implementation with zero sophistication.**

1. **No parallel tool execution.** You accumulate all tool calls from one LLM turn, then execute them sequentially in a `for tc in tool_calls` loop. Claude Code executes parallel tool calls concurrently. When the LLM asks to read 5 files simultaneously, you read them one by one, wasting 5x the wall-clock time.

2. **No streaming tool call execution.** You wait for the **entire stream to finish** before executing any tool call. Claude Code starts executing tool calls as soon as they're parsed from the stream. This means your TUI shows nothing happening during tool execution setup.

3. **No stop condition sophistication.** Your only stop conditions are "no tool calls" and "max iterations." Claude Code uses: task completion detection, user satisfaction signals, code change verification, test pass/fail, explicit "I'm done" detection. You have none of this.

4. **No error recovery loop.** When a tool fails, you feed the error back to the LLM and hope it figures out what to do. There's no structured retry strategy, no "try 3 different approaches then ask the user," no rollback capability.

5. **No tool result truncation.** A `read_file` on a 10,000-line file dumps the entire thing into context. There's no smart truncation, no "read only what matters," no result size limits. This will blow your context window.

6. **No self-correction.** The loop has no mechanism to detect when it's going in circles (same tool calls failing repeatedly), no mechanism to detect when it's stuck, no "backtrack and try a different approach."

### Missing Capabilities vs. Competitors

| Capability | CoreCode | Claude Code | Gemini CLI |
|---|---|---|---|
| Parallel tool execution | No | Yes | Yes |
| Streaming tool execution | No | Yes | Yes |
| Smart stop conditions | No | Yes | Yes |
| Error recovery strategies | No | Yes | Yes |
| Self-correction loops | No | Yes | Partial |
| Task completion detection | No | Yes | Yes |
| Rollback/checkpoint | No | Yes | No |
| Multi-turn verification | No | Yes | Partial |

### Maturity: **Beginner**

---

## 2. Context Management (`agent/context.py`)

### Current Design
- Linear message list: system → summary → messages
- Token estimation via `chars // 4` heuristic
- Summarization at 80% capacity: keep last 5 messages, summarize rest
- Single summary string

### Architectural Problems

1. **`chars // 4` is dangerously inaccurate.** For code, this can be off by 2-3x (JSON tool calls, multi-byte Unicode, code with lots of short identifiers). Claude Code uses tiktoken for exact counts. You'll either overflow the context window or waste 50% of it.

2. **Keeping exactly 5 messages is arbitrary and destructive.** If the last 5 messages are all tool results (which is common — read file → read file → read file → edit → test), the LLM sees almost no useful context. Claude Code uses smart windowing: keep the system prompt, the user's original request, and the most relevant messages based on recency and importance.

3. **No tool result truncation.** A single `read_file` of a large file can consume 50k+ tokens. There's no max size on tool results, no smart truncation, no "summarize this result before storing it."

4. **No structured context engineering.** The system prompt is static + AGENTS.md + README. Claude Code builds context dynamically: it reads relevant code sections, injects file tree summaries, includes error context, adds project structure hints. Your context is essentially "here's the system prompt, here's the conversation, good luck."

5. **No file tree awareness.** The agent doesn't maintain an internal representation of the workspace structure. It has to discover everything through tools. Claude Code maintains a workspace index.

6. **No symbol graph.** No awareness of functions, classes, imports, dependencies. The agent can't answer "what calls this function?" without searching every file.

### Maturity: **Beginner**

---

## 3. Tool System (`tools/`)

### Current Design
- 11 tools: file ops (4), search (2), shell (1), git (4)
- `@tool` decorator auto-registers tools
- Schema inference from type hints
- OpenAI function-calling format for LLM consumption
- `ToolResult(success, output, error, metadata)` return type

### Strengths
- Clean decorator-based registration
- Schema inference is a nice touch
- ToolResult is well-designed with metadata

### Architectural Problems

1. **Missing critical tools.** Compare to Claude Code's tool set:
   - **No `search_symbols`** — no way to find definitions, references, or usages by symbol name
   - **No `read_file_range`** — `read_file` has offset/limit but no smart range selection
   - **No `apply_patch`** — only exact string replacement, no diff-based patching
   - **No `task_complete`** tool — the LLM can't explicitly signal it's done
   - **No `ask_user`** tool — the LLM can't ask clarifying questions mid-task
   - **No `browser_preview`** or similar — no way to check visual output
   - **No `mcp_tool`** integration — no extensibility
   - **No tree-sitter integration** — despite listing it as a dependency, it's unused

2. **`edit_file` is fragile.** Exact string replacement breaks on:
   - Multi-line edits with variable whitespace
   - Files with inconsistent line endings
   - Binary-adjacent files
   - Claude Code uses AST-aware editing and multi-needle edit formats

3. **No tool result size limits.** `read_file` returns the entire file. `search_content` returns up to 50 matches with full lines. `execute_command` returns all stdout/stderr. These can easily be 100k+ tokens each, destroying your context budget.

4. **Shell execution timeout is per-command, not per-session.** An LLM could loop calling `execute_command` with short commands, each under 30s, but collectively consuming infinite time.

5. **No tool composition.** No way to chain tools, no "read this file and if it contains X, edit it" — each tool call is atomic.

### Maturity: **Intermediate**

---

## 4. LLM Client (`llm/`)

### Current Design
- Google GenAI SDK + OpenRouter (via httpx)
- Key pool rotation on 429/404 errors
- Exponential backoff
- Streaming support
- OpenAI-format normalization

### Strengths
- Key pool rotation is a genuinely production-quality feature
- Clean provider abstraction
- Streaming parser handles partial JSON well

### Architectural Problems

1. **No Anthropic SDK support.** Despite the docs mentioning Claude, you dropped LiteLLM and only support Gemini + OpenRouter. This means no native Anthropic tool use, no Claude-specific features (extended thinking, prompt caching), no direct Anthropic API access.

2. **No prompt caching.** You have a `DYNAMIC_BOUNDARY` marker for future caching but don't implement it. Claude Code caches the system prompt and tool schemas, saving significant cost and latency on repeated calls. With Gemini's context caching, this is free performance you're leaving on the table.

3. **No streaming tool call incremental parsing during execution.** Your `StreamParser` accumulates tool calls but only emits them at stream end. You should emit tool calls as soon as they're complete (name + args fully parsed) so the loop can start executing them.

4. **Gemini system message handling is broken.** In `_convert_messages`, you `continue` (skip) system messages entirely for Gemini. This means the system prompt is never sent to Gemini. This is a **critical bug** — the agent has no instructions on Gemini models.

5. **No model fallback.** If Gemini is down, there's no automatic fallback to OpenRouter or another provider. Claude Code has provider fallback chains.

### Maturity: **Intermediate** (would be Advanced if Gemini system prompt bug didn't exist)

---

## 5. Sandbox (`sandbox/`)

### Current Design
- Persistent Docker container with `docker exec`
- Workspace volume mount
- Resource limits (memory, CPU)
- Host fallback when Docker unavailable
- Start/stop lifecycle

### Strengths
- Persistent container is the right architecture choice
- Host fallback is practical
- Clean async wrapper around Docker SDK

### Architectural Problems

1. **No network isolation.** The sandbox container has full network access. A malicious or accidental `curl` could exfiltrate data, download malware, or hit external APIs. Production sandboxes (Claude Code) have network restrictions.

2. **No filesystem restrictions.** The container mounts the entire workspace read-write. The agent can delete `.git`, overwrite config files, or corrupt the project. Should have read-only mounts for sensitive paths.

3. **No command allowlist/blocklist.** The sandbox runs any command. No filtering for `rm -rf /`, `sudo`, `curl | bash`, etc.

4. **Container health check is manual.** `_exec_with_timeout` doesn't actually implement timeout — it relies on `docker exec` blocking indefinitely (it doesn't respect a timeout parameter). A `sleep 999999` command would hang forever.

5. **No container image management.** No auto-build, no version pinning, no image update detection. The user must manually build the Docker image.

6. **No snapshot/restore.** No way to snapshot the workspace state before a risky operation and restore it afterward.

### Maturity: **Intermediate**

---

## 6. Memory System

### Current Design
- `memory_content` parameter in system prompt (always empty)
- `_memory_section()` function exists but is never called with content
- No persistence across sessions

### What's Missing
**You have no memory system.** This is arguably the biggest competitive gap.

- Claude Code remembers project conventions across sessions
- Cursor maintains file change history and learns from corrections
- Aider has repository map persistence
- Your agent starts completely fresh every time, with zero learning

What you need:
- **Episodic memory**: what was done in past sessions (file changes, decisions)
- **Semantic memory**: project conventions, patterns, preferences
- **Working memory**: current task state, subtask progress
- **Procedural memory**: "this project uses pytest, not unittest" — learned facts

### Maturity: **Non-existent**

---

## 7. Planning System

### Current Design
- The system prompt tells the LLM to "Plan multi-step tasks"
- No planning infrastructure exists
- No task decomposition
- No progress tracking
- No plan storage

### What's Missing
**You have no planning system.** The LLM is supposed to plan in its head, which is unreliable and expensive.

- Claude Code has structured planning with explicit task breakdown
- Cursor Agent has plan mode where it reads everything before acting
- Gemini CLI has planning with user confirmation

What you need:
- **Plan generator**: explicit step-by-step plan before execution
- **Plan validator**: check if each step is feasible
- **Progress tracker**: track which steps are done
- **Plan replanner**: when a step fails, regenerate the plan
- **Plan persistence**: save plans to resume later

### Maturity: **Non-existent**

---

## 8. Verification System

### Current Design
- System prompt says "Verify your work"
- No verification infrastructure
- No test running after changes
- No syntax checking after edits
- No diff review

### What's Missing
**You have no verification system.** The agent makes changes and hopes they work.

- Claude Code runs tests after changes and verifies they pass
- It checks syntax validity of edited files
- It compares expected vs actual behavior
- It can revert changes that break things

What you need:
- **Post-edit verification**: run linter/type checker after every edit
- **Test execution**: run relevant tests after code changes
- **Diff review**: compare before/after to ensure changes are minimal
- **Rollback on failure**: if verification fails, undo the change
- **Regression detection**: detect if changes broke existing functionality

### Maturity: **Non-existent**

---

## 9. Session Management (`session/`)

### Current Design
- SQLite schema defined in architecture docs
- `session/__init__.py` exists but is empty
- No actual implementation

### What's Missing
**You have no session management.** The `session/` package is a placeholder.

- No session persistence
- No history viewing
- No session resume
- No operation undo
- No cost tracking per session
- No session export

### Maturity: **Non-existent**

---

## 10. TUI (`tui/`)

### Current Design
- Textual app with grid layout
- Chat display, sidebar, permission dialog, input
- Streaming text updates via StreamHandler
- Keyboard shortcuts

### Strengths
- Clean widget decomposition
- Permission dialog with queue-based callback
- Sidebar shows useful stats

### Architectural Problems

1. **Streaming performance.** `update_last_assistant` removes and re-mounts a widget on every token. This is O(n) DOM operations per stream. Should use in-place text update.

2. **No diff viewer.** File edits show as text. No syntax-highlighted diff, no side-by-side view. Claude Code has a rich diff viewer.

3. **No progress indicators.** When the agent is working on a long task, there's no visual indicator of progress (which step, how many remaining).

4. **No keyboard-driven workflow.** Power users can't navigate with keyboard, approve permissions with 'y', etc.

5. **No session management UI.** No way to view past sessions, resume them, or compare them.

### Maturity: **Intermediate**

---

## 11. System Prompt (`agent/system_prompt.py`)

### Current Design
- 8 static sections + 3 dynamic sections
- Static: identity, principles, tools, editing, task execution, safety, communication, errors
- Dynamic: environment, project context (AGENTS.md/README), memory

### Strengths
- Well-structured with cacheable/non-cacheable separation
- AGENTS.md support
- Comprehensive behavioral instructions

### Architectural Problems

1. **Static prompt is ~2000 tokens.** This is reasonable but could be shorter. Claude Code's prompt is heavily optimized per-model.

2. **No adaptive prompting.** The same prompt is used regardless of task complexity. Simple tasks don't need all 8 sections. Complex tasks need more guidance.

3. **No workspace-specific instructions.** Beyond AGENTS.md, there's no way to inject project-specific context (language conventions, framework patterns, existing code patterns).

4. **No few-shot examples.** The prompt tells the LLM what to do but doesn't show examples. For complex tool use patterns, examples dramatically improve reliability.

5. **No model-specific tuning.** Gemini and Claude respond differently to prompts. The same prompt is sent to both.

### Maturity: **Intermediate**

---

## 12. Testing

### Current Design
- 286+ tests across tools, LLM, agent, TUI
- Mock-based unit tests
- Live integration tests (manual execution)
- Pytest-asyncio

### Strengths
- Good test count for the scope
- Live tests are valuable
- Test patterns are consistent

### Architectural Problems

1. **No end-to-end tests.** No test that exercises the full flow: user input → LLM → tools → result → LLM → done.

2. **No fuzz testing.** No testing with malformed tool calls, partial JSON, edge cases.

3. **No performance tests.** No benchmarks for context building, tool execution, or streaming.

4. **No regression tests.** No tests that verify specific LLM responses against known-good behavior.

### Maturity: **Intermediate**

---

## 13. Industry Comparison

### vs. Claude Code

| Aspect | CoreCode | Claude Code |
|---|---|---|
| Agent loop | Naive ReAct | Sophisticated with state machine |
| Context | Linear + summarization | Dynamic, with file indexing |
| Tools | 11 basic | 20+ with AST-aware editing |
| Planning | None | Explicit plan → execute → verify |
| Memory | None | Cross-session persistence |
| Verification | None | Post-change test/lint |
| Parallel execution | None | Concurrent tool calls |
| Error recovery | Feed error to LLM | Structured retry + rollback |
| Cost optimization | None | Prompt caching, model routing |

Claude Code is years ahead architecturally. You have the primitives; they have the system.

### vs. Cursor Agent

| Aspect | CoreCode | Cursor |
|---|---|---|
| Workspace understanding | None | Full index + symbol graph |
| Edit quality | String replace | AST-aware multi-edit |
| Context selection | Full file dump | Smart chunking |
| Multi-file editing | Sequential | Parallel with coordination |
| User experience | Terminal | IDE integration |

### vs. Gemini CLI

| Aspect | CoreCode | Gemini CLI |
|---|---|---|
| Provider | Gemini (broken) + OpenRouter | Native Gemini |
| Context window | 100k (estimated) | 1M+ native |
| Tool system | Custom | MCP protocol |
| Extensibility | None | Plugin system |
| Sandbox | Docker | gVisor / native |

### vs. OpenCode

| Aspect | CoreCode | OpenCode |
|---|---|---|
| Architecture | Monolithic agent loop | Modular with subagents |
| TUI | Textual (basic) | Rich TUI with panels |
| Tool ecosystem | 11 tools | MCP + custom tools |
| Session management | None | Full persistence |

---

## 14. Agent Loop Deep Dive

### State Transitions

```
IDLE → (user input) → THINKING → (LLM stream) → TOOL_CALLING → (execute) → THINKING
                        ↓                                    ↓
                    DONE ← (no tool calls)            TOOL_RESULT → THINKING
```

**Problems:**
- No `ERROR_RECOVERY` state
- No `PLANNING` state
- No `VERIFYING` state
- No `WAITING_FOR_USER` state (beyond permission)
- No `PAUSED` state

### Tool Execution Strategy

Sequential. Always. No parallelism. No prioritization. No batching.

### Context Flow

Linear append-only. No pruning of irrelevant context. No priority weighting.

### Decision Making

Zero. The LLM decides everything. No heuristic shortcuts, no caching of decisions, no rule-based overrides.

### Iteration Control

`for i in range(max_iterations)`. No adaptive limits. No time-based limits. No cost-based limits.

### Failure Recovery

Feed error message to LLM. That's it. No structured retry, no strategy switching, no escalation.

### Stopping Conditions

1. LLM returns no tool calls
2. Max iterations reached

Missing:
- Task completion detected
- User satisfaction
- Time budget exhausted
- Cost budget exhausted
- No progress being made (stuck detection)
- All approaches exhausted

---

## 15. Future Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PRODUCTION ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │   TUI Layer  │  │   CLI Layer  │  │  API Layer   │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         └─────────────────┼─────────────────┘                       │
│                           │                                         │
│              ┌────────────▼────────────┐                            │
│              │      Orchestrator       │                            │
│              │  (State Machine +       │                            │
│              │   Event Bus)            │                            │
│              └────────────┬────────────┘                            │
│                           │                                         │
│    ┌──────────────────────┼──────────────────────┐                  │
│    │                      │                      │                  │
│  ┌─▼────────┐  ┌──────────▼──────┐  ┌──────────▼──────┐          │
│  │ Planner  │  │  Agent Runner   │  │   Verifier      │          │
│  │          │  │  (subagent)     │  │   (post-change) │          │
│  └──────────┘  └────────┬────────┘  └─────────────────┘          │
│                          │                                         │
│         ┌────────────────┼────────────────┐                       │
│         │                │                │                       │
│    ┌────▼────┐    ┌──────▼──────┐   ┌────▼──────┐               │
│    │ LLM     │    │ Tool System │   │ Context   │               │
│    │ Client  │    │ (parallel)  │   │ Engine    │               │
│    └─────────┘    └──────┬──────┘   └───────────┘               │
│                           │                                        │
│         ┌─────────────────┼─────────────────┐                     │
│         │                 │                 │                     │
│    ┌────▼────┐    ┌───────▼──────┐   ┌─────▼──────┐            │
│    │ Memory  │    │  Workspace   │   │ Sandbox    │            │
│    │ System  │    │  Index       │   │ (gVisor)   │            │
│    └─────────┘    └──────────────┘   └────────────┘            │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   Support Services                        │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │   │
│  │  │ Session  │  │ Permission│  │  Cost    │  │ Event  │  │   │
│  │  │ Manager  │  │ System   │  │ Tracker  │  │ Logger │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **State machine orchestration** — explicit states, not implicit loop
2. **Parallel tool execution** — asyncio.gather for independent tools
3. **Context engineering** — smart truncation, priority weighting, file indexing
4. **Verification loop** — every change is verified before proceeding
5. **Memory persistence** — cross-session learning
6. **Cost consciousness** — prompt caching, model routing, budget limits

---

## 16. Prioritized Roadmap

### Phase 1: Fix Critical Bugs & Foundation (1-2 weeks)

| What | Why | Complexity | Impact |
|---|---|---|---|
| Fix Gemini system prompt bug | Agent is broken on primary provider | Low | Critical |
| Implement parallel tool execution | 5x speed improvement on multi-file tasks | Medium | High |
| Add tool result truncation | Prevent context window overflow | Low | High |
| Implement token counting with tiktoken | Prevent context overflow/waste | Low | High |
| Add streaming tool call emission | Faster perceived response | Medium | Medium |

### Phase 2: Core Intelligence (3-4 weeks)

| What | Why | Complexity | Impact |
|---|---|---|---|
| Planning system | Structured task decomposition | High | Critical |
| Task queue
| Verification system (post-edit lint/test) | Prevent broken code | High | Critical |
| Workspace indexing (file tree + symbols) | Enable intelligent navigation | High | High |
| Smart context selection (don't dump entire files) | Preserve context budget | High | High |
| Error recovery strategies | Handle failures gracefully | Medium | High |
| Stuck detection + backtracking | Prevent infinite loops | Medium | Medium |

### Phase 3: Memory & Persistence (2-3 weeks)

| What | Why | Complexity | Impact |
|---|---|---|---|
| Session persistence (SQLite) | Resume conversations | Medium | High |
| Cross-session memory | Learn project conventions | High | High |
| Undo/redo system | Safe experimentation | Medium | High |
| Operation history with snapshots | Rollback capability | Medium | Medium |
| Cost tracking per session | Budget awareness | Low | Medium |

### Phase 4: Production Hardening (3-4 weeks)

| What | Why | Complexity | Impact |
|---|---|---|---|
| Prompt caching (Gemini/Anthropic) | 50-80% cost reduction | Medium | High |
| Anthropic SDK support | Direct Claude access | Medium | High |
| MCP tool integration | Extensibility | High | High |
| Sub-agent orchestration | Parallel task execution | High | Medium |
| Network-isolated sandbox | Security | Medium | Medium |
| Adaptive system prompt | Model-specific optimization | Medium | Medium |

---

## 17. Architecture Scores

| Dimension | Score | Notes |
|---|---|---|
| **Agent Loop** | 3/10 | Correct shape, missing every sophistication |
| **Context Management** | 2/10 | Basic, no smart selection, inaccurate counting |
| **Tool System** | 5/10 | Clean design, missing critical tools |
| **Memory** | 0/10 | Does not exist |
| **Planning** | 0/10 | Does not exist |
| **Reliability** | 3/10 | No error recovery, no verification, no rollback |
| **Scalability** | 2/10 | Sequential execution, no caching, no budget limits |
| **Developer Experience** | 4/10 | Clean code, good tests, but no session resume, no undo |
| **Production Readiness** | 2/10 | No persistence, no monitoring, no safety rails |

**Overall Architecture Score: 3.5/10**

---

## Bottom Line

You've built the **plumbing** correctly. The tool registry, LLM client, streaming parser, and basic agent loop are well-engineered. But plumbing isn't a product. The things that make Claude Code useful — planning, verification, memory, workspace understanding, context engineering — are entirely absent.

Your Phase 1-6 work is solid. Your Phase 7-8 work (agent loop, TUI) is functional but naive. Everything after that — the intelligence layer — doesn't exist yet.

The good news: your foundation is clean enough to build on. The bad news: you need to build 10x more than what exists.
