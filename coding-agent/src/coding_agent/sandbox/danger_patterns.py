"""Dangerous command detection — blocks destructive shell commands."""

from __future__ import annotations

import re
from typing import NamedTuple


class DangerCheckResult(NamedTuple):
    """Result of a dangerous command check."""

    is_dangerous: bool
    reason: str


# ---------------------------------------------------------------------------
# Pattern definitions — (compiled_regex, human_reason)
# ---------------------------------------------------------------------------

_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = []


def _add(pattern: str, reason: str) -> None:
    _DANGEROUS_PATTERNS.append(
        (re.compile(pattern, re.IGNORECASE | re.VERBOSE), reason)
    )


# -- File deletion ------------------------------------------------------------

_add(
    r"""
    \brm\b
    .{0,20}           # optional flags/args
    -{1,3}r           # -r, -R, -rr, -RR, etc.
    .{0,10}           # optional spacing
    -{0,3}f           # optional -f (may come before or after -r)
    .{0,20}
    /\s*$             # ends with /
    """,
    "Recursive deletion of root filesystem",
)

_add(
    r"""
    \brm\b
    .{0,20}
    -{1,3}f
    .{0,10}
    -{0,3}r
    .{0,20}
    /\s*$
    """,
    "Recursive deletion of root filesystem",
)

_add(
    r"""
    \brm\b
    .{0,30}
    ~/?\s*$
    """,
    "Recursive deletion of home directory",
)

_add(
    r"""
    \brm\b
    .{0,20}
    -{1,3}r
    .{0,10}
    -{0,3}f
    .{0,20}
    /\*\s*$
    """,
    "Recursive deletion of root contents",
)

# -- Git force push -----------------------------------------------------------

_add(
    r"""
    \bgit\b
    .{0,10}
    push\b
    .{0,30}
    --force
    """,
    "Git force push",
)

_add(
    r"""
    \bgit\b
    .{0,10}
    push\b
    .{0,30}
    -f\b
    """,
    "Git force push",
)

_add(
    r"""
    \bgit\b
    .{0,10}
    push\b
    .{0,30}
    --force-with-lease
    """,
    "Git force push with lease",
)

# -- SQL destructive ----------------------------------------------------------

_add(
    r"""
    \bDROP\s+TABLE\b
    """,
    "SQL DROP TABLE",
)

_add(
    r"""
    \bDELETE\s+FROM\b
    """,
    "SQL DELETE FROM",
)

_add(
    r"""
    \bTRUNCATE\s+TABLE\b
    """,
    "SQL TRUNCATE TABLE",
)

_add(
    r"""
    \bDROP\s+DATABASE\b
    """,
    "SQL DROP DATABASE",
)

# -- Disk formatting ----------------------------------------------------------

_add(
    r"""
    \bmkfs\b
    """,
    "Filesystem format (mkfs)",
)

_add(
    r"""
    \bdd\b
    .{0,20}
    if=
    """,
    "Disk write (dd if=)",
)

_add(
    r"""
    \bdd\b
    .{0,20}
    of=/dev/
    """,
    "Disk write (dd of=/dev/)",
)

_add(
    r"""
    \bfdisk\b
    .{0,20}
    /dev/
    """,
    "Disk partitioning (fdisk)",
)

_add(
    r"""
    \bparted\b
    .{0,20}
    /dev/
    """,
    "Disk partitioning (parted)",
)

# -- System control -----------------------------------------------------------

_add(
    r"""
    \bshutdown\b
    """,
    "System shutdown",
)

_add(
    r"""
    \breboot\b
    """,
    "System reboot",
)

_add(
    r"""
    \binit\s+[06]\b
    """,
    "System runlevel change (halt/reboot)",
)

_add(
    r"""
    \bsystemctl\s+(stop|restart|disable)\s+
    """,
    "System service control",
)

# -- Fork bomb ----------------------------------------------------------------

_add(
    r":\(\)\s*\{",
    "Fork bomb",
)

_add(
    r":\|\:\s*&",
    "Fork bomb",
)

# -- Remote code execution ----------------------------------------------------

_add(
    r"""
    \bcurl\b
    .{0,50}
    \|\s*(ba)?sh\b
    """,
    "Remote code execution (curl pipe shell)",
)

_add(
    r"""
    \bwget\b
    .{0,50}
    \|\s*(ba)?sh\b
    """,
    "Remote code execution (wget pipe shell)",
)

_add(
    r"""
    \bcurl\b
    .{0,50}
    \|[^|]*\bexec\b
    """,
    "Remote code execution (curl pipe exec)",
)

# -- Permissions ---------------------------------------------------------------

_add(
    r"""
    \bchmod\b
    .{0,10}
    777\b
    """,
    "World-writable permissions (chmod 777)",
)

_add(
    r"""
    \bchmod\b
    .{0,10}
    -R\b
    .{0,10}
    777\b
    """,
    "Recursive world-writable permissions",
)

_add(
    r"""
    \bchown\b
    .{0,10}
    root\b
    """,
    "Ownership change to root",
)

# -- Device destruction --------------------------------------------------------

_add(
    r"""
    >/dev/sd[a-z]\b
    """,
    "Direct disk write",
)

_add(
    r"""
    \bcat\b
    .{0,20}
    /dev/zero
    .{0,20}
    >/dev/sd
    """,
    "Disk zeroing",
)

# -- Network destruction -------------------------------------------------------

_add(
    r"""
    \biptables\b
    .{0,20}
    -F\b
    """,
    "Flush iptables rules (network lockout risk)",
)

_add(
    r"""
    \bufw\b
    .{0,20}
    --reset
    """,
    "Reset ufw firewall",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalize(command: str) -> str:
    """Normalize a command string for pattern matching.

    - Lowercase
    - Collapse multiple whitespace to single space
    - Strip leading/trailing whitespace
    """
    return re.sub(r"\s+", " ", command.lower()).strip()


def check_dangerous_command(command: str) -> DangerCheckResult:
    """Check if a shell command is potentially dangerous.

    Parameters
    ----------
    command:
        The raw shell command string.

    Returns
    -------
    DangerCheckResult
        ``is_dangerous`` is True if the command matches a dangerous pattern.
        ``reason`` describes why it was blocked.
    """
    normalized = _normalize(command)

    for pattern, reason in _DANGEROUS_PATTERNS:
        if pattern.search(normalized):
            return DangerCheckResult(is_dangerous=True, reason=reason)

    return DangerCheckResult(is_dangerous=False, reason="")
