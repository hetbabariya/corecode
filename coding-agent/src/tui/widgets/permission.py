"""Permission dialog — modal dialog for tool execution approval."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static


class PermissionDialog(Widget):
    """Permission request dialog with Approve/Deny/Always buttons.

    Appears at the bottom of the screen when a tool needs permission.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.display = False

    def compose(self) -> ComposeResult:
        yield Static("Permission Required", classes="permission-title")
        yield Static("", id="permission-tool-name", classes="permission-detail")
        yield Static("", id="permission-args", classes="permission-detail")
        yield Static("", id="permission-level", classes="permission-detail")
        with Horizontal(classes="permission-buttons"):
            yield Button(
                "Approve",
                variant="success",
                id="btn-approve",
                classes="permission-btn",
            )
            yield Button(
                "Always Allow",
                variant="warning",
                id="btn-always",
                classes="permission-btn",
            )
            yield Button(
                "Deny", variant="error", id="btn-deny", classes="permission-btn"
            )

    def show(
        self,
        tool_name: str,
        args: dict[str, object] | None = None,
        permission_level: str = "write",
    ) -> None:
        """Show the permission dialog with details."""
        self.query_one("#permission-tool-name", Static).update(f"Tool: {tool_name}")

        args_text = ""
        if args:
            args_str = str(args)
            if len(args_str) > 120:
                args_str = args_str[:117] + "..."
            args_text = args_str
        self.query_one("#permission-args", Static).update(f"Args: {args_text}")

        self.query_one("#permission-level", Static).update(f"Level: {permission_level}")

        self.display = True

    def hide(self) -> None:
        """Hide the permission dialog."""
        self.display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        if button_id == "btn-approve":
            self.post_message(self.Response(approved=False))
        elif button_id == "btn-always":
            self.post_message(self.Response(approved=True))
        elif button_id == "btn-deny":
            self.post_message(self.Response(approved=False, denied=True))
        self.hide()

    class Response(Message):
        """Posted when the user responds to a permission request."""

        def __init__(self, approved: bool = False, denied: bool = False) -> None:
            super().__init__()
            self.approved = approved  # True = always allow
            self.denied = denied
