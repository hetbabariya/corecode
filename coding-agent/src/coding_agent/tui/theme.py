"""Textual CSS theme for the coding agent TUI.

Provides ``build_css(theme)`` which generates a complete Textual CSS
stylesheet from a :class:`~coding_agent.tui.themes.Theme` object.
"""

from __future__ import annotations

from coding_agent.tui.themes import Theme, get_theme


def build_css(theme: Theme | None = None) -> str:
    """Return the full Textual CSS for the given *theme*."""
    if theme is None:
        theme = get_theme()
    return _CSS_TEMPLATE.format(
        bg=theme.background,
        fg=theme.foreground,
        surface=theme.surface,
        user_msg=theme.user_message,
        assistant_msg=theme.assistant_message,
        err=theme.error,
        status=theme.status,
        muted=theme.muted_fg,
        accent=theme.accent,
        border=theme.border,
        border_focus=theme.border_focus,
        border_muted=theme.border_muted,
        tool_border=theme.tool_border,
        tool_ok=theme.tool_result_ok,
        tool_err=theme.tool_result_err,
        perm_border=theme.permission_border,
        btn_s_fg=theme.btn_success_fg,
        btn_w_fg=theme.btn_warning_fg,
        btn_e_fg=theme.btn_error_fg,
        sb_bg=theme.status_bar_bg,
        sb_border=theme.status_bar_border,
        chat_user_bg=theme.chat_user_bg,
        chat_user_border=theme.chat_user_border,
        chat_asst_bg=theme.chat_assistant_bg,
        chat_asst_border=theme.chat_assistant_border,
        tool_border_hover=theme.tool_call_border_hover,
        input_focus=theme.input_border_focus,
        sb_thumb=theme.scrollbar_thumb,
        sb_track=theme.scrollbar_track,
        success_bdr=theme.success_border,
        warning_bdr=theme.warning_border,
        info_bdr=theme.info_border,
        diff_add_bg=theme.diff_add_bg,
        diff_del_bg=theme.diff_del_bg,
        diff_ctx_fg=theme.diff_ctx_fg,
        sel_bg=theme.selection_bg,
        cursor_clr=theme.cursor_color,
        tooltip_bg=theme.tooltip_bg,
        tooltip_fg=theme.tooltip_fg,
        badge_bg=theme.badge_bg,
        badge_fg=theme.badge_fg,
        bg_subtle=theme.bg_subtle,
        bg_muted=theme.bg_muted,
        bg_emphasized=theme.bg_emphasized,
    )


_CSS_TEMPLATE = """\
/* ── Screen layout ─────────────────────────────────────── */
Screen {{
    background: {bg};
    color: {fg};
    layers: default overlay;
}}

/* ── Status bar (top) ──────────────────────────────────── */
#status-bar {{
    dock: top;
    height: 1;
    layout: horizontal;
    background: {sb_bg};
    color: {fg};
    padding: 0 1;
    border-bottom: solid {sb_border};
}}

/* ── Chat area (main panel) ────────────────────────────── */
#chat {{
    height: 1fr;
    overflow-y: auto;
    padding: 1 1;
    background: {bg};
}}

/* ── Input area ────────────────────────────────────────── */
#input-container {{
    dock: bottom;
    height: auto;
    min-height: 3;
    max-height: 12;
    padding: 0 1;
    background: {bg};
}}

#input-box {{
    height: auto;
    min-height: 3;
    max-height: 10;
    layout: horizontal;
    border: solid {border};
    background: {surface};
}}

#input-box:focus-within {{
    border: solid {input_focus};
}}

#input-box.disabled {{
    border: solid {border_muted};
    opacity: 0.6;
}}

#input-prompt {{
    width: 2;
    height: auto;
    min-height: 3;
    content-align: center middle;
    text-align: center;
    color: {accent};
    background: transparent;
}}

#user-input {{
    height: auto;
    min-height: 3;
    max-height: 10;
    width: 1fr;
    background: transparent;
    color: {fg};
    border: none;
}}

#user-input:focus {{
    border: none;
}}

/* ── Chat messages ─────────────────────────────────────── */
.chat-message {{
    padding: 0 0 1 0;
    height: auto;
  max-width: 80;
    text-wrap: wrap;
}}

/* ── User messages ─────────────────────────────────────── */
.chat-user {{
    color: {user_msg};
    padding: 0 0 1 0;
    background: {chat_user_bg};
    border-left: tall {chat_user_border};
}}

.chat-user-prefix {{
    text-style: bold;
    color: {user_msg};
    background: transparent;
}}

.chat-user-content {{
    color: {user_msg};
    background: transparent;
    padding: 0 0 0 1;
}}

/* ── Assistant messages ────────────────────────────────── */
.chat-assistant {{
    color: {fg};
    padding: 0 0 1 0;
    border-left: tall {chat_asst_border};
    margin: 0 0 0 1;
    padding-left: 1;
    background: {chat_asst_bg};
    text-wrap: wrap;
}}

.chat-assistant-prefix {{
    text-style: bold;
    color: {assistant_msg};
    background: transparent;
}}

/* ── Tool messages ─────────────────────────────────────── */
.chat-tool-call {{
    color: {fg};
    padding: 0 0 0 2;
    height: auto;
    border-left: tall {tool_border};
    margin: 0 0 0 1;
    text-wrap: wrap;
}}

.chat-tool-call:hover {{
    border-left: tall {tool_border_hover};
}}

.tool-running {{
    text-style: blink;
    color: {accent};
}}

.tool-ok {{
    color: {tool_ok};
}}

.tool-err {{
    color: {tool_err};
}}

.tool-group {{
    color: {status};
    text-style: italic;
}}

.chat-tool-result {{
    color: {fg};
    padding: 0 0 0 2;
    height: auto;
    margin: 0 0 0 1;
    text-wrap: wrap;
}}

.chat-tool-result.tool-ok {{
    border-left: tall {tool_ok};
}}

.chat-tool-result.tool-err {{
    border-left: tall {tool_err};
}}

/* ── Typing indicator ──────────────────────────────────── */
.chat-typing {{
    color: {status};
    padding: 0 0 0 1;
    height: 1;
}}

/* ── Error messages ────────────────────────────────────── */
.chat-error {{
    color: {err};
    padding: 0 0 1 0;
    border-left: tall {err};
    margin: 0 0 0 1;
    padding-left: 1;
    text-wrap: wrap;
}}

/* ── Status messages ───────────────────────────────────── */
.chat-status {{
    color: {status};
    padding: 0 0 0 1;
}}

/* ── Welcome card ──────────────────────────────────────── */
.chat-welcome {{
    padding: 1 2;
    margin: 0 0 1 0;
    border: solid {border};
    background: {surface};
}}

.chat-welcome-title {{
    text-style: bold;
    color: {accent};
    background: transparent;
}}

.chat-welcome-detail {{
    color: {status};
    background: transparent;
}}

/* ── Task complete banner ──────────────────────────────── */
.chat-task-done {{
    color: {tool_ok};
    text-style: bold;
    padding: 0 0 0 1;
}}

.chat-task-cancelled {{
    color: {tool_border};
    text-style: bold;
    padding: 0 0 0 1;
}}

.chat-task-maxiter {{
    color: {err};
    text-style: bold;
    padding: 0 0 0 1;
}}

/* ── Permission dialog ─────────────────────────────────── */
#permission-dialog {{
    layer: overlay;
    dock: bottom;
    height: auto;
    max-height: 20;
    margin: 0 2;
    padding: 1 2;
    border: double {perm_border};
    background: {surface};
    display: none;
}}

.permission-title {{
    text-style: bold;
    color: {perm_border};
    padding: 0 0 1 0;
}}

.permission-detail {{
    color: {fg};
    padding: 0 0 0 1;
}}

.permission-buttons {{
    layout: horizontal;
    height: 3;
    padding: 1 0;
}}

.permission-btn {{
    margin: 0 1;
    min-width: 12;
}}

.permission-btn:focus {{
    border: solid {border_focus};
}}

/* ── Status bar child elements ──────────────────────────── */
#status-model, #status-cost, #status-tokens, #status-state, #status-perm {{
    background: transparent;
}}

.status-sep {{
    color: {border};
}}

/* ── Status indicator colours ──────────────────────────── */
.status-idle {{
    color: {status};
}}

.status-thinking {{
    color: {accent};
}}

.status-error {{
    color: {err};
}}

.status-active {{
    color: {tool_ok};
}}

/* ── Scrollbar ─────────────────────────────────────────── */
#chat {{
    scrollbar-color: {sb_thumb} {sb_track};
}}

/* ── Help bar (bottom) ─────────────────────────────────── */
#help-bar {{
    dock: bottom;
    height: 1;
    background: {surface};
    color: {muted};
    text-wrap: wrap;
}}

#help-bar Static {{
    background: transparent;
    color: {muted};
}}

/* ── Diff widget ───────────────────────────────────────── */
DiffWidget {{
    height: auto;
    max-height: 20;
    margin: 0 0 1 0;
    border: solid {border};
    background: {surface};
    text-wrap: wrap;
}}

.diff-header {{
    text-style: bold;
    color: {fg};
    padding: 0 1;
    background: {surface};
}}

.diff-line {{
    padding: 0 1;
    height: auto;
    text-wrap: wrap;
}}

.diff-add {{
    color: {tool_ok};
    background: {diff_add_bg};
}}

.diff-del {{
    color: {err};
    background: {diff_del_bg};
}}

.diff-ctx {{
    color: {diff_ctx_fg};
}}

.diff-hunk {{
    color: {assistant_msg};
    text-style: bold;
}}

/* ── Spinner ───────────────────────────────────────────── */
Spinner {{
    width: auto;
    height: 1;
    background: transparent;
}}

.spinner-text {{
    background: transparent;
}}

.spinner-idle {{
    color: {status};
}}

.spinner-thinking {{
    color: {accent};
}}

.spinner-requesting {{
    color: {accent};
}}

.spinner-responding {{
    color: {assistant_msg};
}}

.spinner-tool-use {{
    color: {tool_border};
}}

.spinner-stalled {{
    color: {err};
}}

/* ── Focus mode (compact display) ──────────────────────── */
.focus-mode #chat {{
    padding: 0 1;
}}

.focus-mode .chat-tool-call {{
    padding: 0 0 0 2;
    height: 1;
}}

.focus-mode .chat-tool-result {{
    display: none;
}}

.focus-mode .chat-tool-call.tool-group {{
    display: none;
}}

.focus-mode .chat-status {{
    display: none;
}}
"""


# Legacy alias so existing ``from coding_agent.tui.theme import TUI_CSS``
# continues to work.  It uses the default (dark) theme.
TUI_CSS: str = build_css()
