"""User input widget — multi-line text input with submit handling and history."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.message import Message
from textual.widgets import Static, TextArea


class SubmitTextArea(TextArea):
    """TextArea that submits on Enter, newlines on Shift+Enter."""

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
                self.clear()

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text


class UserInput(Container):
    """Multi-line text input with prompt character and history navigation.

    Layout::

        ┌─ input-box ─────────────────────────────────┐
        │ ❯ │ Type your message...                    │
        └─────────────────────────────────────────────┘

    Enter → submit.  Shift+Enter → newline.
    Up/Down → navigate input history.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_index: int = -1

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-box"):
            yield Static("❯", id="input-prompt")
            yield SubmitTextArea(
                id="user-input",
                placeholder="Type a message…",
            )

    @property
    def text_area(self) -> SubmitTextArea:
        return self.query_one("#user-input", SubmitTextArea)

    def get_text(self) -> str:
        """Get the current input text."""
        return self.text_area.text.strip()

    def clear(self) -> None:
        """Clear the input area."""
        self.text_area.clear()

    def set_focus(self) -> None:
        """Focus the text area."""
        self.text_area.focus()

    # ── History ────────────────────────────────────────────

    def add_to_history(self, text: str) -> None:
        """Append text to the session history."""
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_index = -1

    def _history_up(self) -> None:
        """Navigate to the previous history entry."""
        if not self._history:
            return
        if self._history_index == -1:
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        self._load_history_entry()

    def _history_down(self) -> None:
        """Navigate to the next history entry."""
        if not self._history:
            return
        if self._history_index == -1:
            return
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self._load_history_entry()
        else:
            self._history_index = -1
            self.text_area.clear()

    def _load_history_entry(self) -> None:
        """Load the current history entry into the text area."""
        if 0 <= self._history_index < len(self._history):
            self.text_area.text = self._history[self._history_index]
            self.text_area.cursor_location = self.text_area.document.end

    @property
    def last_user_message(self) -> str:
        """Return the last user message from history, or empty string."""
        return self._history[-1] if self._history else ""

    # ── Message handling ───────────────────────────────────

    def on_submit_text_area_submitted(self, message: SubmitTextArea.Submitted) -> None:
        """Handle submission from the text area."""
        self.add_to_history(message.text)
        self.post_message(self.Submitted(message.text))

    def on_key(self, event: Key) -> None:
        """Handle key events for history navigation."""
        if event.key == "up" and not self.text_area.selected_text:
            if self.text_area.cursor_location.row == 0:
                event.prevent_default()
                self._history_up()
        elif event.key == "down" and not self.text_area.selected_text:
            if self.text_area.cursor_location.row >= self.text_area.document.line_count - 1:
                event.prevent_default()
                self._history_down()

    class Submitted(Message):
        """Posted when the user submits input."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text
