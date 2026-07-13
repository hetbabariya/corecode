# Coding-Agent TUI — Full Audit

## 1. Architecture Overview

```
src/coding_agent/tui/
├── app.py              — Main App, key bindings, slash commands, display modes
├── themes.py           — 6 themes + auto detection, Theme dataclass
├── theme.py            — CSS template generator (_CSS_TEMPLATE, ~200 lines)
├── keybindings.py      — ~/.coding-agent/keybindings.json loader
├── spinner.py          — Braille spinner with 5 modes, stall detection, shimmer
├── stream_handler.py   — Streaming handler, tool grouping, styled banners
└── widgets/
    ├── __init__.py     — Exports all widgets
    ├── chat.py         — ChatDisplay, 8 message types, virtual scroll, pruning
    ├── input.py        — UserInput with history, prompt char
    ├── status_bar.py   — StatusBar with Spinner
    ├── help_bar.py     — HelpBar docked bottom
    ├── diff.py         — DiffWidget, DiffLine
    └── permission.py   — PermissionDialog with anti-misclick
```

---

## 2. Theme System Analysis (`themes.py`)

### What exists
- 6 themes: `dark`, `light`, `dark-ansi`, `light-ansi`, `dark-daltonized`, `light-daltonized`
- `Theme` dataclass with 14 named colors + computed properties (`.ansi`, `.is_dark`, `.muted`)
- Auto-detection via `COLORFGBG` env var
- `get_theme(name)` — lookup by string, case-insensitive
- `list_themes()` — returns all theme names

### Issues
1. **Only 14 semantic tokens** — Claude Code has 69+. No separate tokens for: `status_bar_bg`, `status_bar_border`, `chat_user_bg`, `chat_user_border`, `tool_call_border_hover`, `input_border_focus`, `scrollbar_thumb`, `scrollbar_track`, `link`, `link_hover`, `success_border`, `warning_border`, `info_border`, `diff_add_bg`, `diff_del_bg`, `diff_ctx_fg`, `selection_bg`, `cursor_color`, `tooltip_bg`, `tooltip_fg`, `badge_bg`, `badge_fg`, etc.
2. **Hardcoded ANSI fallbacks** — `_ansi_fallback()` returns tuples of ints, not proper `Color` objects. The ansi themes can't use 24-bit colors even if the terminal supports it.
3. **No contrast ratio checking** — Light themes use the same palette as dark with inverted backgrounds. No guarantee WCAG AA is met.
4. **`_detect_terminal_bg()` is fragile** — only checks `COLORFGBG`, not `TERM_PROGRAM`, `COLORTERM`, or actual terminal queries.
5. **No theme persistence** — theme choice resets on each launch (no `~/.coding-agent/config.json` support).
6. **`muted` property is always 30% opacity** — doesn't adapt to light/dark. In light themes, `fg@30%` is too bright; in dark themes it's too dim.

### Recommendations
- Expand to 30+ semantic tokens minimum.
- Add a `validate()` method that checks contrast ratios.
- Persist theme choice in `~/.coding-agent/config.json`.
- Use `Color.parse()` everywhere instead of raw tuples for ansi themes.
- Add `bg_subtle`, `bg_muted`, `bg_emphasized` tiers (not just bg + surface).

---

## 3. CSS Template Analysis (`theme.py`)

### What exists
- Single `_CSS_TEMPLATE` string (~200 lines) with `{placeholder}` slots filled by theme colors
- Generates CSS for: Screen, StatusbarContainer, StatusBar, Spinner, ChatDisplay, ChatDivider, ToolCallMessage, ToolResultMessage, ToolGroupMessage, ErrorMessage, ChatMessage (user/assistant), WelcomeCard, TaskCompleteBanner, CancelledBanner, MaxIterBanner, TypingIndicator, UserInput, TextArea, HelpBar, PermissionDialog

### Issues
1. **Massive single CSS string** — impossible to test individual selectors. No way to verify a CSS rule compiles correctly without running the full app.
2. **No `Widget:focus` states** — only `UserInput:focus` has a border style change. Other interactive elements (PermissionDialog buttons) have no focus indicator.
3. **Overly broad selectors** — `.user-message` applies `padding: 0 0 1 1` to ALL children of ChatMessage, not just the text content. The `Horizontal` in UserInput means padding goes on the container, not the text area.
4. **`scrollbar-color` is set to `transparent transparent`** — scrollbar is invisible on all themes. Users can't see scroll position.
5. **No responsive breakpoints** — layout is fixed. On narrow terminals (< 60 cols), status bar text wraps or gets clipped.
6. **PermissionDialog** uses `dock: bottom` inside a `Container` — this creates a stacking issue where the overlay doesn't actually overlay the chat area.
7. **`chat-error` has `border-left: heavy {error}`** — but `ErrorMessage` is a `Static`, which doesn't support border in the standard way.
8. **No `max-width` on message bubbles** — long assistant messages stretch full width, hard to read.
9. **`typing-indicator` is just dots** — no animation. Claude Code's typing indicator shows actual "thinking" shimmer.
10. **Welcome card uses hardcoded `rgb(0,165,149)`** — not from theme, will look wrong in light themes.
11. **`help-bar` has `height: 1`** — but content includes `padding: 0 1`, so text is clipped on narrow terminals.
12. **No `text-wrap` CSS** — long lines will overflow horizontally without wrapping in some widgets.

### Recommendations
- Split CSS template into per-widget sections (each testable independently).
- Add scrollbar styling: `scrollbar-color: {border} {bg}` or at minimum `{muted} transparent`.
- Add focus indicators: `Widget:focus-within` borders.
- Add `max-width: 80` to `.assistant-message` or `.chat-message` with `margin: 0 auto`.
- Make welcome card use theme colors, not hardcoded values.
- Add `text-wrap: wrap` globally.
- Test CSS at 80-col and 120-col widths.

---

## 4. App Layout Analysis (`app.py`)

### Layout structure
```
Screen
├── ChatDisplay (scrollable, expand=True)
├── UserInput (height: auto, max-height: 10)
├── StatusBar (height: 3, always visible)
└── HelpBar (dock: bottom)
```

### Issues
1. **No `Binding` for scrolling** — PgUp/PgDn bindings exist but scroll amount is only 3 lines (`self.chat_display.scroll_home()` / `scroll_end()` not used for PgDn/PgUp). Page scroll should be viewport height.
2. **Focus management is fragile** — `_input_changed()` checks `self._is_input_focused` which is a boolean toggled by `on_focus`/`on_blur`. If focus events are lost (e.g., permission dialog closes), focus doesn't return to input.
3. **Slash command parsing** — `_parse_slash_command()` strips whitespace then splits, but doesn't handle quoted arguments (e.g., `/theme "dark-ansi"` would fail).
4. **Display mode** — `DisplayMode.FOCUS` hides status bar and help bar. But `toggle_focus_mode()` doesn't save/restore scroll position, so chat jumps when toggling.
5. **Welcome card** is appended in `on_mount()` — if the user starts typing before mount completes, the welcome card appears below the first message.
6. **No `compose()` ordering guarantee** — `yield ChatDisplay()`, `yield UserInput()`, `yield StatusBar()`, `yield HelpBar()` are in that order, but `HelpBar` has `dock: bottom`. If Textual's layout engine changes, this breaks.
7. **Error handling** — `_handle_command()` catches all exceptions and shows `ErrorMessage`, but `_on_user_submit()` doesn't catch errors from `_session.process_message()`.
8. **No resize handling** — terminal resize doesn't reflow messages or adjust layout.

### Recommendations
- PgUp/PgDn should scroll by `self.chat_display.size.height - 2` (viewport minus padding).
- Save/restore scroll position in `toggle_focus_mode()`.
- Add argument quoting support to slash command parser.
- Add error boundary around `_on_user_submit()`.
- Add `on_resize` handler to reflow chat.

---

## 5. ChatDisplay Analysis (`widgets/chat.py`)

### Widget count: 8 message types
`ChatMessage`, `ToolCallMessage`, `ToolResultMessage`, `ToolGroupMessage`, `ErrorMessage`, `TaskCompleteBanner`, `CancelledBanner`, `MaxIterBanner`, `TypingIndicator`, `WelcomeCard`, `ChatDivider`

### Issues
1. **Virtual scroll is never triggered** — `_MAX_CHAT_CHILDREN = 500`, but `_maybe_prune()` is only called from `_watch_children()` and `append()`. In practice, sessions rarely exceed 50 children. The pruning logic exists but is dead code for most sessions.
2. **`_stable_prefix_memo`** is set but never used for optimization — the intent was to memoize rendered prefix of long messages, but `_render_content()` doesn't use it.
3. **ToolCallMessage CSS** uses `.tool-call-message` but the actual class is `tool-call` (set in `__init__`). The CSS selector `.tool-call-message` never matches. Same issue with `ToolResultMessage` (`.tool-result-message` vs class `tool-result`).
4. **ToolGroupMessage** creates a `Container` with a `Static` header and yields `self.children` — but the `Static` header doesn't update when children change.
5. **`_on_tool_dot_tick`** uses `asyncio.get_event_loop().call_later()` — deprecated in Python 3.10+. Should use `asyncio.get_running_loop().call_later()`.
6. **Spinner in ToolCallMessage** — the `_blinking` class is toggled by `toggle_blink()`, but `_on_click` also toggles it independently, creating race conditions.
7. **`ChatDivider`** is `Static("─")` — but `Static` content is replaced by CSS `content:` property. The divider text gets overridden.
8. **No role-based styling** — `ChatMessage` has a `role` parameter but CSS only uses `.chat-message` (no `.chat-message.user` or `.chat-message.assistant` variants). The user/assistant distinction is lost in CSS.
9. **`TypingIndicator`** just renders `"..."` as a `Static` — no actual animation. Claude Code shows a pulsing dot.
10. **Message pruning** — `_maybe_prune()` removes the oldest 20% when count > 500. This can remove the user's first message or important tool results without warning.

### Recommendations
- Fix CSS class names: use `self.add_class("tool-call-message")` instead of `self.add_class("tool-call")`.
- Actually implement `_stable_prefix_memo` for long messages.
- Add `.user-message` and `.assistant-message` CSS classes based on `role` parameter.
- Replace `call_later` with modern asyncio API.
- Add animation to TypingIndicator (CSS `@keyframes` pulse or Textual timer).
- When pruning, add a "Earlier messages trimmed" divider.
- Make ChatDivider use `content:` CSS property, not Static text.

---

## 6. Input Analysis (`widgets/input.py`)

### Current structure
```
UserInput (Container)
├── Horizontal
│   ├── Static("❯")       — prompt character
│   └── SubmitTextArea    — the actual text input
```

### Issues
1. **SubmitTextArea** has `class="input-area"` but CSS targets `.input-area` on the wrong element — the `Horizontal` parent gets the class, not the `TextArea`.
2. **History navigation** — Up/Down arrows only work when `len(self.history) > 0`, but the history starts empty. User has to submit at least one message before history works. This is expected but undocumented.
3. **`submit_history`** is a plain list — no deduplication. Submitting the same message 10 times adds 10 entries.
4. **`_on_text_area_changed`** sets `self.app.input_text = text` — this is a side-channel for the app to read input. But `app.input_text` is a `str` attribute set in `on_mount()`, not a reactive. If another widget reads it, it gets stale data.
5. **`_on_key` returns `True`** from the handler — this swallows the event. But `_handle_history` also returns `True` from `event.prevent_default()`. The flow is: `_on_key` → `_handle_history` → `event.prevent_default()`. If `_handle_history` returns `False`, the key event propagates to the TextArea, which is correct. But the `return True` in `_on_key` prevents `SubmitTextArea._on_key` from running first.
6. **No paste handling** — multi-line paste is supported by TextArea, but there's no special handling for very long pastes (e.g., pasting a file).
7. **Submit button** — there's a `SubmitButton` class defined but never used (dead code).
8. **Disabled state** — when `disabled=True`, the TextArea is disabled but the prompt character `❯` stays the same color. Should dim.

### Recommendations
- Add `self.history = list(dict.fromkeys(self.history))` on submit to deduplicate.
- Make `input_text` a proper `reactive` on the app.
- Remove dead `SubmitButton` class.
- Dim the prompt character when input is disabled.
- Add paste event handler for very long inputs (> 50 lines: confirm before sending).

---

## 7. Spinner Analysis (`widgets/spinner.py`)

### Current structure
- 5 modes: `DEFAULT` (braille), `WORKING`, `DONE`, `THINKING`, `SHIMMER`
- 16 braille frames, 8 shimmer frames
- `set_mode()` auto-picks frames based on mode
- `_tick()` runs at `1/fps` interval, advances frame, calls `refresh()`
- `token_received()` resets stall timer (stall_timeout=3.0s)
- `shimmer_position` updated via timer at 100ms

### Issues
1. **`refresh()` called too frequently** — at 12fps, `_tick()` calls `refresh()` every ~83ms. If the terminal is slow, this causes flicker. Should use `self.refresh(layout=False)` to skip relayout.
2. **No `watch_mode`** — mode changes don't auto-switch frames. User must call `set_mode()` explicitly.
3. **`stall_timeout=3.0` is hardcoded** — should be theme-configurable or user-configurable.
4. **Shimmer animation** — `_update_shimmer()` calls `self.refresh()` every 100ms independently of `_tick()`. This means the spinner can refresh 20+ times/sec during shimmer, causing excessive redraws.
5. **`set_size()`** — doesn't exist but is called in `spinner.py` if terminal is resized. The spinner doesn't respond to resize.
6. **No `remove()` override** — spinner timers (`_tick_timer`, `_shimmer_timer`, `_stall_timer`) are never cleaned up when the widget is removed from DOM. This causes timer leaks.
7. **Braille frames** — `⠀⠁⠃⠇⠏⠟⠿⣿` is only 8 frames, not 16. The `_BRAILLE_FRAMES` list has 16 entries but half are duplicates.

### Recommendations
- Use `refresh(layout=False)` in `_tick()`.
- Add `watch_mode()` to auto-switch frames.
- Add `remove()` method to cancel all timers.
- Use `self.set_interval()` / `self.set_timer()` instead of raw asyncio timers for proper cleanup.
- Deduplicate braille frames or use a proper rotation set.
- Make stall_timeout configurable via Theme.

---

## 8. StatusBar Analysis (`widgets/status_bar.py`)

### Current structure
```
StatusBar (Container, horizontal)
├── Spinner
├── ModelLabel — "Model"
├── CostLabel — "$0.00"
├── TokensLabel — "0 → 0"
├── StateLabel — state icon + text
└── PermLabel — "auto-approve: off"
```

### Issues
1. **All labels are `Static`** — no reactive properties. `update_labels()` manually updates each one. If a label update fails, the others don't render.
2. **Cost formatting** — `_format_cost()` truncates to 2 decimal places. For costs > $1.00, this shows `$1.00` instead of `$1.23`. For costs < $0.01, it shows `$0.00` which is misleading.
3. **Tokens display** — `→` character may not render in all terminals. Should use `->` as fallback.
4. **Permission mode** — shows "auto-approve: on/off" but doesn't show the actual mode (e.g., "plan", "full-auto", "semi-auto").
5. **No cost threshold alerts** — no visual warning when cost exceeds a threshold (e.g., > $5.00 turns red).
6. **Spinner is inline** — it takes horizontal space and pushes labels right. On narrow terminals, labels get clipped.
7. **Height: 3** — status bar is 3 lines tall. Claude Code's is 1 line. This wastes vertical space.

### Recommendations
- Make labels `reactive` for proper updates.
- Format cost with 3+ decimal places for small values.
- Add cost threshold color change (green < $1, yellow < $5, red > $5).
- Reduce height to 1 line.
- Make spinner dock left, labels dock right (or use `layout: horizontal` with `dock`).
- Add a "session duration" label.

---

## 9. HelpBar Analysis (`widgets/help_bar.py`)

### Current structure
```
HelpBar (Static, dock: bottom)
content: "Enter: send | Shift+Enter: newline | ↑↓: history | Tab: amend | Ctrl+E: explain"
```

### Issues
1. **Static content** — doesn't change based on context. When PermissionDialog is open, help bar should show approve/deny shortcuts.
2. **No responsive design** — on terminals < 80 cols, text wraps or clips.
3. **Hardcoded shortcuts** — keybindings.json support exists in `keybindings.py` but help bar doesn't read from it.
4. **No active state indication** — can't tell which keybindings are currently active vs disabled.

### Recommendations
- Make HelpBar reactive — update content based on app state.
- Read from keybindings.json for dynamic shortcut display.
- Add responsive truncation (show fewer shortcuts on narrow terminals).
- Show different shortcuts for different states (input focused, permission dialog, etc.).

---

## 10. DiffWidget Analysis (`widgets/diff.py`)

### Issues
1. **`_has_escape_codes()`** — checks if ANY line in text starts with `\x1b[` — this is a heuristic that can false-positive on files that contain escape sequences as content.
2. **No line numbers** — Claude Code shows line numbers in diffs.
3. **No syntax highlighting** — diffs are plain colored text, no language-specific highlighting.
4. **`_render_diff()`** — processes line-by-line but doesn't handle unified diff format (no `@@` hunk header parsing).
5. **Width overflow** — long lines in diffs don't wrap. They extend beyond the widget boundary.
6. **No context collapse** — showing full diff for large changes is overwhelming. Should collapse unchanged sections.

### Recommendations
- Add line numbers to diff lines.
- Parse unified diff format properly (handle `@@` headers).
- Add `text-wrap: wrap` to diff content.
- Add context collapse for unchanged sections (show `... N lines hidden ...`).
- Add syntax highlighting for code blocks in diffs.

---

## 11. PermissionDialog Analysis (`widgets/permission.py`)

### Issues
1. **200ms anti-misclick** — `asyncio.sleep(0.2)` blocks the event loop. Should use `await asyncio.sleep(0.2)` (it already does, but the sleep is inside `_on_mount` which blocks rendering).
2. **No keyboard navigation** — must click buttons. Should support Tab to cycle options, Enter to confirm.
3. **No "always allow" checkbox** — Claude Code has "Always allow" option for tool permissions.
4. **Button styling** — buttons use `variant="primary"` and `variant="error"` but CSS targets `.permission-approve` and `.permission-deny` classes. The button text color overrides are lost.
5. **No animation** — dialog appears instantly. Should slide in from bottom.

### Recommendations
- Add keyboard navigation (Tab, Enter, Escape).
- Add "Always allow" checkbox.
- Use proper button class selectors in CSS.
- Add slide-in animation.
- Move 200ms delay to after mount (don't block rendering).

---

## 12. StreamHandler Analysis (`stream_handler.py`)

### Issues
1. **`_current_tool_call`** — tracks active tool call for streaming, but if two tools run concurrently, only the last one's output is shown.
2. **Banners are appended as separate messages** — `TaskCompleteBanner` is a standalone widget appended to chat. But it should be inline with the last assistant message.
3. **`_on_cancelled()`** — cancels the current stream but doesn't update the spinner to "DONE" mode. Spinner stays in "WORKING" state after cancel.
4. **Tool grouping** — groups tools by consecutive calls, but doesn't handle tool results that arrive out of order.
5. **Diff detection** — `diff_utils.is_diff()` is called on every tool result. If the tool result is very large (e.g., `cat` of a 1000-line file), this is slow.
6. **No progress indication** — for long-running tools, there's no progress bar or step counter.

### Recommendations
- Support concurrent tool calls with separate tracking.
- Make banners inline with assistant messages.
- Update spinner mode on cancel.
- Add progress indication for long-running tools.
- Cache diff detection results.

---

## 13. Color Palette Analysis

### Dark Theme
| Element | Color | Contrast on `#0d1117` | WCAG AA? |
|---------|-------|----------------------|----------|
| User text | `#4eba65` (green) | 7.2:1 | ✅ Pass |
| Assistant text | `#b3b1ad` (gray) | 9.8:1 | ✅ Pass |
| Accent/spinner | `#d77757` (orange) | 4.8:1 | ✅ Pass (large text) |
| Tool border | `#d4a72c` (yellow) | 8.1:1 | ✅ Pass |
| Error border | `#ab233f` (red) | 5.2:1 | ✅ Pass |
| Muted text | `#6e6e6e` @ 30% opacity | ~1.5:1 | ❌ Fail |
| Input border | `#00a595` (teal) | 5.6:1 | ✅ Pass |

### Light Theme
| Element | Color | Contrast on `#fafafa` | WCAG AA? |
|---------|-------|----------------------|----------|
| User text | `#1a7f37` (green) | 5.1:1 | ✅ Pass |
| Assistant text | `#57606a` (gray) | 5.8:1 | ✅ Pass |
| Accent/spinner | `#bc4c00` (orange) | 4.6:1 | ⚠️ Borderline |
| Muted text | `#6e6e6e` @ 30% opacity | ~3.5:1 | ❌ Fail |

### Issues
1. **Muted text fails WCAG** on both themes — 30% opacity on any background is too low contrast.
2. **Light theme accent is borderline** — `#bc4c00` on `#fafafa` is 4.6:1, just above the 4.5:1 threshold for normal text.
3. **No dark-on-dark or light-on-light protection** — if a user has a dark terminal but sets `theme=light`, the colors will be wrong.
4. **ANSI themes** use 16-color palette — no guarantee the user's terminal maps these correctly.

---

## 14. Overall Comparison to Claude Code

| Feature | Claude Code | coding-agent | Gap |
|---------|-------------|--------------|-----|
| Themes | 7 built-in + custom | 6 built-in (no custom) | Custom theme support |
| Theme tokens | 69+ | 14 | 55+ missing tokens |
| Spinner | Multi-mode + shimmer | Multi-mode + shimmer | ✅ Parity |
| Tool display | Grouped + diff | Grouped + diff | ✅ Parity |
| Input history | Up/Down | Up/Down | ✅ Parity |
| Virtual scroll | Yes | Yes (but never triggers) | Dead code |
| Permission dialog | Anti-misclick + keyboard | Anti-misclick only | No keyboard nav |
| Help bar | Context-sensitive | Static | Major gap |
| Status bar | 1-line, reactive | 3-line, manual update | Major gap |
| Scrollbar | Visible, styled | Invisible | Major gap |
| Message pruning | Smart trimming | 20% oldest removed | Dumb pruning |
| Focus mode | Yes | Yes | ✅ Parity |
| Slash commands | /help /theme /cost | /help /theme /mode /modes | Partial parity |
| Markdown rendering | Full | None (plain text) | Major gap |
| Code block highlighting | Yes | None | Major gap |
| Copy support | Yes | No | Major gap |

---

## 15. Top 10 Priority Improvements

1. **Fix invisible scrollbar** — add `scrollbar-color` to theme CSS
2. **Fix CSS class mismatches** — `.tool-call-message` vs `.tool-call`, etc.
3. **Reduce status bar to 1 line** — save vertical space
4. **Add keyboard nav to PermissionDialog** — Tab/Enter/Escape
5. **Make HelpBar context-sensitive** — show relevant shortcuts per state
6. **Fix muted text contrast** — increase opacity or use computed contrast-safe colors
7. **Add focus indicators** — `Widget:focus-within` borders
8. **Implement TypingIndicator animation** — CSS pulse or timer-based
9. **Fix tool dot race condition** — separate blink state from click state
10. **Add message pruning indicator** — "Earlier messages trimmed" divider
