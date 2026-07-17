"""Command registry — maps command names to handlers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coding_agent.commands.types import Command, CommandHandler
from coding_agent.logging import logger


@dataclass
class CommandContext:
    """Read-only context passed to every command handler."""

    agent: Any
    workspace: Path
    repl: Any


class CommandRegistry:
    """Registry that dispatches `/commands` to handler functions."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._order: list[str] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, command: Command) -> None:
        """Register a command (overwrites if name already exists)."""
        if command.name not in self._commands:
            self._order.append(command.name)
        self._commands[command.name] = command

    def register_all(self, commands: list[Command]) -> None:
        """Register multiple commands at once."""
        for cmd in commands:
            self.register(cmd)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> Command | None:
        """Find a command by name or alias."""
        normalised = name.lower().lstrip("/")
        for cmd in self._commands.values():
            if cmd.matches(normalised):
                return cmd
        return None

    def list_commands(self, *, include_hidden: bool = False) -> list[Command]:
        """Return all registered commands in registration order."""
        cmds = [self._commands[n] for n in self._order if n in self._commands]
        if not include_hidden:
            cmds = [c for c in cmds if not c.hidden]
        return cmds

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        raw_input: str,
        ctx: CommandContext,
    ) -> str | None:
        """Parse *raw_input*, dispatch to the matching handler, and return output.

        Returns ``None`` if the command was not recognised (so the REPL can
        forward the input to the agent as a normal message).
        """
        parts = raw_input.split(maxsplit=1)
        name = parts[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        cmd = self.get(name)
        if cmd is None:
            return None

        try:
            result = await cmd.handler(ctx, arg)
            return result
        except Exception as exc:
            logger.error("command_failed", command=name, error=str(exc))
            return f"Error executing {name}: {exc}"

    # ------------------------------------------------------------------
    # Custom commands (loaded from markdown files)
    # ------------------------------------------------------------------

    def load_custom_commands(self, *directories: Path) -> int:
        """Load custom commands from ``.coding-agent/commands/*.md`` files.

        Each file defines a command where:
        - Filename (without .md) = command name
        - First line (if starts with #) = description
        - Remaining content = prompt template (supports $ARGUMENTS)

        Returns the number of commands loaded.
        """
        count = 0
        for directory in directories:
            if not directory.is_dir():
                continue
            for md_file in sorted(directory.glob("*.md")):
                name = md_file.stem
                if name in self._commands:
                    continue
                try:
                    content = md_file.read_text(encoding="utf-8")
                    lines = content.strip().splitlines()
                    description = "Custom command"
                    prompt_template = content.strip()

                    if lines and lines[0].startswith("#"):
                        description = lines[0].lstrip("#").strip()
                        prompt_template = "\n".join(lines[1:]).strip()

                    cmd = Command(
                        name=name,
                        description=description,
                        handler=_make_custom_handler(prompt_template),
                        usage=f"/{name} [args]",
                        hidden=False,
                    )
                    self.register(cmd)
                    count += 1
                    logger.debug("custom_command_loaded", name=name, path=str(md_file))
                except Exception as exc:
                    logger.warning("custom_command_load_failed", path=str(md_file), error=str(exc))

        return count


def _make_custom_handler(template: str) -> CommandHandler:
    """Create a handler that renders a prompt template and returns it."""

    async def handler(ctx: CommandContext, args: str) -> str:
        return template.replace("$ARGUMENTS", args)

    return handler
