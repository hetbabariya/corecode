"""TUI widgets package."""

from coding_agent.tui.widgets.chat import ChatDisplay
from coding_agent.tui.widgets.diff import DiffWidget
from coding_agent.tui.widgets.help_bar import HelpBar
from coding_agent.tui.widgets.input import UserInput
from coding_agent.tui.widgets.permission import PermissionDialog
from coding_agent.tui.widgets.spinner import Spinner, SpinnerMode
from coding_agent.tui.widgets.status_bar import StatusBar

__all__ = [
    "ChatDisplay",
    "DiffWidget",
    "HelpBar",
    "PermissionDialog",
    "Spinner",
    "SpinnerMode",
    "StatusBar",
    "UserInput",
]
