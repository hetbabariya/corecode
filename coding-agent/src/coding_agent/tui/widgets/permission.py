"""Permission dialog — modal dialog for tool execution approval."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static


class PermissionDialog(Widget):
    """Permission request dialog with Allow / Always / Deny buttons.

    Appears at the bottom of the screen when a tool needs permission.
    Includes a 200 ms anti-misclick delay before accepting input.
    Fully keyboard-operable: Tab cycles buttons, Enter confirms, Escape denies.
    """

    BINDINGS = [
        Binding("tab", "next_button", show=False),
        Binding("shift+tab", "prev_button", show=False),
        Binding("enter", "confirm", show=False),
        Binding("escape", "deny", show=False),
    ]

    _button_ids = ["btn-approve", "btn-always", "btn-deny"]
    _focused_btn_index = 0

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._can_respond = False
        self.display = False

    def compose(self) -> ComposeResult:
        yield Static("Permission Required", classes="permission-title")
        yield Static("", id="permission-tool-name", classes="permission-detail")
        yield Static("", id="permission-args", classes="permission-detail")
        yield Static("", id="permission-level", classes="permission-detail")
        with Horizontal(classes="permission-buttons"):
            yield Button(
                "Allow",
                variant="success",
                id="btn-approve",
                classes="permission-btn",
            )
            yield Button(
                "Always",
                variant="warning",
                id="btn-always",
                classes="permission-btn",
            )
            yield Button(
                "Deny",
                variant="error",
                id="btn-deny",
                classes="permission-btn",
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

        # Anti-misclick: disable buttons for 200 ms
        self._can_respond = False
        self.display = True
        self._focused_btn_index = 0
        self.set_timer(0.2, callback=self._enable_response)

    def _enable_response(self) -> None:
        self._can_respond = True

    def hide(self) -> None:
        """Hide the permission dialog."""
        self.display = False
        self._can_respond = False

    def _set_focus_to_button(self, btn_id: str) -> None:
        """Move focus to a specific button."""
        try:
            btn = self.query_one(f"#{btn_id}", Button)
            btn.focus()
        except Exception:
            pass

    def action_next_button(self) -> None:
        """Cycle focus to the next button."""
        if not self._can_respond:
            return
        self._focused_btn_index = (self._focused_btn_index + 1) % len(self._button_ids)
        self._set_focus_to_button(self._button_ids[self._focused_btn_index])

    def action_prev_button(self) -> None:
        """Cycle focus to the previous button."""
        if not self._can_respond:
            return
        self._focused_btn_index = (self._focused_btn_index - 1) % len(self._button_ids)
        self._set_focus_to_button(self._button_ids[self._focused_btn_index])

    def action_confirm(self) -> None:
        """Confirm the currently focused button."""
        if not self._can_respond:
            return
        btn_id = self._button_ids[self._focused_btn_index]
        if btn_id == "btn-approve":
            self.post_message(self.Response(approved=False))
        elif btn_id == "btn-always":
            self.post_message(self.Response(approved=True))
        elif btn_id == "btn-deny":
            self.post_message(self.Response(approved=False, denied=True))
        self.hide()

    def action_deny(self) -> None:
        """Deny via Escape key."""
        if not self._can_respond:
            return
        self.post_message(self.Response(approved=False, denied=True))
        self.hide()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if not self._can_respond:
            return

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
