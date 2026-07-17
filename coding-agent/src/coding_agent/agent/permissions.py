"""Permission system for tool execution."""

from __future__ import annotations

from enum import Enum

from coding_agent.logging import logger


class Permission(Enum):
    """Permission levels for tool operations."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DANGEROUS = "dangerous"


class TrustLevel(Enum):
    """Trust levels that determine which operations are auto-allowed."""

    READONLY = "readonly"
    STANDARD = "standard"
    FULL = "full"
    UNSAFE = "unsafe"


class PermissionMode(Enum):
    """Permission modes controlling agent autonomy."""

    DEFAULT = "default"             # >  Ask for all non-read tools
    ACCEPT_EDITS = "acceptEdits"    # >> Auto-allow file edits in workspace
    PLAN = "plan"                   # ?  Pause after every tool call
    BYPASS = "bypassPermissions"    # !  Skip all permission checks


_TRUST_TO_MAX_PERMISSION: dict[TrustLevel, Permission] = {
    TrustLevel.READONLY: Permission.READ,
    TrustLevel.STANDARD: Permission.WRITE,
    TrustLevel.FULL: Permission.EXECUTE,
    TrustLevel.UNSAFE: Permission.DANGEROUS,
}

_PERMISSION_RANK: dict[Permission, int] = {
    Permission.READ: 0,
    Permission.WRITE: 1,
    Permission.EXECUTE: 2,
    Permission.DANGEROUS: 3,
}

# Tools auto-allowed in acceptEdits mode (file edits within workspace)
_ACCEPT_EDITS_TOOLS: frozenset[str] = frozenset({
    "write_file", "edit_file", "multi_edit", "apply_patch",
})


def permission_from_str(value: str) -> Permission:
    """Convert a string to a Permission enum value."""
    try:
        return Permission(value)
    except ValueError:
        return Permission.READ


class PermissionManager:
    """Decides whether a tool call needs user confirmation.

    Usage::

        pm = PermissionManager(level=Permission.WRITE)

        # For each tool call:
        if pm.check(tool_name, tool_permission_level):
            # Auto-allowed
            result = await execute_tool(tool_name, args)
        else:
            # Needs user confirmation
            approved = await ask_user(tool_name, args)
            if approved:
                pm.approve_tool(tool_name)
                result = await execute_tool(tool_name, args)
    """

    def __init__(self, level: Permission = Permission.WRITE) -> None:
        self.level = level
        self._approved_writes: set[str] = set()
        self._mode: PermissionMode = PermissionMode.DEFAULT
        self._workspace: str | None = None

    @property
    def mode(self) -> PermissionMode:
        """Current permission mode."""
        return self._mode

    def set_mode(
        self, mode: PermissionMode, workspace: str | None = None
    ) -> str | None:
        """Switch permission mode.

        Returns a warning message for BYPASS mode, or ``None``.
        """
        if workspace is not None:
            self._workspace = workspace

        if mode == PermissionMode.BYPASS and self._mode != PermissionMode.BYPASS:
            self._mode = mode
            return (
                "All permission checks are disabled. "
                "The agent can modify any file and run any command."
            )

        self._mode = mode
        return None

    def should_pause_after_tool(self) -> bool:
        """Returns True if plan mode is active (pause after every tool call)."""
        return self._mode == PermissionMode.PLAN

    def check(self, tool_name: str, permission_level: str) -> bool:
        """Check if a tool execution is auto-allowed.

        Returns ``True`` if the tool can run without user confirmation,
        ``False`` if user approval is required.
        """
        required = permission_from_str(permission_level)

        if required == Permission.READ:
            return True

        # Bypass mode: skip all permission checks
        if self._mode == PermissionMode.BYPASS:
            return True

        # acceptEdits mode: auto-allow file edits
        if self._mode == PermissionMode.ACCEPT_EDITS:
            if (
                required == Permission.WRITE
                and tool_name in _ACCEPT_EDITS_TOOLS
            ):
                return True

        if required == Permission.DANGEROUS:
            return False

        if required == Permission.WRITE:
            return tool_name in self._approved_writes

        if required == Permission.EXECUTE:
            return False

        return False

    def approve_tool(self, tool_name: str) -> None:
        """Mark a write tool as approved for this session."""
        self._approved_writes.add(tool_name)
        logger.debug("permission_approved", tool=tool_name)

    def reset(self) -> None:
        """Reset all approvals (e.g. for a new session)."""
        count = len(self._approved_writes)
        self._approved_writes.clear()
        if count:
            logger.debug("permission_approvals_reset", count=count)

    @classmethod
    def from_trust_level(cls, trust: TrustLevel) -> PermissionManager:
        """Create a PermissionManager from a trust level preset."""
        return cls(level=_TRUST_TO_MAX_PERMISSION[trust])
