"""Tests for git tools."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from coding_agent.tools.registry import tool_registry

# Skip entire module if git is not available
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git not installed",
)


async def _git_init(path: Path) -> None:
    """Initialize a git repo in path with an initial commit."""
    proc = await __import__("asyncio").create_subprocess_exec(
        "git",
        "init",
        str(path),
        stdout=__import__("asyncio").subprocess.PIPE,
        stderr=__import__("asyncio").subprocess.PIPE,
    )
    await proc.wait()

    # Configure git user for the test repo
    for key, val in [("user.name", "Test"), ("user.email", "test@test.com")]:
        proc = await __import__("asyncio").create_subprocess_exec(
            "git",
            "-C",
            str(path),
            "config",
            key,
            val,
            stdout=__import__("asyncio").subprocess.PIPE,
            stderr=__import__("asyncio").subprocess.PIPE,
        )
        await proc.wait()

    # Create initial commit
    (path / "README.md").write_text("# Test\n")
    proc = await __import__("asyncio").create_subprocess_exec(
        "git",
        "-C",
        str(path),
        "add",
        "-A",
        stdout=__import__("asyncio").subprocess.PIPE,
        stderr=__import__("asyncio").subprocess.PIPE,
    )
    await proc.wait()
    proc = await __import__("asyncio").create_subprocess_exec(
        "git",
        "-C",
        str(path),
        "commit",
        "-m",
        "initial commit",
        stdout=__import__("asyncio").subprocess.PIPE,
        stderr=__import__("asyncio").subprocess.PIPE,
    )
    await proc.wait()


# ------------------------------------------------------------------
# git_status tests
# ------------------------------------------------------------------


class TestGitStatus:
    async def test_clean_repo(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        result = await tool_registry.execute("git_status", {"path": str(tmp_path)})
        assert result.success is True

    async def test_shows_modified_files(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        (tmp_path / "README.md").write_text("# Modified\n")
        result = await tool_registry.execute("git_status", {"path": str(tmp_path)})
        assert result.success is True
        assert "README.md" in result.output

    async def test_shows_untracked_files(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        (tmp_path / "new_file.txt").write_text("new\n")
        result = await tool_registry.execute("git_status", {"path": str(tmp_path)})
        assert result.success is True
        assert "new_file.txt" in result.output

    async def test_not_git_repo(self, tmp_path: Path) -> None:
        result = await tool_registry.execute(
            "git_status",
            {"path": str(tmp_path)},
        )
        assert result.success is False
        assert "failed" in (result.error or "").lower()


# ------------------------------------------------------------------
# git_diff tests
# ------------------------------------------------------------------


class TestGitDiff:
    async def test_unstaged_changes(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        (tmp_path / "README.md").write_text("# Changed\n")
        result = await tool_registry.execute("git_diff", {"path": str(tmp_path)})
        assert result.success is True
        assert "Changed" in result.output
        assert result.metadata["has_changes"] is True

    async def test_no_changes(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        result = await tool_registry.execute("git_diff", {"path": str(tmp_path)})
        assert result.success is True
        assert result.metadata["has_changes"] is False

    async def test_staged_changes(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        (tmp_path / "README.md").write_text("# Staged\n")
        # Stage the file
        proc = await __import__("asyncio").create_subprocess_exec(
            "git",
            "-C",
            str(tmp_path),
            "add",
            "README.md",
            stdout=__import__("asyncio").subprocess.PIPE,
            stderr=__import__("asyncio").subprocess.PIPE,
        )
        await proc.wait()
        result = await tool_registry.execute(
            "git_diff", {"path": str(tmp_path), "staged": True}
        )
        assert result.success is True
        assert result.metadata["staged"] is True

    async def test_diff_specific_file(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        (tmp_path / "a.txt").write_text("aaa\n")
        (tmp_path / "b.txt").write_text("bbb\n")
        result = await tool_registry.execute(
            "git_diff", {"path": str(tmp_path), "file": "a.txt"}
        )
        assert result.success is True


# ------------------------------------------------------------------
# git_log tests
# ------------------------------------------------------------------


class TestGitLog:
    async def test_shows_commits(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        result = await tool_registry.execute("git_log", {"path": str(tmp_path), "n": 5})
        assert result.success is True
        assert "initial commit" in result.output

    async def test_limit_count(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        result = await tool_registry.execute("git_log", {"path": str(tmp_path), "n": 1})
        assert result.success is True
        lines = [line for line in result.output.splitlines() if line.strip()]
        assert len(lines) <= 1

    async def test_metadata_count(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        result = await tool_registry.execute("git_log", {"path": str(tmp_path), "n": 10})
        assert result.metadata["count"] == 10


# ------------------------------------------------------------------
# git_commit tests
# ------------------------------------------------------------------


class TestGitCommit:
    async def test_commit_all_changes(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        (tmp_path / "new.txt").write_text("new file\n")
        result = await tool_registry.execute(
            "git_commit",
            {"message": "add new file", "path": str(tmp_path)},
        )
        assert result.success is True
        assert result.metadata["commit_hash"]
        assert result.metadata["message"] == "add new file"

    async def test_commit_specific_files(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        (tmp_path / "a.txt").write_text("aaa\n")
        (tmp_path / "b.txt").write_text("bbb\n")
        result = await tool_registry.execute(
            "git_commit",
            {
                "message": "add a.txt only",
                "files": ["a.txt"],
                "path": str(tmp_path),
            },
        )
        assert result.success is True
        # b.txt should still be untracked
        status_result = await tool_registry.execute("git_status", {"path": str(tmp_path)})
        assert "b.txt" in status_result.output

    async def test_empty_commit_fails(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        result = await tool_registry.execute(
            "git_commit",
            {"message": "nothing to commit", "path": str(tmp_path)},
        )
        assert result.success is False
        assert "commit failed" in (result.error or "").lower()

    async def test_commit_hash_is_hex(self, tmp_path: Path) -> None:
        await _git_init(tmp_path)
        (tmp_path / "file.txt").write_text("data\n")
        result = await tool_registry.execute(
            "git_commit",
            {"message": "test commit", "path": str(tmp_path)},
        )
        assert result.success is True
        h = result.metadata["commit_hash"]
        assert len(h) >= 7
        assert all(c in "0123456789abcdef" for c in h)
