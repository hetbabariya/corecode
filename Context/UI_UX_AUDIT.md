# CoreCode UI/UX Audit — Pre-Ship Review

**Date:** 2026-07-14
**Reviewer:** Staff Product Designer / Senior UX Engineer
**Scope:** Full UI/UX audit of CoreCode TUI (v0.1.0)

---

## 1. Overall First Impression

**Score: 2/10**

This does not look like a premium developer tool. It looks like a terminal chatbot demo from 2019.

Problems:
- The title "Coding Agent - AI-powered coding assistant" is generic and forgettable. Every AI tool says this.
- The welcome message ("Type your message and press Enter to submit") is instructions for someone who has never used a computer.
- The sidebar is plain text dumped into a column. No visual hierarchy, no structure.
- There is zero branding. No logo, no wordmark, no identity. It could be any of a thousand TUI projects.
- The workspace path wraps across 4 lines in the sidebar, which looks broken on arrival.
- The color palette (dark background + cyan + orange) reads as "default terminal theme," not "premium tool."
- Developers seeing this for the first time will not trust it with their codebase.

---

## 2. Visual Hierarchy

**Score: 2/10**

There is essentially no visual hierarchy. Everything is the same visual weight.

### Typography
- All text is the same monospace font. There is no distinction between headings, labels, values, and body text.
- Sidebar section titles ("Session", "Usage", "Tools", "Status") are styled with `text-style: bold` and `$primary` color, but this is invisible in the screenshot — they look identical to the values below them.
- The chat area has no distinction between user messages and assistant messages visually (both are plain text on the same background).

### Color Usage
- Cyan is used for the input border and sidebar border. That is it.
- Orange is used for keyboard shortcut hints in the footer.
- The screenshot shows no color differentiation between user messages, assistant messages, tool calls, or errors.

### Spacing
- The sidebar has `padding: 1` but the content inside has no inter-section spacing that creates visual grouping.
- The chat area has `padding: 0 1` which is minimal.

### Contrast
- `$text-muted` is used for sidebar labels but in the screenshot they appear nearly identical to sidebar values. Low contrast between label and value defeats the purpose of having labels.

### Alignment
- Sidebar values are left-aligned but the `key:value` format creates ragged edges because values have different lengths.

---

## 3. Layout

**Score: 3/10**

The 2-column grid layout is a reasonable starting point but the execution is poor.

### What is wrong
- The sidebar is 30 characters wide (fixed). This is too wide for the information it contains, yet too narrow to display the workspace path without wrapping to 4 lines. This is the worst of both worlds.
- The workspace path wrapping is the most visually broken element. It reads:
  ```
  C:\Users\hetba\OneDrive\Des
  ktop\Work\Learn\Projects\Co
  reCode\coding-agent
  ```
  This looks like a bug.
- The chat area takes the remaining space but has no content structure. There is no visual separation between messages.
- The input area is docked to the bottom, which is correct, but there is no visual container or framing around the chat messages above it.
- The footer is a single line with keyboard shortcuts. It wastes space that could be used for status information.
- There is no header bar with useful context (session name, model selector, etc.). The Textual `Header()` widget shows "Coding Agent" which is not useful.

### What wastes space
- The 30-char sidebar is mostly empty vertical space with 4 sections of 2-3 lines each.
- The footer line is mostly empty with 3 shortcuts and a palette hint.

### What feels crowded
- Nothing. The problem is the opposite — the interface feels empty and unfinished.

---

## 4. Developer Experience

**Score: 2/10**

Would a developer enjoy using this for 8 hours? No.

### Reading responses
- Markdown rendering exists (`RichMarkdown`) but the screenshot shows no code blocks, no syntax highlighting, no visual structure in the chat area. If the LLM returns code, it is unclear how it renders.
- There is no way to distinguish between a user message and an assistant message at a glance.

### Viewing tool execution
- Tool calls are displayed as `  [tool_name] args` in muted text. This is invisible during rapid execution.
- Tool results are truncated to 200 characters. For file reads, search results, or shell output, this is useless.
- There is no expand/collapse for tool results.
- There is no visual indicator of tool execution status (running, completed, failed).

### Viewing diffs
- No diff rendering exists. File edits will show as raw text.

### Viewing errors
- Errors are shown in `$error` color but there is no error context, no stack trace display, no file/line reference.

### Viewing logs
- No log viewer exists.

### Viewing file operations
- File operations show as tool call messages. No file tree, no file preview, no diff view.

### Copying code
- No copy-to-clipboard functionality visible.

### Navigation
- No way to jump between messages, search history, or navigate to specific tool calls.

### Keyboard friendliness
- The footer shows `Ctrl+L` clear, `Ctrl+R` regenerate, `Ctrl+N` new session. These are good.
- But there are no vim bindings, no `Ctrl+C` to interrupt a running generation, no `Ctrl+T` for a new tab or split.
- The `SubmitTextArea` overrides Enter to submit but there is no indication of how to edit a previous message.

### Focus management
- Focus is set to the input on mount and after completion. This is correct.
- But there is no focus trapping in the permission dialog — it uses buttons which may not be keyboard-navigable in all TUI contexts.

---

## 5. Agent Experience

**Score: 1/10**

The interface does not communicate that an autonomous agent is working.

### What is missing
| Capability | Status |
|------------|--------|
| Current task | Not shown — sidebar only shows `idle` / `thinking` / `running: tool_name` |
| Current plan | Not shown |
| Completed tasks | Not shown |
| Tool being executed | Sidebar briefly shows `running: tool_name` but disappears on next event |
| Reasoning progress | Not shown |
| Files modified | Not tracked in the UI |
| Current phase | Not shown — no distinction between reading, writing, testing |
| Waiting for approval | Permission dialog exists but minimal |
| Current workspace | Shown in sidebar but broken (wrapping) |
| Progress | No progress bar, percentage, or step counter |

The sidebar state field cycles through `idle → thinking → running: tool_name → thinking → idle` but this is the only agent status indicator. A developer watching this has no idea what the agent is actually doing.

---

## 6. Information Architecture

### Missing panels (everything that modern agents show)

| Panel | Status | Priority |
|-------|--------|----------|
| Task Queue | Missing | High |
| Plan View | Missing | High |
| Execution Timeline | Missing | High |
| Tool History | Missing | High |
| Context Usage (visual) | Partial — text only in sidebar | High |
| Memory | Missing | Medium |
| Workspace Tree | Missing | High |
| Running Processes | Missing | High |
| Logs | Missing | High |
| Model Usage | Partial — sidebar | Medium |
| Token Usage | Partial — sidebar | Medium |
| Permission Queue | Missing | High |
| Git Changes | Missing | High |
| Session Summary | Missing | Medium |
| Checkpoint History | Missing | Medium |
| Recent Files | Missing | High |
| Conversation History | Missing — only current session | High |
| Suggestions | Missing | Medium |

The sidebar currently shows: Model, Provider, Workspace, Tokens, Cost, Tool Calls, State. This is about 10% of what a modern coding agent needs to expose.

---

## 7. Interaction Design

**Score: 2/10**

### Animations
- None visible. The `update_last_assistant` method removes and re-mounts a widget on every streaming chunk, which likely causes flicker rather than smooth updates.

### Loading states
- The input is disabled during processing (`self.user_input.disabled = True`). There is no spinner, no pulsing indicator, no "Agent is thinking..." message in the chat area.

### Streaming
- Streaming works by accumulating text and calling `update_last_assistant` which does a full widget replace. This is inefficient and will cause visual glitches.

### Tool execution
- Tool calls appear as static text lines. No spinner, no animation, no status change.

### Status updates
- The sidebar state updates but there is no notification, no toast, no visual emphasis.

### Error messages
- Errors appear in red text but there is no error boundary, no retry button, no error details expansion.

### Success states
- "Task complete" is shown as a plain text divider line. No emphasis, no summary.

### Confirmation dialogs
- Permission dialog exists with Approve/Always/Deny buttons. This is the only modal interaction.

### Empty states
- The empty chat area shows a welcome message. This is acceptable but bland.

### Keyboard shortcuts
- The footer shows shortcuts but there is no shortcut discoverability (no `?` key for help, no command palette beyond `^p`).

---

## 8. Workflow Friction Points

Imagine using this 8 hours a day:

1. **No context persistence** — Sessions are in-memory. Close the terminal, lose everything. No session history, no resume.

2. **No undo** — If the agent makes a bad edit, there is no checkpoint to roll back to.

3. **No diff preview** — When the agent edits a file, you see a tool call message with truncated args. You have no idea what changed.

4. **No file tree** — You cannot see which files exist in the workspace without leaving the tool.

5. **No split view** — You cannot see the code and the chat simultaneously.

6. **No search** — You cannot search through conversation history.

7. **Permission dialog interruption** — Every write operation requires manual approval. After 100 file edits, this becomes unbearable. The "Always Allow" button exists but there is no scoped permission (e.g., "allow all writes in this directory").

8. **No progress indication** — For large tasks (refactor entire codebase), there is no way to see progress.

9. **No parallel execution** — The agent runs one tool at a time sequentially.

10. **Sidebar path wrapping** — Every time you glance at the sidebar, the workspace path is broken across lines. This is visually noisy.

11. **No command history** — No way to recall previous prompts with arrow keys (the TextArea may support this but it is not obvious).

12. **No autocomplete** — No file path completion, no command completion, no tool name completion.

13. **No model switching** — The model is fixed at startup. No way to switch mid-session.

14. **No cost alerts** — Token cost accumulates but there is no warning when approaching limits.

---

## 9. Comparison Against Modern Coding Agents

| Feature | CoreCode | Claude Code | Cursor Agent | Gemini CLI | OpenCode | Aider | Warp |
|---------|----------|-------------|--------------|------------|----------|-------|------|
| Plan view | No | Yes | Yes | No | Yes | No | No |
| File tree | No | No | Yes | No | Yes | No | Yes |
| Diff view | No | Yes | Yes | No | Yes | Yes | No |
| Tool history | No | Yes | Yes | No | Yes | Yes | Yes |
| Undo/checkpoint | No | Yes | Yes | No | No | Yes | No |
| Context visualization | No | Partial | Yes | No | Yes | No | No |
| Inline code editing | No | Yes | Yes | No | Yes | Yes | No |
| Session persistence | No | Yes | Yes | No | Yes | Yes | Yes |
| Split view | No | No | Yes | No | No | No | Yes |
| Permission scoping | No | Yes | Yes | No | No | No | No |
| Progress indicators | Minimal | Yes | Yes | Yes | Yes | Yes | Yes |
| Streaming display | Basic | Smooth | Smooth | Smooth | Smooth | N/A | Smooth |

CoreCode is behind every single competitor in information architecture and developer experience. The gap is not small.

---

## 10. Scalability

**Score: 1/10**

| Scenario | Assessment |
|----------|------------|
| 100+ tool executions | Every tool call mounts a new `ToolCallMessage` widget. At 100+ widgets, Textual will struggle with render performance. No virtualization exists. |
| 50 modified files | No file tracking. Tool calls show truncated args. At 50 files, the chat becomes an undifferentiated wall of text. |
| Long conversations | The `ContextManager` summarizes at 80% token budget, but the chat display keeps every message widget mounted. At 200+ messages, scroll performance will degrade. |
| Large repositories | No file tree, no indexing, no workspace awareness beyond the path string. |
| Multiple agents | Single agent only. No support for parallel or background agents. |
| Background tasks | No background task support. The input is disabled during execution. |
| Parallel tool execution | Sequential only. The agent loop processes one tool at a time. |
| Large plans | No plan display. Multi-step plans are invisible to the user. |
| Massive outputs | Tool results truncated to 200 chars. Shell output, file reads, search results are all truncated. |

---

## 11. Technical UI Architecture

**Score: 4/10**

### Component structure
- Clean separation: `app.py`, `stream_handler.py`, widgets in `widgets/`. This is good.
- But all widgets are monolithic. `ChatDisplay` handles user messages, assistant messages, tool calls, errors, and status. This should be split.

### Folder organization
- Reasonable: `tui/`, `agent/`, `llm/`, `tools/`, `sandbox/`, `session/`.
- The `tui/theme.py` with a single CSS string constant is not maintainable. At 176 lines it is fine, but it will not scale.

### State management
- State is scattered across `App` attributes (`prompt_tokens`, `completion_tokens`, `tool_count`), `Sidebar` widget state, and `StreamHandler` state (`_current_text`, `_running`).
- No centralized state store. No reactive state. Updates are manual imperative calls.

### Event flow
The flow is:
```
UserInput.Submitted
  → App.on_user_input_submitted
    → StreamHandler.run
      → AgentLoop.process_input (async generator)
        → AgentEvent stream
          → StreamHandler._handle_event
            → widget updates (imperative)
```
This is reasonable but the `StreamHandler` is tightly coupled to both `App` and `AgentLoop`.

### Render performance
- `update_last_assistant` removes and re-mounts a widget on every streaming chunk. This is O(n) in the number of child widgets and triggers a full re-render.
- No debouncing on streaming updates.

### Streaming implementation
- Streaming accumulates text in `_current_text` and calls `update_last_assistant` which creates a new `RichMarkdown` widget every chunk. This is expensive.
- Should update the widget content in-place rather than removing and remounting.

### Virtualization
- None. `VerticalScroll` renders all children.

### Modularity
- Widgets are modular but the `StreamHandler` is a god object that knows about every widget type.

### Maintainability
- The CSS is in a Python string constant. No linting, no hot reload, no syntax highlighting.
- No type safety on sidebar element IDs (strings like `"sidebar-model"`).

---

## 12. Production Readiness

### Would you ship this?

**NO.**

### Reasons
1. The workspace path wrapping in the sidebar is a visual bug that will embarrass you in any demo.
2. There is no session persistence. Losing all context on close is unacceptable.
3. The streaming display will flicker and perform poorly at scale.
4. No diff rendering means developers cannot trust file edits.
5. No error recovery — a single exception in the stream handler crashes the UI.
6. No undo/checkpoint — a single bad edit can destroy a codebase with no rollback.
7. The "Regenerate" button is not implemented (`TODO: implement regeneration`).
8. No tests for the TUI (the test files exist but are not comprehensive).
9. The permission dialog does not support keyboard-only workflow (buttons require mouse or tab navigation).
10. No graceful degradation — if the LLM API is down, the user sees an error message and nothing else.

---

## 13. Final Scorecard

| Dimension | Score |
|-----------|-------|
| Visual Design | 2/10 |
| Developer Experience | 2/10 |
| Agent Experience | 1/10 |
| Interaction Design | 2/10 |
| Layout | 3/10 |
| Scalability | 1/10 |
| Architecture | 4/10 |
| Professional Feel | 2/10 |
| Innovation | 1/10 |
| **Overall** | **2/10** |

---

## 14. Top 50 Problems (Ranked)

### Critical (Ship-blockers)

| # | Problem |
|---|---------|
| 1 | No session persistence — all context lost on close |
| 2 | No diff rendering — file edits are invisible |
| 3 | No undo/checkpoint — no recovery from bad edits |
| 4 | Workspace path wrapping — visual bug in sidebar |
| 5 | Streaming widget remount — flicker and performance issues at scale |
| 6 | Regenerate not implemented — button does nothing |
| 7 | No error recovery — exceptions crash the UI |
| 8 | Tool results truncated to 200 chars — useless for real work |
| 9 | No progress indication — invisible multi-step work |
| 10 | Permission dialog not keyboard-navigable — blocks keyboard-only workflow |

### High

| # | Problem |
|---|---------|
| 11 | No visual distinction between user/assistant messages — chat is unreadable |
| 12 | No file tree or workspace awareness — blind coding |
| 13 | No plan view — multi-step tasks are invisible |
| 14 | No tool execution status — no spinner, no running indicator |
| 15 | No model switching mid-session — locked to startup model |
| 16 | No conversation history — cannot revisit previous sessions |
| 17 | No cost alerts — runaway spending possible |
| 18 | No context usage visualization — invisible token budget |
| 19 | No command autocomplete — no file path or tool name completion |
| 20 | No search in conversation — cannot find previous messages |

### Medium

| # | Problem |
|---|---------|
| 21 | No virtualization — performance degrades with many messages |
| 22 | CSS in Python string — unmaintainable at scale |
| 23 | State scattered across components — no centralized state |
| 24 | StreamHandler is a god object — tightly coupled to all widgets |
| 25 | No vim keybindings — many developers expect this |
| 26 | No split view — cannot see code and chat simultaneously |
| 27 | No toast/notification system — no non-blocking feedback |
| 28 | No empty state guidance — new users do not know what to do |
| 29 | No branded identity — looks like a demo, not a product |
| 30 | No help system — no `?` key, no docs panel |

### Low

| # | Problem |
|---|---------|
| 31 | No animation or transitions — static feel |
| 32 | No theme customization — one color scheme only |
| 33 | No font size control — accessibility concern |
| 34 | No export conversation — cannot save session to file |
| 35 | No workspace switching — fixed to one directory |
| 36 | No background agent execution — input locked during work |
| 37 | No parallel tool execution — sequential bottleneck |
| 38 | No agent memory/persistence — no cross-session learning |
| 39 | No git integration UI — no branch display, no commit view |
| 40 | No diff preview before apply — blind acceptance of edits |
| 41 | Sidebar too wide for content — 30 chars wasted on 3-line sections |
| 42 | Footer wasted on 3 shortcuts — underutilized space |
| 43 | No collapsible sections — sidebar cannot be hidden |
| 44 | No responsive layout — fixed grid does not adapt to terminal size |
| 45 | No accessibility labels — screen reader support absent |
| 46 | No colorblind-friendly palette — relies on red/green/yellow |
| 47 | No log viewer — cannot debug agent behavior |
| 48 | No process manager — cannot see running background commands |
| 49 | No workspace tree diff — cannot see all changed files at once |
| 50 | No session comparison — cannot diff two sessions |

---

## Summary

CoreCode has a functional foundation — the agent loop, tool system, streaming, and permission model work. But the UI is at prototype stage. It is not competitive with any modern coding agent.

The gap is not about polish; it is about missing core features that developers expect.

A redesign should prioritize:
1. Session persistence
2. Diff rendering
3. Plan/task visualization
4. File tree
5. Tool execution feedback
6. A scalable widget architecture that can handle hundreds of tool calls without performance degradation
