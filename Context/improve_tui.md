# TUI Improvement Plan — Match Claude Code

**Goal:** Make the coding-agent TUI look and feel like Claude Code's terminal interface.

**Current state:** Basic Textual TUI with chat display, sidebar, input, and permission dialog. Functional but visually plain.

**Target:** Claude Code-level polish — status bar, colored messages, tool status dots, spinner animations, input history, diff rendering, themes.

---

## Claude Code Reference

Claude Code uses React/Ink (251KB renderer, Yoga Flexbox, virtual DOM). Key design principles:

- **Observable Autonomy** — every operation is transparent, users can Ctrl+C within 3 seconds if the agent goes wrong
- **Animation encodes information** — spinner color, shimmer speed, synchronized blinking all convey state
- **Minimal interruptions** — 200ms anti-misclick delay on permission prompts
- **7 built-in themes** with 69+ color tokens

### Claude Code Layout
```
┌─ Status Bar ──────────────────────────────────────┐
│ model · cost · tokens · state · permission mode    │
├─ Chat Area (scrollable) ──────────────────────────┤
│ [green] User message                              │
│ [blue]  Assistant response with markdown          │
│ [yellow border] ● Tool call (blinking while run)  │
│ [green border] Tool result                        │
│ [red border] Error result                         │
├─ Input Area ──────────────────────────────────────┤
│ ┌─ teal border ──────────────────────────────┐    │
│ │ Type message...                            │    │
│ └────────────────────────────────────────────┘    │
├─ Help Bar ────────────────────────────────────────┤
│ Enter send · Shift+Enter newline · ↑↓ history     │
└───────────────────────────────────────────────────┘
```

### Claude Code Color Palette (Dark Theme)
| Element | Color |
|---------|-------|
| User messages | `rgb(78,186,101)` green |
| Assistant messages | blue |
| Brand accent (spinner, label) | `rgb(215,119,87)` orange |
| Tool use borders | yellow |
| Tool result success | green borders |
| Tool result error | red borders |
| Errors | `rgb(171,43,63)` red |
| Input prompt border | teal `rgb(0,165,149)` |
| Permission prompt | yellow double border |
| Muted text/borders | gray |

---

## Phase 1: Visual Foundation (Immediate)

**Goal:** Match Claude Code's look and feel.

### 1a. Fix button text color
- `theme.py`: Add `Button.-success { color: white; }`, `Button.-warning { color: black; }`, `Button.-error { color: white; }`
- Remove dead CSS classes (`.permission-approve`, `.permission-deny`, `.permission-always`)

### 1b. Color scheme (match Claude Code dark theme)
- `theme.py`: Define CSS variables matching Claude Code's palette
- Update all widget CSS to use these variables
- File: `tui/theme.py` (major rewrite)

### 1c. Status bar (top)
- New widget `tui/widgets/status_bar.py`: Single-line bar showing:
  - Model name (e.g. "openai/gpt-4o-mini")
  - Accumulated cost ($0.0042)
  - Token count (1,234)
  - State indicator (idle / thinking / running tool)
  - Permission mode badge
- `app.py`: Replace `Header()` with `StatusBar`, dock top
- Remove sidebar (merge into status bar or keep as optional)
- Files: `tui/widgets/status_bar.py` (new), `tui/app.py`

### 1d. Permission dialog redesign
- `theme.py`: Double border in yellow, matching Claude Code's style
- `permission.py`: Add 200ms anti-misclick delay before accepting input
- Show tool name, args, and permission level in a compact format
- Buttons: green "Allow" / yellow "Always" / red "Deny" with proper text colors
- Files: `tui/widgets/permission.py`, `tui/theme.py`

### 1e. Message styling
- `chat.py`: User messages in green, assistant in default
- Tool calls: yellow left border, compact format
- Tool results: green (success) or red (error) left border
- Status messages: muted/gray
- Files: `tui/widgets/chat.py`

### 1f. Input area
- `theme.py`: Input border in teal `rgb(0,165,149)` when focused, gray when disabled
- `input.py`: Disable input during streaming, gray border
- Files: `tui/widgets/input.py`, `tui/theme.py`

### Files to create/modify:
- `tui/widgets/status_bar.py` (new)
- `tui/theme.py` (major rewrite)
- `tui/app.py` (replace Header with StatusBar, remove sidebar)
- `tui/widgets/permission.py` (anti-misclick, styling)
- `tui/widgets/chat.py` (message colors, borders)
- `tui/widgets/input.py` (disabled state styling)

---

## Phase 2: Tool Display (Match Claude Code)

**Goal:** Tool calls look like Claude Code's inline tool display.

### 2a. Tool status dots
- New widget or style for the blinking dot:
  - Blinking dim = executing
  - Static green = success
  - Static red = error
- Textual supports CSS `text-style: blink` for blinking

### 2b. Tool result borders
- Green left border for success results
- Red left border for error results
- Yellow left border for tool invocations

### 2c. Diff rendering
- New widget `tui/widgets/diff.py`: Render file edits as git diff
  - Deleted lines in red
  - Added lines in green
  - Context lines in gray
  - Line numbers
- `stream_handler.py`: Detect edit_file tool results and render as diff

### 2d. Tool grouping
- Multiple reads of same type shown as a single list
- Reduces visual noise

### Files to create/modify:
- `tui/widgets/diff.py` (new)
- `tui/widgets/chat.py` (tool status dots, colored borders)
- `tui/stream_handler.py` (diff detection, tool grouping)

---

## Phase 3: Animations (Match Claude Code)

**Goal:** State-aware animations.

### 3a. Multi-state spinner
- New widget `tui/widgets/spinner.py`:
  - Unicode Braille characters: `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`
  - Modes: requesting (fast 50ms), thinking (slow 200ms), responding, tool-use
  - Arrows: `↑` for requesting, `↓` for responding
- `app.py`: Show spinner in status bar during streaming

### 3b. Stall indication
- When model stops producing tokens and no tools running:
  - Gradually transition spinner color from orange to red
  - `stalledIntensity` 0-1 drives RGB interpolation

### 3c. Shimmer effects
- Character-level shimmer on spinner text
- Light point sweeps left-right at 20fps
- Different speeds for different states

### 3d. Synchronized blinking
- All tool status dots share a single animation clock
- `Math.floor(time / 600ms) % 2 === 0` formula
- Pause blinking when terminal loses focus

### Files to create/modify:
- `tui/widgets/spinner.py` (new)
- `tui/app.py` (spinner integration)
- `tui/widgets/chat.py` (synchronized tool dots)

---

## Phase 4: Input & Interaction (Match Claude Code)

**Goal:** Input behaves like Claude Code.

### 4a. Input history
- `input.py`: Store previous inputs in a list
- Up/Down arrows navigate history
- History persists during session

### 4b. Keyboard shortcuts
- `app.py` bindings matching Claude Code:
  - `Escape` = cancel current operation
  - `Tab` = amend (edit last message)
  - `Ctrl+E` = explain current tool call
  - `PgUp/PgDn` = scroll chat
  - `Ctrl+Home/Ctrl+End` = scroll to top/bottom

### 4c. Help bar
- New widget `tui/widgets/help_bar.py`: Single-line bar at very bottom
  - Shows available shortcuts: `Enter send · Shift+Enter newline · ↑↓ history · Ctrl+C quit`
- `app.py`: Add help bar, dock bottom

### 4d. Input disabled state
- During streaming: border turns gray, keyboard input ignored
- Visual indicator that agent is working

### Files to create/modify:
- `tui/widgets/input.py` (history, disabled state)
- `tui/widgets/help_bar.py` (new)
- `tui/app.py` (new bindings, help bar)

---

## Phase 5: Advanced Features (Match Claude Code)

**Goal:** Production-quality features.

### 5a. Virtual scrolling
- `chat.py`: Only render visible messages (like Claude Code's VirtualMessageList)
- Textual's `VerticalScroll` already does this partially
- Optimize for hundreds of messages

### 5b. Theme system
- `tui/themes.py` (new): Define 7 themes matching Claude Code
  - dark, light, dark-daltonized, light-daltonized, dark-ansi, light-ansi, auto
- `theme.py`: Load theme tokens dynamically
- `/theme` command to switch themes

### 5c. Display modes
- Default mode (scrolling log) — current behavior
- Fullscreen mode — already our default with Textual
- Focus mode — shrink to: last prompt, one-line summary per tool call, final response

### 5d. Markdown rendering
- `chat.py`: Render assistant messages with full markdown
  - Code blocks with syntax highlighting (via pygments)
  - Bold, italic, lists, links
  - Stable prefix memoization for streaming

### 5e. Custom keybindings
- `~/.coding-agent/keybindings.json` support
- Chord shortcuts and context conditions

### Files to create/modify:
- `tui/themes.py` (new)
- `tui/theme.py` (dynamic theme loading)
- `tui/widgets/chat.py` (virtual scroll, markdown)
- `tui/app.py` (display modes, keybinding config)

---

## Execution Order

| Phase | Effort | Impact | Dependencies |
|-------|--------|--------|-------------|
| 1 (Visual) | 2-3 days | High | None |
| 2 (Tools) | 2-3 days | High | Phase 1 |
| 3 (Animations) | 2-3 days | Medium | Phase 1 |
| 4 (Input) | 1-2 days | Medium | Phase 1 |
| 5 (Advanced) | 3-5 days | Medium | Phases 1-4 |

**Total: ~10-16 days of focused work**

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/coding_agent/tui/app.py` | Main TUI app (grid layout, bindings, compose) |
| `src/coding_agent/tui/theme.py` | All CSS styles |
| `src/coding_agent/tui/stream_handler.py` | AgentEvent → UI bridge |
| `src/coding_agent/tui/widgets/chat.py` | ChatDisplay, ChatMessage, ToolCallMessage |
| `src/coding_agent/tui/widgets/input.py` | UserInput with SubmitTextArea |
| `src/coding_agent/tui/widgets/permission.py` | PermissionDialog with buttons |
| `src/coding_agent/tui/widgets/sidebar.py` | Sidebar (to be merged into status bar) |
| `src/coding_agent/tui/widgets/status_bar.py` | (new) Top status bar |
| `src/coding_agent/tui/widgets/spinner.py` | (new) Multi-state spinner |
| `src/coding_agent/tui/widgets/diff.py` | (new) Git diff renderer |
| `src/coding_agent/tui/widgets/help_bar.py` | (new) Bottom help bar |
| `src/coding_agent/tui/themes.py` | (new) Theme definitions |
