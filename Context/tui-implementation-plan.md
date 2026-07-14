# TUI Overhaul: From Basic to Claude Code Quality

**Goal:** Restore deleted TUI features (reverted in commit `062484c` due to black screen regression), fix all 40 audit issues, and bring the TUI to Claude Code parity.

**Total estimated effort:** 69-87 hours across 5 phases, 39 items

**Status: ⬜ PLANNED (0/5 phases, 39 items)**

---

## Context: What Happened

The TUI originally had a rich feature set: 6 themes with 37-token color system, braille-animated spinner, context-sensitive help bar, compact status bar, diff viewer, slash commands, and keyboard navigation. Commit `cdc226b` added these features. Commit `062484c` **reverted everything** due to a "black screen regression" — the app wouldn't render at all.

**Root cause:** Dynamic CSS injection via `build_css(theme)` produced invalid CSS when theme tokens resolved to empty strings or malformed values. The fix: use Textual's CSS variable system properly, with safe fallbacks.

**Strategy:** Don't recover the old code blindly. Rebuild each feature properly, fixing the issues that caused the black screen and the audit findings.

---

## Phase T1: Foundation Recovery & Critical Bug Fixes (15-20h)

**Goal:** Recover deleted features safely, fix bugs that crash or break the UI.

| # | Item | What | Impact |
|---|------|------|--------|
| T1.1 | **Theme system recovery** | Recover `themes.py` from git, fix black screen (use CSS variables, not string interpolation, add safe fallback) | Critical |
| T1.2 | **CSS class mismatches** | Fix `.tool-call-message` vs `.tool-call` selector mismatch | High |
| T1.3 | **Invisible scrollbar** | Add `scrollbar-color` to theme CSS | High |
| T1.4 | **Streaming performance** | Update widget in-place instead of remove+remount on every token | High |
| T1.5 | **None crash fix** | Guard `add_tool_result` against None | Medium |
| T1.6 | **Deprecated API fix** | `get_event_loop()` → `get_running_loop()` | Low |
| T1.7 | **Redundant code** | Remove duplicate `_current_text = ""` | Low |
| T1.8 | **Regenerate** | Implement `action_regenerate()` (currently a stub) | High |

---

### T1.1 Recover Theme System & Fix Black Screen

**Why:** The entire color system was deleted. Without it, the TUI is stuck with Textual's default dark/light.

**What happened:** The pre-revert `themes.py` (481 lines) had a `Theme` dataclass with 37 fields, 6 built-in themes, WCAG contrast validation, custom theme loading from `~/.coding-agent/themes/*.json`, and theme persistence. The `theme.py` used `build_css(theme)` to inject theme tokens into CSS via string formatting. The black screen was caused by CSS injection producing invalid CSS when theme tokens resolved to empty strings or malformed values.

**What to build:**
- Recover `themes.py` from git (`062484c^`)
- **Fix the black screen cause:** Instead of `{placeholder}` string interpolation (fragile), use Textual's CSS variable system (`$primary`, `$surface`, etc.) properly. Map Theme tokens → Textual CSS variables at mount time, not via string formatting
- New approach: `Theme.to_textual_vars()` returns a dict of CSS variables. Set them via `self.stylesheet.variables` or `self.css = template.substitute(vars)`
- Add `Theme.validate()` that catches empty/malformed tokens before CSS injection
- Add safe fallback: if theme loading fails, fall back to default dark theme with a logged warning
- Persist theme choice in `~/.coding-agent/config.json` (already exists in pre-revert code)
- Custom theme loading from `~/.coding-agent/themes/*.json`

**Files to create/modify:**
- `src/coding_agent/tui/themes.py` (RECOVER from git + rewrite CSS injection)
- `src/coding_agent/tui/theme.py` (rewrite to use CSS variables safely)
- `src/coding_agent/tui/app.py` (wire theme loading, add `/theme` slash command)

**Verification:** App launches without black screen. `/theme light` switches colors. `/theme dark` switches back. Invalid theme name shows error, doesn't crash.

**Complexity:** High (8-10 hours)
**Impact:** Critical (unblocks all visual improvements)

---

### T1.2 Fix CSS Class Mismatches

**Why:** Tool call/result messages have wrong CSS classes. `.tool-call-message` selector never matches the actual `.tool-call` class on the widget.

**What to build:**
- In `ToolCallMessage.__init__`: change `self.add_class("tool-call")` to `self.add_class("tool-call-message")`
- In `ToolResultMessage.__init__` (if exists): same fix
- Audit all widget `add_class()` calls against CSS selectors
- Add CSS for role-based message styling: `.chat-message.user`, `.chat-message.assistant`

**Files to create/modify:**
- `src/coding_agent/tui/widgets/chat.py`
- `src/coding_agent/tui/theme.py`

**Verification:** Tool call messages have correct borders and colors.

**Complexity:** Low (1-2 hours)
**Impact:** High (visual correctness)

---

### T1.3 Fix Invisible Scrollbar

**Why:** `scrollbar-color: transparent transparent` makes scrollbar invisible. Users can't see scroll position.

**What to build:**
- Add scrollbar CSS to theme: `scrollbar-color: {scrollbar_thumb} {scrollbar_track}`
- Default `scrollbar_thumb` to `border` color, `scrollbar_track` to `transparent` or `bg_subtle`
- Test on both dark and light themes

**Files to create/modify:**
- `src/coding_agent/tui/theme.py`
- `src/coding_agent/tui/themes.py`

**Verification:** Scrollbar is visible when chat content overflows.

**Complexity:** Low (1 hour)
**Impact:** High (usability)

---

### T1.4 Fix Streaming Performance

**Why:** `update_last_assistant()` removes and re-mounts the entire assistant widget on every streaming token. For long responses, this causes significant lag.

**What to build:**
- Instead of remove+remount, update the `Static` content in-place:
  ```python
  def update_last_assistant(self, content: str) -> None:
      for widget in reversed(self.children):
          if isinstance(widget, ChatMessage) and widget.role == "assistant":
              widget.update(RichMarkdown(content))
              return
  ```
- Add debouncing: batch token updates, flush every 100ms or on TOOL_START
- Use `self.refresh(layout=False)` to skip relayout on content-only changes

**Files to create/modify:**
- `src/coding_agent/tui/widgets/chat.py`

**Verification:** Streaming 1000 tokens doesn't cause visible lag. No widget remounting in logs.

**Complexity:** Medium (3-4 hours)
**Impact:** High (performance)

---

### T1.5 Fix `add_tool_result` Crash on None

**Why:** `result[:200]` on `None` raises `TypeError`.

**What to build:**
- Guard: `preview = str(result)[:200] if result else "(no result)"`
- Add type hint: `result: str | None = None`

**Files to create/modify:**
- `src/coding_agent/tui/widgets/chat.py`

**Verification:** Tool result with None doesn't crash.

**Complexity:** Low (30 min)
**Impact:** Medium (stability)

---

### T1.6 Fix Deprecated `get_event_loop()`

**Why:** `_permission_future` uses `asyncio.get_event_loop().create_future()` which is deprecated in Python 3.10+.

**What to build:**
- Replace with `asyncio.get_running_loop().create_future()`
- Also fix in `ToolCallMessage` if it uses `get_event_loop()`

**Files to create/modify:**
- `src/coding_agent/tui/app.py`
- `src/coding_agent/tui/widgets/chat.py`

**Verification:** No deprecation warnings on startup.

**Complexity:** Low (30 min)
**Impact:** Low (code quality)

---

### T1.7 Fix Redundant `_current_text = ""`

**Why:** Set twice in `_handle_max_iterations`.

**What to build:**
- Remove the duplicate line.

**Files to create/modify:**
- `src/coding_agent/tui/stream_handler.py`

**Verification:** No duplicate assignment.

**Complexity:** Trivial (5 min)
**Impact:** Low (code quality)

---

### T1.8 Implement `action_regenerate()`

**Why:** Ctrl+R shows "not yet implemented". Users expect regeneration to work.

**What to build:**
- Store last user prompt in `_last_user_prompt`
- On regenerate: remove last assistant message, re-run stream handler with same prompt
- Guard against empty history

**Files to create/modify:**
- `src/coding_agent/tui/app.py`
- `src/coding_agent/tui/stream_handler.py`

**Verification:** Ctrl+R re-sends the last prompt and produces a new response.

**Complexity:** Medium (2-3 hours)
**Impact:** High (core feature)

---

## Phase T2: Theme System & Visual Foundation (12-15h)

**Goal:** Full 37-token theme system with 6 built-in themes, custom theme support, and WCAG validation.

| # | Item | What | Impact |
|---|------|------|--------|
| T2.1 | **Expand tokens** | 14 → 37 tokens (status_bar, chat, scrollbar, diff, selection, tooltip, badge, bg tiers) | High |
| T2.2 | **WCAG muted text** | Binary search for contrast-safe muted foreground | High |
| T2.3 | **Theme validation** | `validate()` checks contrast ratios for 9 key pairs | Medium |
| T2.4 | **Custom themes** | Load from `~/.coding-agent/themes/*.json` | Medium |
| T2.5 | **Theme persistence** | Save/load from `~/.coding-agent/config.json` | Medium |
| T2.6 | **Background tiers** | `bg_subtle`, `bg_muted`, `bg_emphasized` | Medium |
| T2.7 | **ANSI fallback** | Use `Color.parse()` not raw tuples | Low |

---

### T2.1 Expand Theme Tokens

**Why:** 14 tokens is insufficient. Need 30+ for proper visual hierarchy.

**What to build:**
- Recover the 37-field `Theme` dataclass from git
- Ensure all fields have sensible defaults via `_with_defaults()`
- Map each token to a CSS variable in the template

**Token groups:**
- Core: `name`, `background`, `foreground`, `surface`
- Messages: `user_message`, `assistant_message`, `error`, `status`
- Chrome: `accent`, `border`, `border_focus`, `border_muted`
- Tools: `tool_border`, `tool_result_ok`, `tool_result_err`
- Permission: `permission_border`
- Status bar: `status_bar_bg`, `status_bar_border`
- Chat: `chat_user_bg`, `chat_user_border`, `chat_assistant_bg`, `chat_assistant_border`
- Scrollbar: `scrollbar_thumb`, `scrollbar_track`
- Diff: `diff_add_bg`, `diff_del_bg`, `diff_ctx_fg`
- Selection: `selection_bg`, `cursor_color`
- Tooltip: `tooltip_bg`, `tooltip_fg`
- Badge: `badge_bg`, `badge_fg`
- Background tiers: `bg_subtle`, `bg_muted`, `bg_emphasized`
- Computed: `muted_fg` (WCAG-safe)

**Files to create/modify:**
- `src/coding_agent/tui/themes.py`

**Verification:** `Theme()` has 37+ fields. All 6 themes define all fields.

**Complexity:** Medium (3-4 hours)
**Impact:** High (visual richness)

---

### T2.2 WCAG-Aware Muted Text

**Why:** Current `muted` property always produces 30% opacity gray, failing WCAG AA on both dark and light themes.

**What to build:**
- `_compute_muted(fg, bg, min_ratio=4.5)` — binary search for a muted foreground that meets contrast ratio
- Use grayscale search: find the closest gray to `fg` that has ≥4.5:1 contrast against `bg`
- Cache computed muted values per theme

**Files to create/modify:**
- `src/coding_agent/tui/themes.py`

**Verification:** Muted text passes WCAG AA on all 6 themes.

**Complexity:** Medium (2-3 hours)
**Impact:** High (accessibility)

---

### T2.3 Theme Validation

**Why:** No way to verify a theme is usable before applying it.

**What to build:**
- `Theme.validate()` → list of issues
- Check: all required fields non-empty
- Check: contrast ratios for 9 key pairs (fg/bg, user/assistant/error/tool text on background)
- `_validate_theme(theme)` function (already existed in pre-revert)
- `validate_all_themes()` — run on all built-in themes at import time

**Files to create/modify:**
- `src/coding_agent/tui/themes.py`

**Verification:** Invalid theme produces clear error messages. All built-in themes pass validation.

**Complexity:** Low (2 hours)
**Impact:** Medium (reliability)

---

### T2.4 Custom Theme Loading

**Why:** Users want to define their own color schemes.

**What to build:**
- Scan `~/.coding-agent/themes/*.json` on startup
- Each JSON file defines a subset of Theme fields
- `_with_defaults()` fills missing fields from the default theme
- Invalid JSON → skip with warning
- List custom themes alongside built-in in `/themes` command

**Files to create/modify:**
- `src/coding_agent/tui/themes.py`

**Verification:** Creating `~/.coding-agent/themes/my-theme.json` with `{"background": "#111111"}` makes it available via `/theme my-theme`.

**Complexity:** Low (2 hours)
**Impact:** Medium (customization)

---

### T2.5 Theme Persistence

**Why:** Theme resets on every launch.

**What to build:**
- `save_theme_preference(name)` → writes to `~/.coding-agent/config.json`
- `load_theme_preference()` → reads on startup
- `get_theme(name=None)` → checks saved preference first, then "dark" default

**Files to create/modify:**
- `src/coding_agent/tui/themes.py`

**Verification:** Set theme to "light", restart app, theme is still "light".

**Complexity:** Low (1 hour)
**Impact:** Medium (UX)

---

### T2.6 Background Tiers

**Why:** Only `background` and `surface` exist. Need subtle/muted/emphasized for layered UI.

**What to build:**
- `bg_subtle` — slightly lighter/darker than background (for hover states)
- `bg_muted` — for disabled states, muted containers
- `bg_emphasized` — for active/selected states
- Default: `bg_subtle` = 5% blend toward surface, `bg_muted` = 15%, `bg_emphasized` = 25%

**Files to create/modify:**
- `src/coding_agent/tui/themes.py`

**Verification:** Status bar, help bar, and permission dialog use appropriate background tiers.

**Complexity:** Low (1-2 hours)
**Impact:** Medium (visual depth)

---

### T2.7 Fix ANSI Theme Fallback

**Why:** `_ansi_fallback()` returns tuples of ints instead of proper `Color` objects. ANSI themes can't use 24-bit colors.

**What to build:**
- Use `Color.parse()` for ANSI color names (e.g., `"black"`, `"white"`)
- Ensure ANSI themes work in both 16-color and 24-bit terminals
- Test with `TERM=xterm-256color` and `TERM=xterm`

**Files to create/modify:**
- `src/coding_agent/tui/themes.py`

**Verification:** ANSI themes render correctly in 16-color terminals.

**Complexity:** Low (1-2 hours)
**Impact:** Low (compatibility)

---

## Phase T3: Widget Restoration & Enhancement (20-25h)

**Goal:** Restore spinner, status bar, help bar, diff widget — all fixed and improved.

| # | Item | What | Impact |
|---|------|------|--------|
| T3.1 | **Spinner** | Recover, fix timer leaks, use `set_interval()`, `refresh(layout=False)` | High |
| T3.2 | **StatusBar** | Recover, 1-line height, reactive labels, cost color thresholds | High |
| T3.3 | **HelpBar** | Recover, context-sensitive, responsive truncation | High |
| T3.4 | **DiffWidget** | Recover, line numbers, context collapse, syntax highlighting | High |
| T3.5 | **TypingIndicator** | CSS pulse animation | Medium |
| T3.6 | **PermissionDialog keyboard nav** | Tab/Enter/Escape navigation | High |
| T3.7 | **Always Allow checkbox** | Persist per-session auto-approve | High |
| T3.8 | **Reactive HelpBar** | Different shortcuts per app state | Medium |

---

### T3.1 Restore and Fix Spinner

**Why:** No visual feedback during streaming. The braille spinner was deleted.

**What to build:**
- Recover `spinner.py` from git
- Fix timer cleanup: override `remove()` to cancel `_tick_timer`, `_shimmer_timer`, `_stall_timer`
- Use `self.set_interval()` instead of raw asyncio timers for proper Textual lifecycle
- Use `refresh(layout=False)` in `_tick()` to skip relayout
- Deduplicate braille frames (half are duplicates in original)
- Add `watch_mode()` to auto-switch frames on mode change
- Make `stall_timeout` configurable via Theme

**Files to create/modify:**
- `src/coding_agent/tui/widgets/spinner.py` (RECOVER + fix)
- `src/coding_agent/tui/app.py` (wire spinner)

**Verification:** Spinner animates during streaming. No timer leaks. Mode changes auto-switch frames.

**Complexity:** Medium (3-4 hours)
**Impact:** High (visual feedback)

---

### T3.2 Restore and Fix StatusBar

**Why:** Current sidebar wastes vertical space. A compact 1-line status bar is better.

**What to build:**
- Recover `status_bar.py` from git
- Make labels `reactive` for proper updates (not manual `update_labels()`)
- Fix cost formatting: 3+ decimal places for small values, color-coded thresholds
- Reduce height to 1 line
- Add session duration label
- Add cost threshold alerts (green < $1, yellow < $5, red > $5)
- Make spinner dock left, labels dock right
- ASCII fallback for `·` separator

**Files to create/modify:**
- `src/coding_agent/tui/widgets/status_bar.py` (RECOVER + fix)
- `src/coding_agent/tui/app.py` (replace sidebar with status bar, or make configurable)

**Verification:** Status bar shows model, cost, tokens, state in 1 line. Cost turns red above $5.

**Complexity:** Medium (3-4 hours)
**Impact:** High (vertical space)

---

### T3.3 Restore and Fix HelpBar

**Why:** Users don't know available keyboard shortcuts. HelpBar shows context-sensitive hints.

**What to build:**
- Recover `help_bar.py` from git
- Make it reactive — update content based on app state
- Read from keybindings.json for dynamic shortcut display
- Add responsive truncation (show fewer shortcuts on narrow terminals)
- Show different shortcuts for different states:
  - Normal: "Enter send · Shift+Enter newline · ↑↓ history · Tab amend"
  - Permission: "Tab cycle · Enter confirm · Escape deny"
  - Disabled: "...waiting..."

**Files to create/modify:**
- `src/coding_agent/tui/widgets/help_bar.py` (RECOVER + fix)
- `src/coding_agent/tui/app.py` (wire help bar, update on state change)

**Verification:** Help bar changes when permission dialog opens. Narrow terminal truncates gracefully.

**Complexity:** Medium (2-3 hours)
**Impact:** High (discoverability)

---

### T3.4 Restore and Fix DiffWidget

**Why:** No way to see file changes inline. Diff viewer was deleted.

**What to build:**
- Recover `diff.py` from git
- Add line numbers to diff lines
- Parse unified diff format properly (handle `@@` headers)
- Add `text-wrap: wrap` to diff content
- Add context collapse for unchanged sections (>5 consecutive context lines → show "N lines hidden")
- Add syntax highlighting for code blocks in diffs (use Rich syntax highlighting)
- Fix width overflow — long lines wrap

**Files to create/modify:**
- `src/coding_agent/tui/widgets/diff.py` (RECOVER + fix)
- `src/coding_agent/tui/stream_handler.py` (use DiffWidget for file edit results)

**Verification:** File edits show inline diffs with line numbers, context collapse, and syntax highlighting.

**Complexity:** High (5-6 hours)
**Impact:** High (visibility into changes)

---

### T3.5 TypingIndicator Animation

**Why:** Current indicator is just static `"..."`. Should show activity.

**What to build:**
- CSS `@keyframes` pulse animation:
  ```css
  @keyframes pulse {
      0%, 100% { opacity: 0.3; }
      50% { opacity: 1.0; }
  }
  .typing-indicator { animation: pulse 1.5s ease-in-out infinite; }
  ```
- Or use Textual timer to cycle through frames: `"."`, `".."`, `"..."`

**Files to create/modify:**
- `src/coding_agent/tui/widgets/chat.py`
- `src/coding_agent/tui/theme.py`

**Verification:** Typing indicator pulses while agent is thinking.

**Complexity:** Low (1-2 hours)
**Impact:** Medium (visual feedback)

---

### T3.6 Keyboard Navigation for PermissionDialog

**Why:** Must click buttons. Should support Tab/Enter/Escape.

**What to build:**
- Tab cycles between Approve / Always Allow / Deny
- Enter confirms currently focused button
- Escape denies
- Visual focus indicator on current button
- Add `on_key` handler to PermissionDialog

**Files to create/modify:**
- `src/coding_agent/tui/widgets/permission.py`

**Verification:** Tab cycles buttons, Enter confirms, Escape denies. No mouse required.

**Complexity:** Medium (2-3 hours)
**Impact:** High (accessibility)

---

### T3.7 "Always Allow" Checkbox

**Why:** Claude Code has "Always allow" for tool permissions. Current button exists but doesn't persist.

**What to build:**
- Add checkbox: "Always allow {tool_name} in this session"
- When checked + approved: set `permission_manager.set_always_allow(tool_name, session=True)`
- Future calls to same tool skip permission dialog
- Visual indicator in StatusBar when auto-approve is active

**Files to create/modify:**
- `src/coding_agent/tui/widgets/permission.py`
- `src/coding_agent/agent/permissions.py` (add `set_always_allow`)
- `src/coding_agent/tui/stream_handler.py` (check always-allow before showing dialog)

**Verification:** Check "Always Allow" for `read_file`, subsequent reads don't show dialog.

**Complexity:** Medium (3-4 hours)
**Impact:** High (workflow speed)

---

### T3.8 Reactive HelpBar

**Why:** HelpBar shows the same shortcuts regardless of context.

**What to build:**
- App calls `help_bar.update_hints(context)` on state changes:
  - Input focused → "Enter send · Shift+Enter newline · ↑↓ history"
  - Permission dialog → "Tab cycle · Enter confirm · Escape deny"
  - Agent running → "...waiting..."
- Read keybindings.json for custom shortcuts
- Responsive: on terminals < 80 cols, show abbreviated hints

**Files to create/modify:**
- `src/coding_agent/tui/widgets/help_bar.py`
- `src/coding_agent/tui/app.py`

**Verification:** Help bar content changes when permission dialog opens.

**Complexity:** Low (1-2 hours)
**Impact:** Medium (UX)

---

## Phase T4: Input, Chat & Stream Polish (12-15h)

**Goal:** Fix input handling, improve chat display, polish streaming.

| # | Item | What | Impact |
|---|------|------|--------|
| T4.1 | **Input history** | Up/Down arrows, deduplication | High |
| T4.2 | **Slash commands** | `shlex.split()` for quoted args, /help /theme /themes /cost /clear /undo | Medium |
| T4.3 | **Focus management** | Return to input after dialog close | High |
| T4.4 | **PgUp/PgDn** | Scroll by viewport height, not 3 lines | Medium |
| T4.5 | **Pruning indicator** | "Earlier messages trimmed" divider | Medium |
| T4.6 | **Role-based CSS** | `.chat-message-user` / `.chat-message-assistant` classes | Medium |
| T4.7 | **Text wrap** | `text-wrap: wrap` globally | Medium |
| T4.8 | **Max-width messages** | Bound assistant message width for readability | Medium |

---

### T4.1 Input History

**Why:** No way to recall previous messages. Up/Down arrows should navigate history.

**What to build:**
- Add `history: list[str]` to `UserInput`
- On submit: append to history (deduplicate)
- Up arrow: move back in history, populate text area
- Down arrow: move forward in history
- History wraps at boundaries
- Max history: 100 entries

**Files to create/modify:**
- `src/coding_agent/tui/widgets/input.py`

**Verification:** Submit 3 messages. Up arrow recalls them in reverse order.

**Complexity:** Medium (2-3 hours)
**Impact:** High (productivity)

---

### T4.2 Slash Command Parsing

**Why:** `/theme "dark-ansi"` fails because parsing doesn't handle quotes.

**What to build:**
- Use `shlex.split()` for parsing (already exists in pre-revert code)
- Fallback to simple split on `ValueError`
- Add commands: `/help`, `/theme`, `/themes`, `/mode`, `/modes`, `/cost`, `/clear`, `/undo`

**Files to create/modify:**
- `src/coding_agent/tui/app.py`

**Verification:** `/theme "dark-ansi"` works. `/help` shows available commands.

**Complexity:** Low (1-2 hours)
**Impact:** Medium (usability)

---

### T4.3 Focus Management

**Why:** After permission dialog closes, focus doesn't return to input.

**What to build:**
- After permission response: `self.user_input.set_focus()`
- After command execution: `self.user_input.set_focus()`
- Track focus state properly with `on_focus`/`on_blur` events

**Files to create/modify:**
- `src/coding_agent/tui/app.py`

**Verification:** After approving a permission, input is focused and ready.

**Complexity:** Low (1 hour)
**Impact:** High (usability)

---

### T4.4 PgUp/PgDn Scrolling

**Why:** Current scroll is only 3 lines. Should scroll by viewport height.

**What to build:**
- `scroll_chat_up`: `self.chat_display.scroll_relative(y=-(self.chat_display.size.height - 2))`
- `scroll_chat_down`: `self.chat_display.scroll_relative(y=self.chat_display.size.height - 2)`
- `scroll_chat_top`: `self.chat_display.scroll_home()`
- `scroll_chat_bottom`: `self.chat_display.scroll_end()`

**Files to create/modify:**
- `src/coding_agent/tui/app.py`

**Verification:** PgDn scrolls a full page. PgUp scrolls back.

**Complexity:** Low (1 hour)
**Impact:** Medium (navigation)

---

### T4.5 Message Pruning Indicator

**Why:** Pruning removes 20% of messages silently. Users lose context.

**What to build:**
- When pruning, add a divider: `"── Earlier messages trimmed ──"`
- Log how many messages were pruned
- Consider: don't prune user messages (only tool results and assistant messages)

**Files to create/modify:**
- `src/coding_agent/tui/widgets/chat.py`

**Verification:** After 500+ messages, a divider appears indicating trimmed content.

**Complexity:** Low (1-2 hours)
**Impact:** Medium (transparency)

---

### T4.6 Role-Based CSS Classes

**Why:** User and assistant messages look the same in CSS.

**What to build:**
- In `ChatMessage.__init__`: `self.add_class(f"chat-message-{role}")`
- Add CSS selectors: `.chat-message-user`, `.chat-message-assistant`
- Style: user messages right-aligned with accent border, assistant left-aligned

**Files to create/modify:**
- `src/coding_agent/tui/widgets/chat.py`
- `src/coding_agent/tui/theme.py`

**Verification:** User messages have different visual treatment from assistant messages.

**Complexity:** Low (1-2 hours)
**Impact:** Medium (visual hierarchy)

---

### T4.7 Global Text Wrap

**Why:** Long lines overflow horizontally.

**What to build:**
- Add `text-wrap: wrap` to Screen or ChatDisplay CSS
- Test with long URLs, long code lines

**Files to create/modify:**
- `src/coding_agent/tui/theme.py`

**Verification:** Long lines wrap instead of overflowing.

**Complexity:** Trivial (15 min)
**Impact:** Medium (readability)

---

### T4.8 Max-Width on Messages

**Why:** Assistant messages stretch full width, hard to read on wide terminals.

**What to build:**
- Add `max-width: 100` to `.chat-message-assistant` (or calculate based on terminal width)
- Add `margin: 0 auto` for centering

**Files to create/modify:**
- `src/coding_agent/tui/theme.py`

**Verification:** On 120-col terminal, assistant messages are bounded.

**Complexity:** Low (30 min)
**Impact:** Medium (readability)

---

## Phase T5: Advanced Features & Polish (10-12h)

**Goal:** Final polish — welcome card, focus indicators, resize handling, session selector, cost warnings.

| # | Item | What | Impact |
|---|------|------|--------|
| T5.1 | **Welcome card color** | Use theme token, not hardcoded `rgb(0,165,149)` | Low |
| T5.2 | **Focus indicators** | `Widget:focus-within` borders | Medium |
| T5.3 | **HelpBar height** | Fix clipping on narrow terminals | Low |
| T5.4 | **Scroll preservation** | Save/restore in focus mode toggle | Low |
| T5.5 | **Resize handling** | `on_resize` to reflow chat | Medium |
| T5.6 | **Session selector** | Ctrl+S quick switch | Medium |
| T5.7 | **Cost warning** | Yellow/red alerts at budget thresholds | Medium |
| T5.8 | **Error boundary** | Wrap `_on_user_submit` in try/except | High |

---

### T5.1 Fix Welcome Card Hardcoded Color

**Why:** Welcome card uses `rgb(0,165,149)` instead of theme token.

**What to build:**
- Replace hardcoded color with `{accent}` theme token
- Ensure welcome card looks correct in all 6 themes

**Files to create/modify:**
- `src/coding_agent/tui/widgets/chat.py`
- `src/coding_agent/tui/theme.py`

**Verification:** Welcome card uses theme accent color in all themes.

**Complexity:** Trivial (15 min)
**Impact:** Low (consistency)

---

### T5.2 Focus Indicators

**Why:** No visual indication of which widget has focus.

**What to build:**
- Add CSS: `Widget:focus-within { border: solid {border_focus}; }`
- Apply to UserInput, PermissionDialog buttons
- Don't apply to ChatDisplay (annoying)

**Files to create/modify:**
- `src/coding_agent/tui/theme.py`

**Verification:** Tabbing to input shows a focus border.

**Complexity:** Low (1 hour)
**Impact:** Medium (accessibility)

---

### T5.3 Help Bar Height Clipping

**Why:** `height: 1` with `padding: 0 1` clips text on narrow terminals.

**What to build:**
- Change to `height: auto` with `min-height: 1`
- Or reduce padding on narrow terminals
- Add `overflow: hidden` to prevent wrapping

**Files to create/modify:**
- `src/coding_agent/tui/theme.py`

**Verification:** Help bar text is fully visible on 80-col terminal.

**Complexity:** Trivial (15 min)
**Impact:** Low (usability)

---

### T5.4 Focus Mode Scroll Preservation

**Why:** Toggling focus mode loses scroll position.

**What to build:**
- In `toggle_focus_mode()`: save `scroll_offset` before toggle
- After toggle: restore `scroll_offset`

**Files to create/modify:**
- `src/coding_agent/tui/app.py`

**Verification:** Toggle focus mode, scroll position is preserved.

**Complexity:** Low (30 min)
**Impact:** Low (UX)

---

### T5.5 Resize Handling

**Why:** Terminal resize doesn't reflow layout.

**What to build:**
- Add `on_resize()` handler
- Refresh HelpBar (responsive truncation)
- Refresh StatusBar (reflow labels)
- Refresh ChatDisplay (recalculate max-width)

**Files to create/modify:**
- `src/coding_agent/tui/app.py`

**Verification:** Resize terminal, layout adapts.

**Complexity:** Low (1 hour)
**Impact:** Medium (robustness)

---

### T5.6 Session Selector

**Why:** No way to switch between recent sessions quickly.

**What to build:**
- New screen or overlay: list last 10 sessions
- Select one to load its context
- Keyboard shortcut: Ctrl+S

**Files to create/modify:**
- `src/coding_agent/tui/screens/session_selector.py` (NEW)
- `src/coding_agent/tui/app.py`

**Verification:** Ctrl+S shows session list, selecting one loads it.

**Complexity:** Medium (3-4 hours)
**Impact:** Medium (workflow)

---

### T5.7 Cost Warning

**Why:** No warning when approaching budget limit.

**What to build:**
- When cost > 80% of budget: show yellow warning in StatusBar
- When cost > 95%: show red warning
- When cost >= 100%: show error, disable input

**Files to create/modify:**
- `src/coding_agent/tui/stream_handler.py`
- `src/coding_agent/tui/widgets/status_bar.py`

**Verification:** Cost approaching budget shows visual warning.

**Complexity:** Low (1-2 hours)
**Impact:** Medium (cost awareness)

---

### T5.8 Error Boundary

**Why:** Errors in `_on_user_submit()` crash the app.

**What to build:**
- Wrap `_on_user_submit()` in try/except
- On error: show ErrorMessage, re-enable input, log error
- Don't let exceptions propagate to Textual's event loop

**Files to create/modify:**
- `src/coding_agent/tui/app.py`

**Verification:** Throwing an error in the agent loop shows an error message, not a crash.

**Complexity:** Low (30 min)
**Impact:** High (stability)

---

## TUI Audit Issue → Implementation Mapping

| # | Audit Issue | Fixed In | Status |
|---|-------------|----------|--------|
| 1 | Only 14 theme tokens | T2.1 | ⬜ |
| 2 | Hardcoded ANSI fallbacks | T2.7 | ⬜ |
| 3 | No contrast ratio checking | T2.3 | ⬜ |
| 4 | Fragile `_detect_terminal_bg()` | T2.5 | ⬜ |
| 5 | No theme persistence | T2.5 | ⬜ |
| 6 | Muted property always 30% | T2.2 | ⬜ |
| 7 | Massive single CSS string | T1.1 (safe injection) | ⬜ |
| 8 | No Widget:focus states | T5.2 | ⬜ |
| 9 | Overly broad selectors | T1.2 | ⬜ |
| 10 | Invisible scrollbar | T1.3 | ⬜ |
| 11 | No responsive breakpoints | T5.3 | ⬜ |
| 12 | PermissionDialog stacking | T3.6 | ⬜ |
| 13 | No max-width on messages | T4.8 | ⬜ |
| 14 | TypingIndicator no animation | T3.5 | ⬜ |
| 15 | Welcome card hardcoded color | T5.1 | ⬜ |
| 16 | HelpBar clips on narrow terminal | T5.3 | ⬜ |
| 17 | No text-wrap | T4.7 | ⬜ |
| 18 | PgUp/PgDn scroll 3 lines | T4.4 | ⬜ |
| 19 | Focus management fragile | T4.3 | ⬜ |
| 20 | Slash command quoting | T4.2 | ⬜ |
| 21 | Focus mode loses scroll | T5.4 | ⬜ |
| 22 | No resize handling | T5.5 | ⬜ |
| 23 | Virtual scroll dead code | T4.5 (pruning) | ⬜ |
| 24 | CSS class mismatches | T1.2 | ⬜ |
| 25 | `call_later` deprecated | T3.1 | ⬜ |
| 26 | Spinner timer leaks | T3.1 | ⬜ |
| 27 | StatusBar 3 lines tall | T3.2 | ⬜ |
| 28 | Cost formatting wrong | T3.2 | ⬜ |
| 29 | HelpBar not reactive | T3.8 | ⬜ |
| 30 | DiffWidget no line numbers | T3.4 | ⬜ |
| 31 | PermissionDialog no keyboard nav | T3.6 | ⬜ |
| 32 | "Always Allow" doesn't persist | T3.7 | ⬜ |
| 33 | Streaming performance | T1.4 | ⬜ |
| 34 | `add_tool_result` crash on None | T1.5 | ⬜ |
| 35 | Deprecated `get_event_loop()` | T1.6 | ⬜ |
| 36 | Redundant `_current_text` | T1.7 | ⬜ |
| 37 | `action_regenerate` stub | T1.8 | ⬜ |
| 38 | Welcome card before first message | T1.1 (mount order) | ⬜ |
| 39 | Debug panel fragile toggle | T5.8 (error boundary) | ⬜ |
| 40 | LogViewer auto_scroll always on | T3.1 (timer cleanup) | ⬜ |

---

## Dependency Graph

```
T1 (Foundation) ←── BLOCKS everything
  ├── T1.1 Theme recovery → T2, T3
  ├── T1.2 CSS class fixes
  ├── T1.3 Scrollbar fix
  ├── T1.4 Streaming performance
  ├── T1.5 None crash fix
  ├── T1.6 Deprecated API fix
  ├── T1.7 Redundant code cleanup
  └── T1.8 Regenerate implementation

T2 (Theme) ←── depends on T1.1
  ├── T2.1 Expand tokens
  ├── T2.2 WCAG muted
  ├── T2.3 Validation
  ├── T2.4 Custom themes
  ├── T2.5 Persistence
  ├── T2.6 Background tiers
  └── T2.7 ANSI fallback

T3 (Widgets) ←── depends on T1.1, T2.1
  ├── T3.1 Spinner
  ├── T3.2 StatusBar
  ├── T3.3 HelpBar
  ├── T3.4 DiffWidget
  ├── T3.5 TypingIndicator
  ├── T3.6 PermissionDialog keyboard nav
  ├── T3.7 Always Allow
  └── T3.8 Reactive HelpBar

T4 (Input/Chat) ←── depends on T1
  ├── T4.1 Input history
  ├── T4.2 Slash commands
  ├── T4.3 Focus management
  ├── T4.4 PgUp/PgDn
  ├── T4.5 Pruning indicator
  ├── T4.6 Role-based CSS
  ├── T4.7 Text wrap
  └── T4.8 Max-width

T5 (Polish) ←── depends on T1-T4
  ├── T5.1 Welcome card color
  ├── T5.2 Focus indicators
  ├── T5.3 HelpBar height
  ├── T5.4 Scroll preservation
  ├── T5.5 Resize handling
  ├── T5.6 Session selector
  ├── T5.7 Cost warning
  └── T5.8 Error boundary
```

---

## Effort Summary

| Phase | Hours | Items | Impact |
|-------|-------|-------|--------|
| T1: Foundation & Bugs | 15-20 | 8 | Critical (unblocks everything) |
| T2: Theme System | 12-15 | 7 | High (visual foundation) |
| T3: Widget Restoration | 20-25 | 8 | High (feature parity) |
| T4: Input/Chat Polish | 12-15 | 8 | Medium (usability) |
| T5: Advanced Polish | 10-12 | 8 | Medium (completeness) |
| **Total** | **69-87** | **39** | |

---

## Recommended Start Order

1. **T1.1** — Theme system recovery (blocks everything)
2. **T1.4** — Streaming performance (most noticeable lag)
3. **T1.2** — CSS class fixes
4. **T1.3** — Scrollbar
5. **T1.5-T1.8** — Remaining bugs
6. **T2.1-T2.7** — Full theme system
7. **T3.1** — Spinner
8. **T3.2** — StatusBar
9. **T3.3** — HelpBar
10. **T3.6-T3.7** — PermissionDialog
11. **T3.4** — DiffWidget
12. **T4.1-T4.8** — Input/chat polish
13. **T5.1-T5.8** — Final polish
