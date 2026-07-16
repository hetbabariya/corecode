"""Theme constants and registration for the Coding Agent REPL."""

from __future__ import annotations

from textual.theme import Theme


def create_nord_theme() -> Theme:
    """Create a Nord-inspired dark theme for the Coding Agent."""
    return Theme(
        name="coding-agent",
        primary="#88C0D0",
        secondary="#81A1C1",
        accent="#B48EAD",
        foreground="#ECEFF4",
        background="#2E3440",
        success="#A3BE8C",
        warning="#EBCB8B",
        error="#BF616A",
        surface="#3B4252",
        panel="#434C5E",
        dark=True,
        variables={
            "block-cursor-foreground": "#ECEFF4",
            "block-cursor-background": "#88C0D0",
            "block-cursor-text-style": "none",
            "footer-key-foreground": "#88C0D0",
            "input-selection-background": "#81A1C140",
            "input-cursor-background": "#ECEFF4",
            "input-cursor-foreground": "#2E3440",
            "scrollbar": "#4C566A",
            "scrollbar-hover": "#616E88",
            "scrollbar-active": "#7B88A1",
            "link-color": "#88C0D0",
            "link-style": "underline",
        },
    )


# CSS for the REPL app
REPL_CSS = """
Screen {
    background: $background;
}

#chat-view {
    background: $background;
    padding: 0 1;
}

#input-bar {
    dock: bottom;
    height: 3;
    background: $surface;
    padding: 0 1;
    border-top: tall $panel;
}

#input-bar Input {
    background: $panel;
    color: $foreground;
    border: tall $primary;
    padding: 0 1;
}

#input-bar Input:focus {
    border: tall $primary;
}

#status-bar {
    dock: bottom;
    height: 1;
    background: $panel;
    color: $text-muted;
    padding: 0 1;
}

UserMessage {
    color: $foreground;
    padding: 0 0 0 2;
    margin: 1 0 0 0;
}

AssistantMessage {
    color: $foreground;
    padding: 0 0 0 2;
    margin: 0 0 0 0;
}

ToolCallBlock {
    background: $surface;
    color: $text-muted;
    padding: 0 1;
    margin: 0 0 0 4;
    border: tall $border-blurred;
}

ToolCallBlock.-success {
    border: tall $success;
}

ToolCallBlock.-error {
    border: tall $error;
}

SystemMessage {
    color: $text-muted;
    padding: 0 1;
    margin: 0 0 0 2;
}

SystemMessage.-warning {
    color: $warning;
}

SystemMessage.-error {
    color: $error;
}

SystemMessage.-info {
    color: $text-muted;
}

ThinkingIndicator {
    color: $text-muted;
    padding: 0 1;
    margin: 0 0 0 2;
}

#toolbar {
    dock: bottom;
    height: 1;
    background: $surface;
    color: $text-muted;
    padding: 0 1;
    border-top: tall $panel;
}
"""
