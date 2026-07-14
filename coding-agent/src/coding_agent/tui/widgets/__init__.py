"""TUI widgets package."""

from coding_agent.tui.widgets.chat import ChatDisplay
from coding_agent.tui.widgets.diff import DiffWidget
from coding_agent.tui.widgets.help_bar import HelpBar
from coding_agent.tui.widgets.input import UserInput
from coding_agent.tui.widgets.log_viewer import LogViewer
from coding_agent.tui.widgets.permission import PermissionDialog
from coding_agent.tui.widgets.sidebar import Sidebar
from coding_agent.tui.widgets.spinner import Spinner
from coding_agent.tui.widgets.status_bar import StatusBar

__all__ = [
    "ChatDisplay",
    "DiffWidget",
    "HelpBar",
    "LogViewer",
    "PermissionDialog",
    "Sidebar",
    "Spinner",
    "StatusBar",
    "UserInput",
]
