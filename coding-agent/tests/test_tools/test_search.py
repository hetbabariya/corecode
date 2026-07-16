"""Tests for search tools (search_content, search_files)."""

from __future__ import annotations

import shutil

import pytest

from coding_agent.tools.registry import tool_registry

_skip_no_rg = pytest.mark.skipif(
    shutil.which("rg") is None,
    reason="ripgrep (rg) not installed",
)


# ------------------------------------------------------------------
# search_content tests
# ------------------------------------------------------------------


@_skip_no_rg
class TestSearchContent:
    async def test_finds_matches(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("def hello():\n    pass\n")
        (tmp_path / "b.py").write_text("def world():\n    pass\n")
        result = await tool_registry.execute(
            "search_content", {"pattern": "def \\w+", "path": str(tmp_path)}
        )
        assert result.success is True
        assert "hello" in result.output
        assert "world" in result.output

    async def test_no_matches(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n")
        result = await tool_registry.execute(
            "search_content", {"pattern": "def nonexistent", "path": str(tmp_path)}
        )
        assert result.success is True
        assert "No matches" in result.output
        assert result.metadata["match_count"] == 0

    async def test_filter_by_file_type(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("TARGET_VALUE = 1\n")
        (tmp_path / "app.js").write_text("TARGET_VALUE = 2\n")
        result = await tool_registry.execute(
            "search_content",
            {"pattern": "TARGET_VALUE", "path": str(tmp_path), "file_type": "py"},
        )
        assert result.success is True
        assert "app.py" in result.output
        assert "app.js" not in result.output

    async def test_path_not_found(self) -> None:
        result = await tool_registry.execute(
            "search_content", {"pattern": "test", "path": "/nonexistent/dir"}
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_metadata_match_count(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("foo\nfoo\nfoo\n")
        result = await tool_registry.execute(
            "search_content", {"pattern": "foo", "path": str(tmp_path)}
        )
        assert result.success is True
        assert result.metadata["match_count"] >= 1

    async def test_max_results(self, tmp_path: Path) -> None:
        lines = "\n".join(["TARGET"] * 20)
        (tmp_path / "big.txt").write_text(lines)
        result = await tool_registry.execute(
            "search_content",
            {"pattern": "TARGET", "path": str(tmp_path), "max_results": 5},
        )
        assert result.success is True
        assert result.metadata["match_count"] <= 5

    async def test_single_file_search(self, tmp_path: Path) -> None:
        f = tmp_path / "specific.txt"
        f.write_text("needle in haystack\n")
        result = await tool_registry.execute(
            "search_content", {"pattern": "needle", "path": str(f)}
        )
        assert result.success is True
        assert "needle" in result.output


# ------------------------------------------------------------------
# search_files tests
# ------------------------------------------------------------------


class TestSearchFiles:
    async def test_finds_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        (tmp_path / "c.txt").write_text("z")
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.py", "path": str(tmp_path)}
        )
        assert result.success is True
        assert "a.py" in result.output
        assert "b.py" in result.output
        assert "c.txt" not in result.output

    async def test_no_matches(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x")
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.xyz", "path": str(tmp_path)}
        )
        assert result.success is True
        assert "No files found" in result.output

    async def test_path_not_found(self) -> None:
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.py", "path": "/nonexistent/dir"}
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_not_a_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = await tool_registry.execute(
            "search_files", {"pattern": "*", "path": str(f)}
        )
        assert result.success is False
        assert "not a directory" in (result.error or "").lower()

    async def test_recursive_pattern(self, tmp_path: Path) -> None:
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "main.py").write_text("code")
        (sub / "util.py").write_text("code")
        result = await tool_registry.execute(
            "search_files", {"pattern": "**/*.py", "path": str(tmp_path)}
        )
        assert result.success is True
        assert "main.py" in result.output
        assert "util.py" in result.output

    async def test_metadata_count(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.py", "path": str(tmp_path)}
        )
        assert result.metadata["count"] == 2

    async def test_max_results(self, tmp_path: Path) -> None:
        for i in range(20):
            (tmp_path / f"file_{i}.txt").write_text(str(i))
        result = await tool_registry.execute(
            "search_files",
            {"pattern": "*.txt", "path": str(tmp_path), "max_results": 5},
        )
        assert result.success is True
        assert result.metadata["count"] == 5

    async def test_excludes_directories(self, tmp_path: Path) -> None:
        sub = tmp_path / "subdir"
        sub.mkdir()
        (tmp_path / "file.txt").write_text("x")
        result = await tool_registry.execute(
            "search_files", {"pattern": "*", "path": str(tmp_path)}
        )
        assert result.success is True
        assert "subdir" not in result.output

    async def test_metadata_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.py", "path": str(tmp_path)}
        )
        assert result.metadata["pattern"] == "*.py"
