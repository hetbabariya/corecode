"""Types for the slash command system."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coding_agent.commands.registry import CommandContext

CommandHandler = Callable[["CommandContext", str], Awaitable[str | None]]


@dataclass
class Command:
    """A single slash command."""

    name: str
    description: str
    handler: CommandHandler
    usage: str = ""
    hidden: bool = False
    aliases: list[str] = field(default_factory=list)

    def matches(self, input_name: str) -> bool:
        """Check if *input_name* matches this command or any alias."""
        normalised = input_name.lower().lstrip("/")
        return normalised == self.name or normalised in self.aliases
