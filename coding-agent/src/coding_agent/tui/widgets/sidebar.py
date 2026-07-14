"""Sidebar widget — status panel showing model, tokens, cost, and active tools."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class SidebarSection(Static):
    """A titled section in the sidebar."""

    def __init__(self, title: str, **kwargs: str | None) -> None:
        super().__init__(title, **kwargs)  # type: ignore[arg-type]
        self.section_title = title
        self.add_class("sidebar-section")


class SidebarValue(Static):
    """A key-value pair in the sidebar."""

    def __init__(self, label: str, value: str = "", **kwargs: str | None) -> None:
        text = f"{label}: {value}" if value else f"{label}: ---"
        super().__init__(text, **kwargs)  # type: ignore[arg-type]
        self.label = label
        self.value = value

    def set_value(self, value: str) -> None:
        """Update the displayed value."""
        self.value = value
        self.update(
            f"{self.label}: {self.value}" if self.value else f"{self.label}: ---"
        )


class Sidebar(Vertical):
    """Sidebar displaying session status and controls."""

    def compose(self) -> ComposeResult:
        yield SidebarSection("Session", id="sidebar-title-model")
        yield SidebarValue("Model", id="sidebar-model")
        yield SidebarValue("Provider", id="sidebar-provider")
        yield SidebarValue("Workspace", id="sidebar-workspace")
        yield Static("", classes="sidebar-divider")

        yield SidebarSection("Usage", id="sidebar-title-usage")
        yield SidebarValue("Tokens", id="sidebar-tokens")
        yield SidebarValue("Cost", id="sidebar-cost")
        yield Static("", classes="sidebar-divider")

        yield SidebarSection("Tools", id="sidebar-title-tools")
        yield SidebarValue("Calls", id="sidebar-tool-count")
        yield Static("", classes="sidebar-divider")

        yield SidebarSection("Status", id="sidebar-title-status")
        yield SidebarValue("State", id="sidebar-state")

    def set_model(self, model: str) -> None:
        self.query_one("#sidebar-model", SidebarValue).set_value(model)

    def set_provider(self, provider: str) -> None:
        self.query_one("#sidebar-provider", SidebarValue).set_value(provider)

    def set_workspace(self, workspace: str) -> None:
        self.query_one("#sidebar-workspace", SidebarValue).set_value(workspace)

    def set_tokens(self, prompt: int, completion: int, total: int) -> None:
        self.query_one("#sidebar-tokens", SidebarValue).set_value(
            f"{total:,} ({prompt:,}+{completion:,})"
        )

    def set_cost(self, cost: float) -> None:
        self.query_one("#sidebar-cost", SidebarValue).set_value(f"${cost:.4f}")

    def set_tool_count(self, count: int) -> None:
        self.query_one("#sidebar-tool-count", SidebarValue).set_value(str(count))

    def set_state(self, state: str) -> None:
        self.query_one("#sidebar-state", SidebarValue).set_value(state)

    def update_stats(
        self,
        model: str = "",
        provider: str = "",
        workspace: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost: float = 0.0,
        tool_count: int = 0,
        state: str = "idle",
    ) -> None:
        """Update all sidebar values at once."""
        if model:
            self.set_model(model)
        if provider:
            self.set_provider(provider)
        if workspace:
            self.set_workspace(workspace)
        self.set_tokens(prompt_tokens, completion_tokens, total_tokens)
        self.set_cost(cost)
        self.set_tool_count(tool_count)
        self.set_state(state)
