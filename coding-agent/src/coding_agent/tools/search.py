"""Search tools: content search (ripgrep) and file search (glob)."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool


def _find_rg() -> str | None:
    """Return the path to ripgrep binary, or None if not found."""
    return shutil.which("rg")


# ------------------------------------------------------------------
# search_content — ripgrep
# ------------------------------------------------------------------


@tool(
    name="search_content",
    description=(
        "Search file contents using regex patterns via ripgrep. "
        "Returns file paths with line numbers and matching text."
    ),
    permission="read",
)
async def search_content(
    pattern: str,
    path: str = ".",
    file_type: str | None = None,
    max_results: int = 50,
) -> ToolResult:
    """Search file contents using ripgrep.

    Parameters
    ----------
    pattern:
        Regex pattern to search for.
    path:
        Directory or file to search in.
    file_type:
        Filter by file type (e.g. "py", "js", "ts").
    max_results:
        Maximum number of results to return.
    """
    rg = _find_rg()
    if rg is None:
        return ToolResult(
            success=False,
            error="ripgrep (rg) not found. Install it: https://github.com/BurntSushi/ripgrep#installation",
        )

    target = Path(path).resolve()
    if not target.exists():
        return ToolResult(success=False, error=f"Path not found: {path}")

    cmd = [rg, "--no-heading", "--line-number", "--color=never", pattern]
    if file_type:
        cmd.extend(["--type", file_type])
    cmd.extend(["--max-count", "1"])
    cmd.append(str(target))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except TimeoutError:
        proc.kill()  # type: ignore[union-attr]
        return ToolResult(success=False, error="Search timed out after 30 seconds")
    except FileNotFoundError:
        return ToolResult(
            success=False,
            error="ripgrep (rg) not found. Install it: https://github.com/BurntSushi/ripgrep#installation",
        )

    if proc.returncode not in (0, 1):  # type: ignore[union-attr]
        # rg returns 1 for no matches, other codes are errors
        err = stderr.decode("utf-8", errors="replace").strip()  # type: ignore[union-attr]
        return ToolResult(success=False, error=f"ripgrep error: {err}")

    output = stdout.decode("utf-8", errors="replace").strip()  # type: ignore[union-attr]
    if not output:
        return ToolResult(
            success=True,
            output=f"No matches found for pattern: {pattern}",
            metadata={"match_count": 0},
        )

    lines = output.splitlines()
    truncated = lines[:max_results]
    match_count = len(truncated)
    output = "\n".join(truncated)

    logger.debug(
        "search_content",
        pattern=pattern,
        path=str(target),
        matches=match_count,
    )
    return ToolResult(
        success=True,
        output=output,
        metadata={"match_count": match_count, "pattern": pattern},
    )


# ------------------------------------------------------------------
# search_files — glob
# ------------------------------------------------------------------


@tool(
    name="search_files",
    description=(
        "Find files by name/glob pattern. "
        "Returns matching file paths."
    ),
    permission="read",
)
async def search_files(
    pattern: str,
    path: str = ".",
    max_results: int = 100,
) -> ToolResult:
    """Find files matching a glob pattern.

    Parameters
    ----------
    pattern:
        Glob pattern (e.g. "*.py", "src/**/*.ts").
    path:
        Directory to search in.
    max_results:
        Maximum number of results to return.
    """
    target = Path(path).resolve()
    if not target.exists():
        return ToolResult(success=False, error=f"Path not found: {path}")
    if not target.is_dir():
        return ToolResult(success=False, error=f"Not a directory: {path}")

    try:
        matches = sorted(target.glob(pattern))
    except Exception as exc:
        return ToolResult(success=False, error=f"Glob error: {exc}")

    # Filter to files only, apply limit
    files: list[str] = []
    for m in matches:
        if m.is_file():
            files.append(str(m.relative_to(target)))
            if len(files) >= max_results:
                break

    if not files:
        return ToolResult(
            success=True,
            output=f"No files found matching '{pattern}' in {target}",
            metadata={"count": 0, "pattern": pattern},
        )

    output = "\n".join(files)
    logger.debug(
        "search_files",
        pattern=pattern,
        path=str(target),
        count=len(files),
    )
    return ToolResult(
        success=True,
        output=output,
        metadata={"count": len(files), "pattern": pattern},
    )
