"""File operation tools: read, write, edit, and list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiofiles
import pathspec
import pathspec.patterns.gitignore  # noqa: F401  # type: ignore[reportUnusedImport]  — registers gitignore factory

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool

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
    offset: int | None = None,
    limit: int | None = None,
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

    start = max((offset or 1) - 1, 0)
    end = (start + limit) if limit else len(lines)
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

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot create parent directory: {exc}")

    try:
        async with aiofiles.open(p, "w", encoding="utf-8") as f:
            await f.write(content)
    except OSError as exc:
        return ToolResult(success=False, error=f"Cannot write file: {exc}")

    byte_count = len(content.encode("utf-8"))
    logger.debug("write_file", path=str(p), bytes=byte_count)
    return ToolResult(
        success=True,
        output=f"Successfully wrote {byte_count} bytes to {p}",
        metadata={"path": str(p), "bytes_written": byte_count},
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

    logger.debug("edit_file", path=str(p))
    return ToolResult(
        success=True,
        output=f"Successfully edited {p}",
        metadata={
            "path": str(p),
            "old_preview": old_text[:120],
            "new_preview": new_text[:120],
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
