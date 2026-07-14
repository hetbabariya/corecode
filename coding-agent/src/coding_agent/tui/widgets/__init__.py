"""TUI widgets package."""

from coding_agent.tui.widgets.chat import ChatDisplay
from coding_agent.tui.widgets.input import UserInput
from coding_agent.tui.widgets.permission import PermissionDialog
from coding_agent.tui.widgets.sidebar import Sidebar

__all__ = [
    "ChatDisplay",
    "PermissionDialog",
    "Sidebar",
    "UserInput",
]
