"""Protected paths — prevents modification of critical files and directories."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import NamedTuple


class ProtectedCheckResult(NamedTuple):
    """Result of a protected path check."""

    is_protected: bool
    reason: str


# ---------------------------------------------------------------------------
# Protected patterns
# ---------------------------------------------------------------------------

# Files that should never be modified
PROTECTED_FILES: set[str] = {
    # Git
    ".gitconfig",
    ".gitignore_global",
    ".gitattributes_global",
    # Shell
    ".bashrc",
    ".bash_profile",
    ".bash_history",
    ".zshrc",
    ".zsh_history",
    ".profile",
    ".login",
    ".logout",
    # Secrets / credentials
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
    ".mcp.json",
    ".claude.json",
    ".cursor",
    # SSH / GPG
    "authorized_keys",
    "id_rsa",
    "id_rsa.pub",
    "id_ed25519",
    "id_ed25519.pub",
    "id_dsa",
    "id_dsa.pub",
    "known_hosts",
    "config",
    # Certificates
    "*.pem",
    "*.key",
    "*.crt",
    "*.p12",
    "*.pfx",
}

# Directories that should never be modified
PROTECTED_DIRS: set[str] = {
    # Version control
    ".git",
    ".svn",
    ".hg",
    # IDEs
    ".vscode",
    ".idea",
    ".claude",
    ".cursor",
    ".vs",
    ".sublime",
    # Dependencies
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pyright",
    # System / credentials
    ".ssh",
    ".gnupg",
    ".gpg",
    ".aws",
    ".azure",
    ".config",
    ".local",
    ".cache",
    # Docker
    ".docker",
}

# Files with extensions that are likely sensitive
PROTECTED_EXTENSIONS: set[str] = {
    ".pem",
    ".key",
    ".crt",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalize_path(path: str) -> PurePosixPath:
    """Normalize a path for comparison.

    - Convert to POSIX path separators
    - Resolve relative components (../, ./)
    - Lowercase for case-insensitive matching
    """
    # Convert backslashes to forward slashes for cross-platform
    normalized = path.replace("\\", "/")

    # Use PurePosixPath to resolve relative components
    p = PurePosixPath(normalized)

    # Resolve ../ and ./
    resolved_parts: list[str] = []
    for part in p.parts:
        if part == "..":
            if resolved_parts:
                resolved_parts.pop()
        elif part == ".":
            continue
        else:
            resolved_parts.append(part.lower())

    return PurePosixPath(*resolved_parts) if resolved_parts else PurePosixPath(".")


def _get_filename(path: PurePosixPath) -> str:
    """Extract filename from path."""
    return path.name


def _get_parent_dirs(path: PurePosixPath) -> list[str]:
    """Get all parent directory names."""
    parts = list(path.parts)
    # Remove the filename (last part) if it's not a directory
    if len(parts) > 1:
        return parts[:-1]
    return []


def is_protected_path(path: str) -> ProtectedCheckResult:
    """Check if a file path is protected from modification.

    Parameters
    ----------
    path:
        The file path to check.

    Returns
    -------
    ProtectedCheckResult
        ``is_protected`` is True if the path should not be modified.
        ``reason`` describes why it is protected.
    """
    normalized = _normalize_path(path)
    filename = _get_filename(normalized)

    # Check exact filename match
    if filename in PROTECTED_FILES:
        return ProtectedCheckResult(
            is_protected=True,
            reason=f"Protected file: {filename}",
        )

    # Check file extension
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in PROTECTED_EXTENSIONS:
        return ProtectedCheckResult(
            is_protected=True,
            reason=f"Protected file type: {suffix}",
        )

    # Check .env.* pattern (any .env variant)
    if filename.startswith(".env"):
        return ProtectedCheckResult(
            is_protected=True,
            reason=f"Protected environment file: {filename}",
        )

    # Check parent directories
    parent_dirs = _get_parent_dirs(normalized)
    for dir_name in parent_dirs:
        if dir_name in PROTECTED_DIRS:
            return ProtectedCheckResult(
                is_protected=True,
                reason=f"Protected directory: {dir_name}",
            )

    return ProtectedCheckResult(is_protected=False, reason="")
