"""User input widget — multi-line text input with submit handling."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.message import Message
from textual.widgets import TextArea


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
    """Multi-line text input container.

    Enter or Ctrl+Enter → submit.
    Shift+Enter → newline.
    """

    def compose(self) -> ComposeResult:
        yield SubmitTextArea(
            id="user-input",
            placeholder="Type your message... (Enter to submit, Shift+Enter for newline)",
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

    def on_submit_text_area_submitted(self, message: SubmitTextArea.Submitted) -> None:
        """Handle submission from the text area."""
        self.post_message(self.Submitted(message.text))

    def on_key(self, event: Key) -> None:
        """Handle key events."""
        if event.key == "escape":
            event.prevent_default()
            self.text_area.focus()

    class Submitted(Message):
        """Posted when the user submits input."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text
