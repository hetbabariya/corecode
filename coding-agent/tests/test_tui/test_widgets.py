"""Tests for TUI widgets."""

from __future__ import annotations

from coding_agent.tui.widgets.chat import (
    ChatDisplay,
    ChatMessage,
    ErrorMessage,
    ToolCallMessage,
)
from coding_agent.tui.widgets.input import UserInput
from coding_agent.tui.widgets.permission import PermissionDialog

# -- Chat widget tests --


class TestChatMessage:
    def test_init(self):
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert "chat-user" in msg.classes

    def test_render(self):
        msg = ChatMessage(role="assistant", content="**bold** text")
        rendered = msg.render()
        assert "bold" in str(rendered)

    def test_assistant_class(self):
        msg = ChatMessage(role="assistant", content="test")
        assert "chat-assistant" in msg.classes


class TestToolCallMessage:
    def test_init_with_detail(self):
        msg = ToolCallMessage(tool_name="read_file", detail="pyproject.toml")
        assert msg.tool_name == "read_file"
        assert msg.detail == "pyproject.toml"

    def test_render_with_detail(self):
        msg = ToolCallMessage(tool_name="edit_file", detail="src/main.py")
        rendered = str(msg.render())
        assert "edit_file" in rendered
        assert "src/main.py" in rendered

    def test_render_without_detail(self):
        msg = ToolCallMessage(tool_name="search_content")
        rendered = str(msg.render())
        assert "search_content" in rendered


class TestErrorMessage:
    def test_init(self):
        msg = ErrorMessage(error="File not found")
        assert msg.error_text == "File not found"
        assert "chat-error" in msg.classes

    def test_render(self):
        msg = ErrorMessage(error="Permission denied")
        rendered = str(msg.render())
        assert "Error:" in rendered
        assert "Permission denied" in rendered


class TestChatDisplay:
    def test_compose(self):
        display = ChatDisplay()
        assert display is not None


class TestUserInput:
    def test_compose(self):
        user_input = UserInput()
        assert user_input is not None

    def test_get_text_empty(self):
        user_input = UserInput()
        assert user_input is not None


# -- Permission dialog tests --


class TestPermissionDialog:
    def test_compose(self):
        dialog = PermissionDialog()
        assert dialog is not None

    def test_show_hide(self):
        dialog = PermissionDialog()
        assert hasattr(dialog, "show")
        assert hasattr(dialog, "hide")


# -- Theme CSS tests --


class TestTheme:
    def test_css_is_string(self):
        from coding_agent.tui.theme import TUI_CSS

        assert isinstance(TUI_CSS, str)
        assert len(TUI_CSS) > 100

    def test_css_has_required_selectors(self):
        from coding_agent.tui.theme import TUI_CSS

        assert "#chat" in TUI_CSS
        assert "#input-container" in TUI_CSS
        assert "#permission-dialog" in TUI_CSS
