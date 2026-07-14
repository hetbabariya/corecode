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

/* ── Header ────────────────────────────────────────────── */
#header {{
    dock: top;
    height: 1;
    background: {surface};
    color: {fg};
    border-bottom: solid {border};
}}

/* ── Chat area ─────────────────────────────────────────── */
#chat {{
    height: 1fr;
    overflow-y: auto;
    padding: 0 1;
    scrollbar-color: {sb_thumb} {sb_track};
}}

/* ── Sidebar ───────────────────────────────────────────── */
#sidebar {{
    height: 1fr;
    padding: 1;
    border-left: solid {accent};
    overflow-y: auto;
    background: {surface};
}}

/* ── Input area ────────────────────────────────────────── */
#input-container {{
    dock: bottom;
    height: auto;
    min-height: 3;
    max-height: 12;
    border-top: solid {accent};
    padding: 0 1;
    background: {bg};
}}

#user-input {{
    height: auto;
    min-height: 3;
    max-height: 10;
    width: 100%;
}}

/* ── Footer ────────────────────────────────────────────── */
#footer {{
    dock: bottom;
    height: 1;
    background: {surface};
    color: {muted};
    border-top: solid {border};
}}

/* ── Chat messages ─────────────────────────────────────── */
.chat-message {{
    height: auto;
    padding: 0 0 1 0;
}}

.chat-user {{
    color: {user_msg};
    padding: 0 0 1 0;
}}

.chat-assistant {{
    color: {assistant_msg};
    padding: 0 0 1 0;
}}

.chat-tool {{
    color: {muted};
    padding: 0 0 0 2;
    height: auto;
}}

.chat-error {{
    color: {err};
    padding: 0 0 1 0;
}}

/* ── Sidebar sections ──────────────────────────────────── */
.sidebar-title {{
    text-style: bold;
    color: {accent};
    padding: 0 0 1 0;
}}

.sidebar-label {{
    color: {muted};
}}

.sidebar-value {{
    color: {fg};
}}

.sidebar-divider {{
    height: 1;
    margin: 0 0 1 0;
    color: {border};
}}

/* ── Permission dialog ─────────────────────────────────── */
#permission-dialog {{
    layer: overlay;
    dock: bottom;
    height: auto;
    max-height: 20;
    margin: 0 2;
    padding: 1 2;
    border: solid {perm_border};
    background: {surface};
}}

.permission-title {{
    text-style: bold;
    color: {perm_border};
    padding: 0 0 1 0;
}}

.permission-detail {{
    color: {fg};
    padding: 0 0 1 0;
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

.permission-approve {{
    background: {tool_ok};
    color: {bg};
}}

.permission-deny {{
    background: {err};
    color: {bg};
}}

.permission-always {{
    background: {perm_border};
    color: {bg};
}}

/* ── Status indicators ─────────────────────────────────── */
.status-active {{
    color: {tool_ok};
}}

.status-idle {{
    color: {muted};
}}

.status-error {{
    color: {err};
}}

/* ── Code blocks in chat ───────────────────────────────── */
.code-block {{
    background: {surface};
    padding: 1 2;
    margin: 0 0 1 0;
    border: solid {border};
}}

/* ── Spinner ───────────────────────────────────────────── */
.spinner {{
    color: {accent};
}}

.spinner-idle {{
    color: {muted};
}}

.spinner-thinking {{
    color: {accent};
}}

.spinner-requesting {{
    color: {tool_ok};
}}

.spinner-responding {{
    color: {assistant_msg};
}}

.spinner-tool_use {{
    color: {tool_border};
}}

.spinner-stalled {{
    color: {err};
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

/* ── Help bar (bottom) ─────────────────────────────────── */
#help-bar {{
    dock: bottom;
    height: 1;
    background: {bg_subtle};
    color: {muted};
    padding: 0 1;
    content: "Enter send | Shift+Enter newline | Ctrl+D debug";
}}

/* ── Diff widget ───────────────────────────────────────── */
.diff-header {{
    text-style: bold;
    color: {accent};
    padding: 0 0 1 0;
}}

.diff-line {{
    padding: 0 0 0 2;
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
    color: {muted};
    text-style: italic;
}}

/* ── Tool call messages ────────────────────────────────── */
.tool-call-message {{
    color: {tool_border};
    border-left: heavy {tool_border};
    padding: 0 0 0 1;
}}

.tool-result-message {{
    color: {tool_ok};
    border-left: heavy {tool_ok};
    padding: 0 0 0 1;
}}

.tool-result-error {{
    color: {err};
    border-left: heavy {err};
    padding: 0 0 0 1;
}}

/* ── Task banners ──────────────────────────────────────── */
.task-complete {{
    color: {tool_ok};
    text-style: bold;
    padding: 1 0;
}}

.task-cancelled {{
    color: {err};
    text-style: bold;
    padding: 1 0;
}}

.task-max-iter {{
    color: {tool_border};
    text-style: bold;
    padding: 1 0;
}}

/* ── Typing indicator ──────────────────────────────────── */
.typing-indicator {{
    color: {muted};
    padding: 0 0 0 2;
}}

/* ── Welcome card ──────────────────────────────────────── */
.welcome-card {{
    color: {accent};
    text-style: bold;
    padding: 1 2;
    margin: 0 0 1 0;
    border: solid {accent};
    background: {surface};
}}

/* ── Debug / Log viewer panel ──────────────────────────── */
#debug-panel {{
    height: 1fr;
    padding: 1;
    border-left: solid {warning_bdr};
    overflow-y: auto;
}}

#debug-panel .log-viewer-title {{
    text-style: bold;
    color: {warning_bdr};
    padding: 0 0 1 0;
}}

#log-viewer {{
    height: 1fr;
    overflow-y: auto;
}}
"""
