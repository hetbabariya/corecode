"""AGENTS.md hierarchy loader.

Loads project configuration from a 5-scope hierarchy (broadest to narrowest)
and resolves ``@path/to/file.md`` imports with circular-import protection.

Hierarchy::

    ~/.coding-agent/AGENTS.md              (user global)
    ./AGENTS.md                            (project root)
    ./.coding-agent/AGENTS.md              (project alt location)
    ./.coding-agent/rules/*.md             (modular rules, sorted)
    ./AGENTS.local.md                      (local, gitignored)
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from coding_agent.logging import logger

# Maximum nesting depth for @path imports.
_MAX_IMPORT_DEPTH = 4

# Default token budget for the merged AGENTS.md content (~2000 tokens ≈ 8000 chars).
_DEFAULT_MAX_CHARS = 8000

# Pattern that matches ``@path/to/file`` (no extension required).
_IMPORT_RE = re.compile(r"^@(\S+)\s*$")

# Simple YAML frontmatter block (--- ... ---) at the start of a file.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n", re.DOTALL)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def load_agents_hierarchy(
    workspace: Path,
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Walk the AGENTS.md hierarchy and return the merged content.

    Parameters
    ----------
    workspace:
        Project root directory.
    max_chars:
        Maximum characters to return (default ~2000 tokens).

    Returns
    -------
    str
        Concatenated content from all discovered files, broadest scope
        first, truncated to *max_chars*.
    """
    parts: list[str] = []
    seen_hashes: set[str] = set()

    for file_path in _hierarchy_paths(workspace):
        if not file_path.is_file():
            continue
        try:
            raw = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("agents_md_read_failed", path=str(file_path), error=str(exc))
            continue

        content = _strip_frontmatter(raw)
        if not content.strip():
            continue

        # Deduplicate by content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)

        # Resolve @imports
        resolved = _resolve_imports(content, file_path.parent, set())
        parts.append(f"# [{file_path.name}] ({_scope_label(file_path, workspace)})\n\n{resolved}")

    if not parts:
        return ""

    merged = "\n\n---\n\n".join(parts)
    if len(merged) > max_chars:
        merged = merged[:max_chars] + "\n\n[truncated...]"

    logger.debug(
        "agents_md_loaded",
        files=len(parts),
        chars=len(merged),
        workspace=str(workspace),
    )
    return merged


# ------------------------------------------------------------------
# Hierarchy paths (broadest → narrowest)
# ------------------------------------------------------------------


def _hierarchy_paths(workspace: Path) -> list[Path]:
    """Return the ordered list of AGENTS.md file paths to check."""
    paths: list[Path] = []

    # 1. User global
    paths.append(Path.home() / ".coding-agent" / "AGENTS.md")

    # 2. Project root
    paths.append(workspace / "AGENTS.md")

    # 3. Project alt location
    paths.append(workspace / ".coding-agent" / "AGENTS.md")

    # 4. Modular rules (sorted alphabetically for determinism)
    rules_dir = workspace / ".coding-agent" / "rules"
    if rules_dir.is_dir():
        for md in sorted(rules_dir.glob("*.md")):
            paths.append(md)
        # Avoid adding the directory itself if it had no .md files
        # by not adding anything extra here.

    # 5. Local overrides
    paths.append(workspace / "AGENTS.local.md")

    return paths


def _scope_label(file_path: Path, workspace: Path) -> str:
    """Return a human-readable scope label for a file path."""
    home = Path.home()
    try:
        rel = file_path.relative_to(home)
        if rel.parts[:2] == (".coding-agent", "AGENTS.md"):
            return "user global"
    except ValueError:
        pass

    try:
        rel = file_path.relative_to(workspace)
    except ValueError:
        return "external"

    parts = rel.parts
    if parts == ("AGENTS.md",):
        return "project root"
    if parts == (".coding-agent", "AGENTS.md"):
        return "project alt"
    if len(parts) >= 2 and parts[0] == ".coding-agent" and parts[1] == "rules":
        return f"rule:{parts[-1].removesuffix('.md')}"
    if parts == ("AGENTS.local.md",):
        return "local"

    return str(rel)


# ------------------------------------------------------------------
# Frontmatter handling
# ------------------------------------------------------------------


def _strip_frontmatter(content: str) -> str:
    """Remove optional YAML frontmatter (``---`` ... ``---``) from *content*."""
    return _FRONTMATTER_RE.sub("", content)


# ------------------------------------------------------------------
# @import resolution
# ------------------------------------------------------------------


def _resolve_imports(
    content: str,
    base_dir: Path,
    visited: set[str],
    depth: int = 0,
) -> str:
    """Recursively resolve ``@path/to/file.md`` imports in *content*.

    Parameters
    ----------
    content:
        Markdown content that may contain ``@`` import lines.
    base_dir:
        Directory to resolve relative paths from.
    visited:
        Set of already-resolved absolute paths (for circular detection).
    depth:
        Current nesting depth. Stops at ``_MAX_IMPORT_DEPTH``.

    Returns
    -------
    str
        Content with all ``@`` lines replaced by the referenced file's content.
    """
    if depth >= _MAX_IMPORT_DEPTH:
        logger.warning("agents_md_import_depth_exceeded", depth=depth)
        return content

    lines: list[str] = []
    for line in content.splitlines():
        match = _IMPORT_RE.match(line.strip())
        if match is None:
            lines.append(line)
            continue

        import_path = match.group(1)

        # Resolve relative to the importing file's directory
        if import_path.startswith("~"):
            resolved = Path(import_path).expanduser()
        elif Path(import_path).is_absolute():
            resolved = Path(import_path)
        else:
            resolved = (base_dir / import_path).resolve()

        # Circular detection
        resolved_str = str(resolved)
        if resolved_str in visited:
            logger.warning("agents_md_circular_import", path=resolved_str)
            lines.append(f"<!-- circular import skipped: {import_path} -->")
            continue

        if not resolved.is_file():
            logger.warning("agents_md_import_not_found", path=resolved_str)
            lines.append(f"<!-- import not found: {import_path} -->")
            continue

        try:
            imported_content = resolved.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("agents_md_import_read_failed", path=resolved_str, error=str(exc))
            lines.append(f"<!-- import failed: {import_path} -->")
            continue

        imported_content = _strip_frontmatter(imported_content)

        # Recurse for nested imports
        new_visited = visited | {resolved_str}
        resolved_content = _resolve_imports(imported_content, resolved.parent, new_visited, depth + 1)
        lines.append(resolved_content)

    return "\n".join(lines)
