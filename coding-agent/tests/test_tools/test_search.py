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
    async def test_finds_matches(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.py").write_text("def hello():\n    pass\n")  # type: ignore[union-attr]
        (p / "b.py").write_text("def world():\n    pass\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_content", {"pattern": "def \\w+", "path": str(p)}
        )
        assert result.success is True
        assert "hello" in result.output
        assert "world" in result.output

    async def test_no_matches(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.py").write_text("x = 1\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_content", {"pattern": "def nonexistent", "path": str(p)}
        )
        assert result.success is True
        assert "No matches" in result.output
        assert result.metadata["match_count"] == 0

    async def test_filter_by_file_type(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "app.py").write_text("TARGET_VALUE = 1\n")  # type: ignore[union-attr]
        (p / "app.js").write_text("TARGET_VALUE = 2\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_content",
            {"pattern": "TARGET_VALUE", "path": str(p), "file_type": "py"},
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

    async def test_metadata_match_count(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.txt").write_text("foo\nfoo\nfoo\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_content", {"pattern": "foo", "path": str(p)}
        )
        assert result.success is True
        assert result.metadata["match_count"] >= 1

    async def test_max_results(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        lines = "\n".join(["TARGET"] * 20)
        (p / "big.txt").write_text(lines)  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_content",
            {"pattern": "TARGET", "path": str(p), "max_results": 5},
        )
        assert result.success is True
        assert result.metadata["match_count"] <= 5

    async def test_single_file_search(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "specific.txt"  # type: ignore[union-attr]
        f.write_text("needle in haystack\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_content", {"pattern": "needle", "path": str(f)}
        )
        assert result.success is True
        assert "needle" in result.output


# ------------------------------------------------------------------
# search_files tests
# ------------------------------------------------------------------


class TestSearchFiles:
    async def test_finds_files(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.py").write_text("x")  # type: ignore[union-attr]
        (p / "b.py").write_text("y")  # type: ignore[union-attr]
        (p / "c.txt").write_text("z")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.py", "path": str(p)}
        )
        assert result.success is True
        assert "a.py" in result.output
        assert "b.py" in result.output
        assert "c.txt" not in result.output

    async def test_no_matches(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.txt").write_text("x")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.xyz", "path": str(p)}
        )
        assert result.success is True
        assert "No files found" in result.output

    async def test_path_not_found(self) -> None:
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.py", "path": "/nonexistent/dir"}
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_not_a_directory(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "file.txt"  # type: ignore[union-attr]
        f.write_text("x")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_files", {"pattern": "*", "path": str(f)}
        )
        assert result.success is False
        assert "not a directory" in (result.error or "").lower()

    async def test_recursive_pattern(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        sub = p / "src"  # type: ignore[union-attr]
        sub.mkdir()  # type: ignore[union-attr]
        (sub / "main.py").write_text("code")  # type: ignore[union-attr]
        (sub / "util.py").write_text("code")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_files", {"pattern": "**/*.py", "path": str(p)}
        )
        assert result.success is True
        assert "main.py" in result.output
        assert "util.py" in result.output

    async def test_metadata_count(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.py").write_text("x")  # type: ignore[union-attr]
        (p / "b.py").write_text("y")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.py", "path": str(p)}
        )
        assert result.metadata["count"] == 2

    async def test_max_results(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        for i in range(20):
            (p / f"file_{i}.txt").write_text(str(i))  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_files",
            {"pattern": "*.txt", "path": str(p), "max_results": 5},
        )
        assert result.success is True
        assert result.metadata["count"] == 5

    async def test_excludes_directories(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        sub = p / "subdir"  # type: ignore[union-attr]
        sub.mkdir()  # type: ignore[union-attr]
        (p / "file.txt").write_text("x")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_files", {"pattern": "*", "path": str(p)}
        )
        assert result.success is True
        assert "subdir" not in result.output

    async def test_metadata_pattern(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.py").write_text("x")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "search_files", {"pattern": "*.py", "path": str(p)}
        )
        assert result.metadata["pattern"] == "*.py"
