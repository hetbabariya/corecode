"""Slash command system for the Coding Agent.

Provides a registry-based command dispatch layer that sits between the
REPL input handler and the agent loop.  Commands are parsed from input
starting with ``/`` and dispatched to registered handlers.

Built-in commands live in ``coding_agent.commands.builtin``.  Custom
commands can be loaded from ``.coding-agent/commands/*.md`` files.
"""

from __future__ import annotations

from coding_agent.commands.builtin import get_builtin_commands
from coding_agent.commands.registry import CommandContext, CommandRegistry
from coding_agent.commands.types import Command

_registry: CommandRegistry | None = None


def get_registry() -> CommandRegistry:
    """Return (and lazily initialise) the global command registry."""
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
        _registry.register_all(get_builtin_commands())
    return _registry


def reset_registry() -> None:
    """Reset the global registry (useful for tests)."""
    global _registry
    _registry = None


__all__ = [
    "Command",
    "CommandContext",
    "CommandRegistry",
    "get_builtin_commands",
    "get_registry",
    "reset_registry",
]
