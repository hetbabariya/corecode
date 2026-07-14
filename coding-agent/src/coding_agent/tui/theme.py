"""Textual CSS theme for the coding agent TUI."""

TUI_CSS = """\
/* ── Screen layout ── */
Screen {
    layout: grid;
    grid-size: 2;
    grid-columns: 1fr 30;
    grid-rows: 1fr auto;
    layers: default overlay;
}

/* ── Header ── */
#header {
    column-span: 2;
    height: 1;
    dock: top;
}

/* ── Chat area (main panel) ── */
#chat {
    height: 1fr;
    overflow-y: auto;
    padding: 0 1;
}

/* ── Sidebar ── */
#sidebar {
    height: 1fr;
    padding: 1;
    border-left: solid $primary;
    overflow-y: auto;
}

/* ── Input area ── */
#input-container {
    dock: bottom;
    height: auto;
    min-height: 3;
    max-height: 12;
    border-top: solid $primary;
    padding: 0 1;
}

#user-input {
    height: auto;
    min-height: 3;
    max-height: 10;
    width: 100%;
}

/* ── Footer ── */
#footer {
    column-span: 2;
    height: 1;
    dock: bottom;
}

/* ── Chat messages ── */
.chat-message {
    padding: 0 0 1 0;
    height: auto;
}

.chat-user {
    color: $text;
    padding: 0 0 1 0;
}

.chat-assistant {
    color: $text;
    padding: 0 0 1 0;
}

.chat-tool {
    color: $text-muted;
    padding: 0 0 0 2;
    height: auto;
}

.chat-error {
    color: $error;
    padding: 0 0 1 0;
}

/* ── Sidebar sections ── */
.sidebar-title {
    text-style: bold;
    color: $primary;
    padding: 0 0 1 0;
}

.sidebar-label {
    color: $text-muted;
}

.sidebar-value {
    color: $text;
}

.sidebar-divider {
    height: 1;
    margin: 0 0 1 0;
}

/* ── Permission dialog ── */
#permission-dialog {
    layer: overlay;
    dock: bottom;
    height: auto;
    max-height: 20;
    margin: 0 2;
    padding: 1 2;
    border: solid $warning;
    background: $surface;
}

.permission-title {
    text-style: bold;
    color: $warning;
    padding: 0 0 1 0;
}

.permission-detail {
    color: $text;
    padding: 0 0 1 0;
}

.permission-buttons {
    layout: horizontal;
    height: 3;
    padding: 1 0;
}

.permission-btn {
    margin: 0 1;
    min-width: 12;
}

.permission-approve {
    background: $success;
    color: $text;
}

.permission-deny {
    background: $error;
    color: $text;
}

.permission-always {
    background: $warning;
    color: $text;
}

/* ── Status indicators ── */
.status-active {
    color: $success;
}

.status-idle {
    color: $text-muted;
}

.status-error {
    color: $error;
}

/* ── Code blocks in chat ── */
.code-block {
    background: $surface;
    padding: 1 2;
    margin: 0 0 1 0;
    border: solid $primary;
}

/* ── Debug / Log viewer panel ── */
#debug-panel {
    height: 1fr;
    padding: 1;
    border-left: solid $warning;
    overflow-y: auto;
}

#debug-panel .log-viewer-title {
    text-style: bold;
    color: $warning;
    padding: 0 0 1 0;
}

#log-viewer {
    height: 1fr;
    overflow-y: auto;
}

"""
