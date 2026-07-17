"""Git operation tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool


async def _run_git(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a git command and return (exit_code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,  # type: ignore[union-attr]
        stdout.decode("utf-8", errors="replace").strip(),  # type: ignore[union-attr]
        stderr.decode("utf-8", errors="replace").strip(),  # type: ignore[union-attr]
    )


# ------------------------------------------------------------------
# git_status
# ------------------------------------------------------------------


@tool(
    name="git_status",
    description="Show working tree status (branch, modified, staged, untracked files).",
    permission="read",
)
async def git_status(path: str | None = None) -> ToolResult:
    """Show git status."""
    cwd = str(Path(path).resolve()) if path else None

    exit_code, stdout, stderr = await _run_git("status", "--short", "--branch", cwd=cwd)
    if exit_code != 0:
        return ToolResult(success=False, error=f"git status failed: {stderr}")

    logger.debug("git_status", path=cwd)
    return ToolResult(
        success=True,
        output=stdout or "(no changes)",
        metadata={"path": cwd},
    )


# ------------------------------------------------------------------
# git_diff
# ------------------------------------------------------------------


@tool(
    name="git_diff",
    description="Show file changes. Use staged=true for staged changes.",
    permission="read",
)
async def git_diff(
    path: str | None = None,
    file: str | None = None,
    staged: bool = False,
) -> ToolResult:
    """Show git diff."""
    cwd = str(Path(path).resolve()) if path else None

    args = ["diff"]
    if staged:
        args.append("--staged")
    if file:
        args.append("--")
        args.append(file)

    exit_code, stdout, stderr = await _run_git(*args, cwd=cwd)
    if exit_code != 0:
        return ToolResult(success=False, error=f"git diff failed: {stderr}")

    output = stdout or "(no changes)"
    logger.debug("git_diff", path=cwd, staged=staged, file=file)
    return ToolResult(
        success=True,
        output=output,
        metadata={"staged": staged, "has_changes": bool(stdout)},
    )


# ------------------------------------------------------------------
# git_log
# ------------------------------------------------------------------


@tool(
    name="git_log",
    description="Show recent commit history with hash, author, date, and message.",
    permission="read",
)
async def git_log(
    n: int = 10,
    path: str | None = None,
    branch: str | None = None,
) -> ToolResult:
    """Show git log."""
    cwd = str(Path(path).resolve()) if path else None

    args = [
        "log",
        f"--max-count={n}",
        "--pretty=format:%h | %an | %ad | %s",
        "--date=short",
    ]
    if branch:
        args.append(branch)

    exit_code, stdout, stderr = await _run_git(*args, cwd=cwd)
    if exit_code != 0:
        return ToolResult(success=False, error=f"git log failed: {stderr}")

    output = stdout or "(no commits)"
    logger.debug("git_log", path=cwd, count=n, branch=branch)
    return ToolResult(
        success=True,
        output=output,
        metadata={"count": n, "branch": branch},
    )


# ------------------------------------------------------------------
# git_commit
# ------------------------------------------------------------------


@tool(
    name="git_commit",
    description="Stage files and create a commit. Use files=[] to stage all changes.",
    permission="write",
    retryable=False,
)
async def git_commit(
    message: str,
    files: list[str] | None = None,
    path: str | None = None,
) -> ToolResult:
    """Stage files and commit."""
    cwd = str(Path(path).resolve()) if path else None

    # Stage files
    if files is None or len(files) == 0:
        # Stage all changes
        exit_code, _, stderr = await _run_git("add", "-A", cwd=cwd)
    else:
        exit_code, _, stderr = await _run_git("add", "--", *files, cwd=cwd)

    if exit_code != 0:
        return ToolResult(success=False, error=f"git add failed: {stderr}")

    # Commit
    exit_code, stdout, stderr = await _run_git("commit", "-m", message, cwd=cwd)
    if exit_code != 0:
        return ToolResult(success=False, error=f"git commit failed: {stderr}")

    # Get the commit hash
    _, hash_output, _ = await _run_git("rev-parse", "HEAD", cwd=cwd)

    logger.debug("git_commit", message=message, files=files, hash=hash_output)
    return ToolResult(
        success=True,
        output=stdout or f"Committed: {hash_output}",
        metadata={"commit_hash": hash_output, "message": message},
    )
