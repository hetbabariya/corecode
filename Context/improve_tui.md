# Bring `coding_agent` TUI to Claude Code Parity

## Pre-Plan: Audit Corrections

Several task items describe issues that **don't exist in the current code**:

| Task Claim | Actual Code | Verdict |
|---|---|---|
| 1.1 CSS mismatch `tool-call` vs `.tool-call-message` | `ToolCallMessage` uses class `chat-tool-call`; CSS has `.chat-tool-call` | **Already correct** |
| 1.4 `ChatDivider` Static("─") vs CSS | No `ChatDivider` class exists; CSS `.chat-divider` defined but unused | **Dead CSS** |
| 1.5 `.input-area` on wrong widget | No `.input-area` class used anywhere | **Non-existent** |
| 1.7 `input_text` side channel | `self.app.input_text` never referenced | **Non-existent** |
| 1.8 Dead `SubmitButton` class | Class doesn't exist in codebase | **Already clean** |
| 2.7 Welcome card hardcoded `rgb(0,165,149)` | Welcome CSS uses `{accent}` token; rgb is only in `Theme.border_focus` | **Already tokenized** |
| 4.14 Braille frame duplicates | All 10 frames are unique braille chars | **No duplicates** |

---

## Phase 1 — Correctness Bugs (4 files, ~5 edits)

### 1.2 Fix `asyncio.get_event_loop()` → `asyncio.get_running_loop()`
**File**: `app.py:294`
Replace `asyncio.get_event_loop().create_future()` with `asyncio.get_running_loop().create_future()`.

### 1.3 Remove dead `_blink_phase` ClassVar
**File**: `widgets/chat.py:44`
Remove `_blink_phase: ClassVar[bool] = True` and the toggle line in `toggle_blink()`. The `_blink_phase` field is set but never read — `_current_dot()` uses `time.monotonic()` instead.

### 1.4 Remove dead `.chat-divider` CSS block
**File**: `theme.py:220-224`
Remove the `.chat-divider { ... }` CSS block. No widget uses this class. (Phase 4.2 will create a divider widget when pruning needs it.)

### 1.9 Fix slash command quoted-argument parsing
**File**: `app.py:201-205`
Add `import shlex` at top. Replace naive `text.strip().split(maxsplit=1)` with `shlex.split(text.strip())` wrapped in try/except that falls back to naive split for malformed quotes.

### 1.10 Wrap command handler in try/except
**File**: `app.py:194`
Wrap `self._handle_command(text)` in try/except, routing failures to `ErrorMessage`.

---

## Phase 3 — Theme System Expansion (do BEFORE Phase 2)

Phase 2 needs the expanded tokens from Phase 3.

### 3.1 Expand `Theme` dataclass from 19 → 30+ tokens
**File**: `themes.py`
Add new fields with defaults to `Theme`:
```
status_bar_bg, status_bar_border
chat_user_bg, chat_user_border, chat_assistant_bg, chat_assistant_border
tool_call_border_hover, input_border_focus
scrollbar_thumb, scrollbar_track
link, link_hover
success_border, warning_border, info_border
diff_add_bg, diff_del_bg, diff_ctx_fg
selection_bg, cursor_color
tooltip_bg, tooltip_fg
badge_bg, badge_fg
bg_subtle, bg_muted, bg_emphasized
```
Update all 6 theme instances with appropriate values. This is the largest single edit.

### 3.2 Fix `muted` contrast — computed, not CSS opacity
**File**: `themes.py`
Add helper `_compute_muted(fg, bg, min_ratio=4.5)` that darkens/lightens fg to achieve target contrast. Add `muted_fg` field to Theme computed at definition time.

### 3.3 Add `Theme.validate()` method
**File**: `themes.py`
Implement WCAG luminance formula and contrast ratio computation. Method checks all fg/bg pairs and returns list of warnings for pairs below 4.5:1.

### 3.4 Fix light theme accent contrast
**File**: `themes.py:86`
Change `LIGHT.accent` from `rgb(210,100,50)` to `rgb(180,75,30)` (darker) to guarantee ≥5:1 against `#eff1f5`.

### 3.5 Move hardcoded colors from widget DEFAULT_CSS to theme template
**Files**: `widgets/diff.py` (lines 58-72), `widgets/spinner.py` (lines 55-88)
Remove `DEFAULT_CSS` from both widgets. Add their CSS rules to `_CSS_TEMPLATE` in `theme.py`, using the new tokens (`diff_add_bg`, `diff_del_bg`, `diff_ctx_fg`, etc.). This eliminates all hardcoded colors from widgets.

### 3.6 Extend `_detect_terminal_bg()`
**File**: `themes.py:210-226`
Add checks for `TERM_PROGRAM` (e.g., "Apple_Terminal", "iTerm.app"), `COLORTERM` (e.g., "truecolor"), and `TERM` before defaulting to dark.

### 3.7 Theme persistence
**Files**: `themes.py`, `app.py`
Add `save_theme_preference(name)` and `load_theme_preference()` functions that read/write `~/.coding-agent/config.json`. In `app.py`, load on startup (in `__init__` or `on_mount`) and save in `_cmd_theme()`.

---

## Phase 2 — Visual Parity (using expanded tokens from Phase 3)

### 2.1 Fix invisible scrollbar
**File**: `theme.py` CSS template
Replace `ScrollBar { background: {bg}; }` with:
```css
ScrollBar { background: {scrollbar_track}; }
ScrollBar thumb { background: {scrollbar_thumb}; }
```

### 2.2 Skip — status bar already 1 line
`#status-bar { height: 1; }` at `theme.py:49`. Already matches.

### 2.3 Role-based message styling
**File**: `widgets/chat.py` + `theme.py` CSS
In `ChatMessage.__init__`, add `self.add_class("chat-message")` to all messages. Add CSS:
```css
.chat-message.user { background: {chat_user_bg}; border-left: tall {chat_user_border}; }
.chat-message.assistant { background: {chat_assistant_bg}; border-left: tall {chat_assistant_border}; }
```

### 2.4 Message max-width + text-wrap
**File**: `theme.py` CSS
Add to `.chat-message`:
```css
max-width: 80;
margin: 0 auto;
text-wrap: wrap;
```

### 2.5 TypingIndicator animation
**File**: `widgets/chat.py:138-143`
Add `_frames = ["◇ thinking…", "◈ thinking…", "◆ thinking…"]` and `set_interval(0.5, self._advance_frame)` in constructor. `_advance_frame` increments index and calls `self.update()`.

### 2.6 Focus indicators for PermissionDialog buttons
**File**: `theme.py` CSS
Add:
```css
.permission-btn:focus { border: solid {border_focus}; }
```

### 2.7 Skip — welcome card already tokenized

### 2.8 Add `text-wrap: wrap` globally
**File**: `theme.py` CSS
Add `text-wrap: wrap;` to `.chat-tool-call`, `.chat-tool-result`, `.chat-error`, `DiffWidget`, `#help-bar`.

### 2.9 Fix HelpBar height clipping
**File**: `widgets/help_bar.py` DEFAULT_CSS
Remove `padding: 0 1` from HelpBar. The leading space in the Static text already provides left margin.

---

## Phase 4 — Structural Cleanup

### 4.1 Split `_CSS_TEMPLATE` into per-widget sections
**File**: `theme.py`
Create `_CSS_SECTIONS: dict[str, str]` with keys like `"screen"`, `"status_bar"`, `"chat"`, `"messages"`, `"tools"`, `"input"`, `"permission"`, `"help_bar"`, `"scrollbar"`, `"focus_mode"`. `build_css()` joins them. Enables testing individual fragments.

### 4.2 Add prune marker in `_prune_if_needed()`
**File**: `widgets/chat.py:221-227`
Before removing children, insert a marker:
```python
marker = Static("— Earlier messages trimmed —")
marker.add_class("chat-status")
self.mount(marker)
```
Also create a simple `ChatDivider` class if needed.

### 4.3 Comment `_MAX_CHAT_CHILDREN`
**File**: `widgets/chat.py:20`
Add comment: `# Safety ceiling — sessions rarely exceed 50 children, but this prevents unbounded growth.`

### 4.4 Remove dead `_stable_prefix_memo`
**File**: `widgets/chat.py:213`, `284`, `301`
Remove `_last_assistant_prefix` field and all references. It's set but never read for actual memoization.

### 4.5 Verify PermissionDialog overlay
**File**: `theme.py:265-275`
Already has `layer: overlay; dock: bottom;`. Textual's overlay layer should work. Verify visually; if not, change to absolute positioning with `dock: unset` and fixed bottom margin.

### 4.6 PgUp/PgDn viewport-relative scroll
**File**: `app.py:349-355`
Replace `scroll_page_up()`/`scroll_page_down()` with:
```python
offset = max(1, self.chat_display.size.height - 2)
self.chat_display.scroll_relative(0, -offset)
```

### 4.7 Focus after PermissionDialog closes
**File**: `stream_handler.py:193`
After `self.app.permission_dialog.hide()`, add `self.app.user_input.set_focus()`.

### 4.8 Welcome card mount-order guard
**File**: `widgets/chat.py:231-235`
Add `_ready: bool = False` flag. Set True at end of `add_welcome()`. In `add_user_message()`, if not ready, queue message and flush in `add_welcome()`.

### 4.9 Add `on_resize` handler
**File**: `app.py`
Add `def on_resize(self, event): self.query_one("#help-bar", HelpBar).refresh()` to trigger HelpBar re-render for truncation.

### 4.10 Concurrent tool call tracking
**File**: `stream_handler.py:128-132`
Change `_running_tools` key from `tool_name` to `tool_call_id` (extract from event data). If no ID, use `f"{tool_name}_{self._tool_counts[tool_name]}"`.

### 4.11 Diff detection size gate
**File**: `stream_handler.py:151`
Add `if len(result) > 10_000: skip diff detection` before calling `_render_tool_diff`.

### 4.12 Spinner timer cleanup
**File**: `widgets/spinner.py`
Store timer handles in `self._timers: list[Timer] = []`. Override `on_unmount()` to cancel all. Use `self.set_interval()` instead of `self.set_timer()` for recurring ticks.

### 4.13 Coalesce spinner refresh
**File**: `widgets/spinner.py`
Remove separate shimmer timer. Merge into `_tick()`. Use `self.refresh(layout=False)`.

---

## Phase 5 — Feature Gaps

### 5.1–5.2 Markdown rendering + syntax highlighting
**File**: `widgets/chat.py`
Already uses `RichMarkdown` in `add_assistant_message()` and `update_last_assistant()`. Verify `rich.syntax.Syntax` is used for code fences (it should be by default in `RichMarkdown`). Add explicit `theme="monokai"` if needed.

### 5.3–5.6 Diff improvements
**File**: `widgets/diff.py`
- 5.3: Track line numbers during parsing, show in DiffLine
- 5.4: Parse `@@ -a,b +c,d @@` hunk headers for context
- 5.5: Collapse >5 context lines into `... N lines hidden ...`
- 5.6: Add `text-wrap: wrap` to diff CSS (done in Phase 2.8)

### 5.7 Skip — `_has_escape_codes()` doesn't exist

### 5.8 PermissionDialog keyboard navigation
**File**: `widgets/permission.py`
Add `BINDINGS` to PermissionDialog class:
```python
BINDINGS = [
    Binding("tab", "next_button", show=False),
    Binding("shift+tab", "prev_button", show=False),
    Binding("enter", "confirm", show=False),
    Binding("escape", "deny", show=False),
]
```
Implement `action_next_button()`, `action_prev_button()`, `action_confirm()`, `action_deny()`.

### 5.9 Skip — "Always" button already exists

### 5.10 PermissionDialog button CSS alignment
**File**: `theme.py` CSS
Add `.permission-btn:focus` styling (done in Phase 2.6). Add slide-in animation:
```css
#permission-dialog { animate: slide-up 0.2s; }
```

### 5.11 Context-sensitive HelpBar
**File**: `widgets/help_bar.py`, `app.py`
Add `update_hints(context: str)` method. Different hints for "normal", "permission", "input_disabled" states. Call from `stream_handler.py` when showing/hiding permission dialog.

### 5.12 Adaptive cost formatting
**File**: `widgets/status_bar.py:39`
Replace `f"${cost:.4f}"` with adaptive format:
```python
def _format_cost(cost: float) -> str:
    if cost < 0.01: return f"${cost:.4f}"
    if cost < 1.0: return f"${cost:.3f}"
    return f"${cost:.2f}"
```

### 5.13 Cost threshold coloring
**File**: `widgets/status_bar.py`
In `set_cost()`, add cost-based CSS classes using theme tokens (`status-idle` for <$1, `status-thinking` for $1-$5, `status-error` for >$5).

### 5.14 Arrow character fallback
**File**: `widgets/status_bar.py`
Try `·` character, fall back to `->` on encoding errors. Use try/except UnicodeEncodeError.

### 5.15 Copy support
**File**: `widgets/chat.py`, `app.py`
Add `copy_last_assistant()` to `ChatDisplay` that gets the last assistant widget text and copies via `self.app.clipboard`. Add `ctrl+y` binding.

### 5.16 Custom theme support
**File**: `themes.py`
In `get_theme()`, scan `~/.coding-agent/themes/*.json` for user themes. Parse JSON into `Theme` objects and merge into `THEMES` dict.

---

## Execution Order

1. **Phase 1** — Correctness (app.py, theme.py, chat.py)
2. **Phase 3** — Theme expansion (themes.py, theme.py, diff.py, spinner.py)
3. **Phase 2** — Visual parity (theme.py, chat.py, help_bar.py, permission.py)
4. **Phase 4** — Structural cleanup (theme.py, chat.py, app.py, stream_handler.py, spinner.py)
5. **Phase 5** — Feature gaps (chat.py, diff.py, permission.py, status_bar.py, help_bar.py, themes.py)

After each phase: `ruff check src/coding_agent/tui/` and `pytest tests/test_tui/ -x`.

---

## Acceptance Criteria

- No CSS selector references a class that's never applied
- `grep` for `asyncio.get_event_loop()` returns zero matches in the TUI package
- All timers created by any widget are cancelled on unmount
- Every color in theme.py CSS traces back to a Theme token — zero hardcoded hex/rgb
- `Theme.validate()` passes (all contrast pairs ≥ 4.5:1) for all 6 built-in themes
- Status bar is 1 line tall
- Scrollbar is visibly colored in every theme
- PermissionDialog is fully keyboard-operable (Tab/Enter/Escape)
- Slash command parser handles quoted arguments: `/theme "dark-ansi"`
