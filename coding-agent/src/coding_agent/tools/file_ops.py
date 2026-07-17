"""File operation tools: read, write, edit, and list."""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

import aiofiles
import pathspec
import pathspec.patterns.gitignore  # noqa: F401  # type: ignore[reportUnusedImport]  — registers gitignore factory

from coding_agent.agent.ast_check import validate_syntax
from coding_agent.logging import logger
from coding_agent.sandbox.protected_paths import is_protected_path
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool
from coding_agent.tools.undo import get_undo_manager
from coding_agent.agent.undo import UndoEntry

# Directories always excluded from listing
_DEFAULT_EXCLUDES = {
    ".git",
    "__pycache__",
    ".venv",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pyright",
}


def _check_protected_path(path: Path) -> ToolResult | None:
    """Check if a path is protected. Returns ToolResult if blocked, None if allowed."""
    from coding_agent.config import Settings

    settings = Settings()
    if not settings.protect_critical_paths:
        return None

    is_protected, reason = is_protected_path(str(path))
    if is_protected:
        logger.warning("protected_path_blocked", path=str(path), reason=reason)
        return ToolResult(success=False, error=f"Protected path: {reason}")

    return None


def _push_undo(tool_name: str, file_path: str, before: str, after: str, desc: str = "") -> None:
    """Push an undo entry if the undo manager is available."""
    manager = get_undo_manager()
    if manager is not None:
        manager.push(UndoEntry(
            tool_name=tool_name,
            file_path=file_path,
            before=before,
            after=after,
            description=desc,
        ))


class GitignoreFilter:
    """Load and evaluate .gitignore patterns for a workspace root.

    Lazily loads .gitignore files from directories between the target path
    and the root, so nested .gitignore files in subdirectories are discovered.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._cache: dict[Path, Any] = {}  # dir -> PathSpec

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_spec(self, directory: Path) -> Any:
        """Return the PathSpec for a directory, loading .gitignore if needed."""
        if directory in self._cache:
            return self._cache[directory]

        gitignore = directory / ".gitignore"
        spec: Any = None
        if gitignore.is_file():
            try:
                text = gitignore.read_text(encoding="utf-8")
            except OSError:
                pass
            else:
                lines = text.splitlines()
                spec = pathspec.PathSpec.from_lines("gitignore", lines)
        self._cache[directory] = spec
        return spec

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_ignored(self, path: Path) -> bool:
        """Return ``True`` if *path* matches any loaded gitignore pattern."""
        resolved = path.resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            return False

        # Walk from the path's parent up to root, checking each .gitignore
        current = resolved.parent
        while True:
            spec = self._get_spec(current)
            if spec is not None:
                try:
                    rel = resolved.relative_to(current)
                except ValueError:
                    break
                if spec.match_file(rel.as_posix()):
                    return True
            if current == self._root:
                break
            parent = current.parent
            if parent == current:
                break
            current = parent
        return False


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------


def _is_binary(data: bytes, check_bytes: int = 8192) -> bool:
    """Heuristic: detect binary content by checking for null bytes."""
    chunk = data[:check_bytes]
    return b"\x00" in chunk


# ------------------------------------------------------------------
# Tools
# ------------------------------------------------------------------


@tool(
    name="read_file",
    description="Read the contents of a file. Returns content with line numbers.",
    permission="read",
)
async def read_file(
    path: str,
    offset: int | str | None = None,
    limit: int | str | None = None,
) -> ToolResult:
    """Read a file and return its contents with line numbers."""
    p = Path(path).resolve()
    if not p.exists():
        return ToolResult(success=False, error=f"File not found: {path}")
    if p.is_dir():
        return ToolResult(success=False, error=f"Path is a directory: {path}")

    try:
        raw = p.read_bytes()
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot read file: {exc}")

    if _is_binary(raw):
        preview = raw[:256].hex()
        return ToolResult(
            success=False,
            error=f"Binary file detected ({len(raw)} bytes). Hex preview: {preview}",
        )

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return ToolResult(success=False, error=f"Cannot decode file as UTF-8: {exc}")

    lines = text.splitlines()

    # Coerce to int (LLM may send strings)
    try:
        offset_int = int(offset) if offset is not None else None
    except (ValueError, TypeError):
        offset_int = None
    try:
        limit_int = int(limit) if limit is not None else None
    except (ValueError, TypeError):
        limit_int = None

    start = max((offset_int or 1) - 1, 0)
    end = (start + limit_int) if limit_int else len(lines)
    selected = lines[start:end]

    numbered = [f"{i + 1}: {line}" for i, line in enumerate(selected, start=start)]
    output = "\n".join(numbered)

    logger.debug("read_file", path=str(p), lines=len(selected))
    return ToolResult(
        success=True,
        output=output,
        metadata={"total_lines": len(lines), "returned_lines": len(selected)},
    )


@tool(
    name="write_file",
    description="Write content to a file. Creates parent directories if needed.",
    permission="write",
)
async def write_file(path: str, content: str) -> ToolResult:
    """Create or overwrite a file with the given content."""
    p = Path(path).resolve()

    # Protected path check
    blocked = _check_protected_path(p)
    if blocked:
        return blocked

    # Capture before-state for undo
    before = ""
    if p.exists() and p.is_file():
        try:
            before = p.read_text(encoding="utf-8")
        except OSError:
            pass

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot create parent directory: {exc}")

    try:
        async with aiofiles.open(p, "w", encoding="utf-8") as f:
            await f.write(content)
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot write file: {exc}")

    # Push undo entry
    _push_undo("write_file", str(p), before, content, f"write {p.name}")

    byte_count = len(content.encode("utf-8"))
    logger.debug("write_file", path=str(p), bytes=byte_count)

    # AST validation
    is_valid, err_msg = validate_syntax(content, str(p))
    output = f"Successfully wrote {byte_count} bytes to {p}"
    if not is_valid:
        output += f"\n\nWARNING: Syntax issue detected — {err_msg}"

    return ToolResult(
        success=True,
        output=output,
        metadata={"path": str(p), "bytes_written": byte_count, "syntax_valid": is_valid},
    )


@tool(
    name="edit_file",
    description="Replace text in a file. The old_text must appear exactly once.",
    permission="write",
)
async def edit_file(path: str, old_text: str, new_text: str) -> ToolResult:
    """Perform a targeted string replacement in a file."""
    p = Path(path).resolve()
    if not p.exists():
        return ToolResult(success=False, error=f"File not found: {path}")
    if p.is_dir():
        return ToolResult(success=False, error=f"Path is a directory: {path}")

    # Protected path check
    blocked = _check_protected_path(p)
    if blocked:
        return blocked

    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot read file: {exc}")

    count = text.count(old_text)
    if count == 0:
        return ToolResult(
            success=False,
            error=f"old_text not found in {path}. Make sure the text matches exactly (including whitespace and indentation).",
        )
    if count > 1:
        return ToolResult(
            success=False,
            error=f"old_text appears {count} times in {path}. Provide more surrounding context to make it unique.",
        )

    new_content = text.replace(old_text, new_text, 1)

    try:
        p.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot write file: {exc}")

    # Push undo entry
    _push_undo("edit_file", str(p), text, new_content, f"edit {p.name}")

    # AST validation
    is_valid, err_msg = validate_syntax(new_content, str(p))
    output = f"Successfully edited {p}"
    if not is_valid:
        output += f"\n\nWARNING: Syntax issue detected — {err_msg}"

    logger.debug("edit_file", path=str(p))
    return ToolResult(
        success=True,
        output=output,
        metadata={
            "path": str(p),
            "old_preview": old_text[:120],
            "new_preview": new_text[:120],
            "syntax_valid": is_valid,
        },
    )


@tool(
    name="list_files",
    description="List files and directories in a path, optionally filtered by glob pattern.",
    permission="read",
)
async def list_files(path: str = ".", pattern: str | None = None) -> ToolResult:
    """List files matching *pattern* under *path*, respecting .gitignore."""
    p = Path(path).resolve()
    if not p.exists():
        return ToolResult(success=False, error=f"Path not found: {path}")
    if not p.is_dir():
        return ToolResult(success=False, error=f"Not a directory: {path}")

    gitignore = GitignoreFilter(p)

    glob_pattern = pattern or "*"
    entries: list[str] = []

    try:
        for item in sorted(p.glob(glob_pattern)):
            name = item.name
            if item.is_dir() and name in _DEFAULT_EXCLUDES:
                continue
            if gitignore.is_ignored(item):
                continue
            if item.is_dir():
                entries.append(f"{name}/")
            else:
                try:
                    size = item.stat().st_size
                except OSError:
                    size = 0
                entries.append(f"{name}  ({size} bytes)")
    except Exception as exc:
        return ToolResult(success=False, error=f"Glob error: {exc}")

    if not entries:
        output = f"No files found matching '{glob_pattern}' in {p}"
    else:
        output = "\n".join(entries)

    logger.debug("list_files", path=str(p), pattern=glob_pattern, count=len(entries))
    return ToolResult(
        success=True,
        output=output,
        metadata={"count": len(entries), "path": str(p)},
    )


# ------------------------------------------------------------------
# Patch tools
# ------------------------------------------------------------------


def _parse_unified_diff(diff_text: str) -> list[dict[str, Any]]:
    """Parse unified diff text into a list of hunks.

    Each hunk is a dict with keys:
      - old_start: starting line in old file (1-indexed)
      - old_count: number of lines removed
      - new_start: starting line in new file (1-indexed)
      - new_count: number of lines added
      - removed: list of removed lines (without leading '-')
      - added: list of added lines (without leading '+')
    """
    hunks: list[dict[str, Any]] = []
    lines = diff_text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Match hunk header: @@ -old_start,old_count +new_start,new_count @@
        match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if match:
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")

            removed: list[str] = []
            added: list[str] = []

            i += 1
            while i < len(lines):
                dline = lines[i]
                if dline.startswith("@@") or dline.startswith("diff "):
                    break
                if dline.startswith("-"):
                    removed.append(dline[1:])
                elif dline.startswith("+"):
                    added.append(dline[1:])
                elif dline.startswith(" "):
                    removed.append(dline[1:])
                    added.append(dline[1:])
                elif dline == "":
                    # Empty line at end of diff
                    break
                i += 1

            hunks.append({
                "old_start": old_start,
                "old_count": old_count,
                "new_start": new_start,
                "new_count": new_count,
                "removed": removed,
                "added": added,
            })
        else:
            i += 1

    return hunks


def _apply_hunks(lines: list[str], hunks: list[dict[str, Any]]) -> list[str] | str:
    """Apply parsed hunks to file lines. Returns new lines or error string."""
    # Work on a copy
    result = list(lines)

    # Apply hunks in reverse order to preserve line numbers
    for hunk in sorted(hunks, key=lambda h: h["old_start"], reverse=True):
        old_start = hunk["old_start"]
        removed = hunk["removed"]
        added = hunk["added"]

        # Convert to 0-indexed
        idx = old_start - 1

        # Verify the removed lines match
        existing = result[idx: idx + len(removed)]
        if existing != removed:
            # Try to find the block nearby (fuzzy match within ±3 lines)
            found = False
            for offset in range(-3, 4):
                try_idx = idx + offset
                if try_idx < 0:
                    continue
                if result[try_idx: try_idx + len(removed)] == removed:
                    idx = try_idx
                    found = True
                    break
            if not found:
                preview = "\n".join(existing[:3])
                expected = "\n".join(removed[:3])
                return (
                    f"Hunk at line {old_start} does not match file content.\n"
                    f"Expected:\n{expected}\nFound:\n{preview}"
                )

        # Replace the block
        result[idx: idx + len(removed)] = added

    return result


@tool(
    name="apply_patch",
    description="Apply a unified diff patch to a file. Accepts standard unified diff format with @@ headers.",
    permission="write",
)
async def apply_patch(path: str, patch: str) -> ToolResult:
    """Apply a unified diff patch to a file.

    The patch should be in unified diff format, e.g.::

        @@ -10,6 +10,8 @@
         def main():
         -    pass
         +    print("hello")
         +    return 0

    Multiple hunks can be included in a single patch.
    """
    p = Path(path).resolve()
    if not p.exists():
        return ToolResult(success=False, error=f"File not found: {path}")
    if p.is_dir():
        return ToolResult(success=False, error=f"Path is a directory: {path}")

    # Protected path check
    blocked = _check_protected_path(p)
    if blocked:
        return blocked

    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot read file: {exc}")

    lines = text.splitlines(keepends=True)

    # Strip trailing newlines from each line for comparison
    stripped = [l.rstrip("\n\r") for l in lines]

    hunks = _parse_unified_diff(patch)
    if not hunks:
        return ToolResult(
            success=False,
            error="No valid hunks found in patch. Ensure the patch uses unified diff format with @@ headers.",
        )

    result = _apply_hunks(stripped, hunks)
    if isinstance(result, str):
        return ToolResult(success=False, error=result)

    # Write the result
    new_content = "\n".join(result) + "\n" if text.endswith("\n") else "\n".join(result)

    try:
        p.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot write file: {exc}")

    # Push undo entry
    _push_undo("apply_patch", str(p), text, new_content, f"patch {p.name} ({len(hunks)} hunks)")

    # AST validation
    is_valid, err_msg = validate_syntax(new_content, str(p))
    output = f"Successfully applied {len(hunks)} hunk(s) to {p}"
    if not is_valid:
        output += f"\n\nWARNING: Syntax issue detected — {err_msg}"

    logger.debug("apply_patch", path=str(p), hunks=len(hunks))
    return ToolResult(
        success=True,
        output=output,
        metadata={"path": str(p), "hunks_applied": len(hunks), "syntax_valid": is_valid},
    )


@tool(
    name="multi_edit",
    description="Apply multiple text replacements to a single file in one call. Each edit specifies old_text and new_text.",
    permission="write",
)
async def multi_edit(path: str, edits: list[dict[str, str]]) -> ToolResult:
    """Apply multiple text replacements to a file in one call.

    Each edit in the list should have ``old_text`` and ``new_text`` keys.
    Edits are applied in order. All old_text values must be found exactly
    once in the file before any edits are applied (to prevent ordering issues).

    Example::

        multi_edit("app.py", [
            {"old_text": "def foo():", "new_text": "def bar():"},
            {"old_text": "return None", "new_text": "return 0"},
        ])
    """
    p = Path(path).resolve()
    if not p.exists():
        return ToolResult(success=False, error=f"File not found: {path}")
    if p.is_dir():
        return ToolResult(success=False, error=f"Path is a directory: {path}")

    # Protected path check
    blocked = _check_protected_path(p)
    if blocked:
        return blocked

    if not edits:
        return ToolResult(success=False, error="No edits provided.")

    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot read file: {exc}")

    original_text = text

    # Validate all old_text values exist before applying any
    for i, edit in enumerate(edits):
        old_text = edit.get("old_text", "")
        new_text = edit.get("new_text", "")
        if not old_text:
            return ToolResult(success=False, error=f"Edit {i+1}: old_text is empty.")
        count = text.count(old_text)
        if count == 0:
            return ToolResult(
                success=False,
                error=f"Edit {i+1}: old_text not found in {path}.",
            )
        if count > 1:
            return ToolResult(
                success=False,
                error=f"Edit {i+1}: old_text appears {count} times in {path}. Provide more context.",
            )

    # Apply edits sequentially
    for i, edit in enumerate(edits):
        old_text = edit["old_text"]
        new_text = edit["new_text"]
        text = text.replace(old_text, new_text, 1)

    try:
        p.write_text(text, encoding="utf-8")
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot write file: {exc}")

    # Push undo entry
    _push_undo("multi_edit", str(p), original_text, text, f"multi-edit {p.name} ({len(edits)} edits)")

    # AST validation
    is_valid, err_msg = validate_syntax(text, str(p))
    output = f"Successfully applied {len(edits)} edit(s) to {p}"
    if not is_valid:
        output += f"\n\nWARNING: Syntax issue detected — {err_msg}"

    logger.debug("multi_edit", path=str(p), edits=len(edits))
    return ToolResult(
        success=True,
        output=output,
        metadata={"path": str(p), "edits_applied": len(edits), "syntax_valid": is_valid},
    )
