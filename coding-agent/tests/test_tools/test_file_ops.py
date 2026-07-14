"""Comprehensive tests for file operation tools."""

from __future__ import annotations

from pathlib import Path

from coding_agent.tools.base import ToolResult
from coding_agent.tools.file_ops import GitignoreFilter, _is_binary
from coding_agent.tools.registry import tool_registry

# ------------------------------------------------------------------
# _is_binary helper
# ------------------------------------------------------------------


class TestIsBinary:
    def test_null_byte_detected(self) -> None:
        assert _is_binary(b"\x00\x01\x02") is True

    def test_empty_bytes_not_binary(self) -> None:
        assert _is_binary(b"") is False

    def test_text_not_binary(self) -> None:
        assert _is_binary(b"hello world\n") is False

    def test_large_null_in_first_8kb(self) -> None:
        data = b"a" * 8192 + b"\x00"
        assert _is_binary(data) is False  # null is after 8192 boundary

    def test_null_within_check_range(self) -> None:
        data = b"a" * 100 + b"\x00" + b"b" * 100
        assert _is_binary(data) is True


# ------------------------------------------------------------------
# GitignoreFilter tests
# ------------------------------------------------------------------


class TestGitignoreFilter:
    def test_ignores_matching_file(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / ".gitignore").write_text("*.log\n")  # type: ignore[union-attr]
        gf = GitignoreFilter(p)  # type: ignore[arg-type]
        assert gf.is_ignored(p / "debug.log")  # type: ignore[union-attr]
        assert not gf.is_ignored(p / "main.py")  # type: ignore[union-attr]

    def test_ignores_directory_pattern(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / ".gitignore").write_text("build/\n")  # type: ignore[union-attr]
        build = p / "build"  # type: ignore[union-attr]
        build.mkdir()  # type: ignore[union-attr]
        (build / "output.txt").write_text("data")  # type: ignore[union-attr]
        gf = GitignoreFilter(p)  # type: ignore[arg-type]
        assert gf.is_ignored(build / "output.txt")  # type: ignore[union-attr]

    def test_nested_gitignore(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / ".gitignore").write_text("*.log\n")  # type: ignore[union-attr]
        sub = p / "src"  # type: ignore[union-attr]
        sub.mkdir()  # type: ignore[union-attr]
        (sub / ".gitignore").write_text("*.tmp\n")  # type: ignore[union-attr]
        cache_file = sub / "cache.tmp"  # type: ignore[union-attr]
        cache_file.write_text("")  # type: ignore[union-attr]
        gf = GitignoreFilter(p)  # type: ignore[arg-type]
        assert gf.is_ignored(p / "debug.log")  # type: ignore[union-attr]
        assert gf.is_ignored(cache_file)
        assert not gf.is_ignored(sub / "main.py")  # type: ignore[union-attr]

    def test_negation_pattern(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / ".gitignore").write_text("*.log\n!important.log\n")  # type: ignore[union-attr]
        (p / "debug.log").write_text("")  # type: ignore[union-attr]
        (p / "important.log").write_text("")  # type: ignore[union-attr]
        gf = GitignoreFilter(p)  # type: ignore[arg-type]
        assert gf.is_ignored(p / "debug.log")  # type: ignore[union-attr]
        assert not gf.is_ignored(p / "important.log")  # type: ignore[union-attr]

    def test_path_outside_root_returns_false(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / ".gitignore").write_text("*.log\n")  # type: ignore[union-attr]
        gf = GitignoreFilter(p)  # type: ignore[arg-type]
        outside = Path("/other/place/file.log")  # noqa: OS001
        assert gf.is_ignored(outside) is False

    def test_multiple_patterns(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / ".gitignore").write_text("*.log\n*.tmp\n*.bak\n")  # type: ignore[union-attr]
        gf = GitignoreFilter(p)  # type: ignore[arg-type]
        assert gf.is_ignored(p / "a.log")  # type: ignore[union-attr]
        assert gf.is_ignored(p / "b.tmp")  # type: ignore[union-attr]
        assert gf.is_ignored(p / "c.bak")  # type: ignore[union-attr]
        assert not gf.is_ignored(p / "d.py")  # type: ignore[union-attr]

    def test_caching_reuses_spec(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / ".gitignore").write_text("*.log\n")  # type: ignore[union-attr]
        gf = GitignoreFilter(p)  # type: ignore[arg-type]
        gf.is_ignored(p / "a.log")  # type: ignore[union-attr]
        gf.is_ignored(p / "b.log")  # type: ignore[union-attr]
        assert len(gf._cache) == 1

    def test_no_gitignore_file(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        gf = GitignoreFilter(p)  # type: ignore[arg-type]
        assert gf.is_ignored(p / "anything.txt") is False  # type: ignore[union-attr]

    def test_deeply_nested_path(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / ".gitignore").write_text("*.log\n")  # type: ignore[union-attr]
        deep = p / "a" / "b" / "c"  # type: ignore[union-attr]
        deep.mkdir(parents=True)  # type: ignore[union-attr]
        (deep / "nested.log").write_text("")  # type: ignore[union-attr]
        gf = GitignoreFilter(p)  # type: ignore[arg-type]
        assert gf.is_ignored(deep / "nested.log")


# ------------------------------------------------------------------
# read_file tests
# ------------------------------------------------------------------


class TestReadFile:
    async def test_returns_content_with_line_numbers(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "hello.txt"  # type: ignore[union-attr]
        f.write_text("alpha\nbeta\ngamma\n")  # type: ignore[union-attr]
        result = await tool_registry.execute("read_file", {"path": str(f)})
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert "1: alpha" in result.output
        assert "2: beta" in result.output
        assert "3: gamma" in result.output

    async def test_with_offset(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "lines.txt"  # type: ignore[union-attr]
        f.write_text("a\nb\nc\nd\ne\n")  # type: ignore[union-attr]
        result = await tool_registry.execute("read_file", {"path": str(f), "offset": 3})
        assert result.success is True
        assert "3: c" in result.output
        assert "1: a" not in result.output

    async def test_with_limit(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "lines.txt"  # type: ignore[union-attr]
        f.write_text("a\nb\nc\nd\ne\n")  # type: ignore[union-attr]
        result = await tool_registry.execute("read_file", {"path": str(f), "limit": 2})
        assert result.success is True
        lines = result.output.strip().split("\n")
        assert len(lines) == 2
        assert "1: a" in lines[0]
        assert "2: b" in lines[1]

    async def test_with_offset_and_limit(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "lines.txt"  # type: ignore[union-attr]
        f.write_text("a\nb\nc\nd\ne\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "read_file", {"path": str(f), "offset": 2, "limit": 2}
        )
        assert result.success is True
        lines = result.output.strip().split("\n")
        assert len(lines) == 2
        assert "2: b" in lines[0]
        assert "3: c" in lines[1]

    async def test_file_not_found(self) -> None:
        result = await tool_registry.execute(
            "read_file", {"path": "/nonexistent/path/file.txt"}
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_is_directory(self, tmp_path: object) -> None:
        result = await tool_registry.execute("read_file", {"path": str(tmp_path)})  # type: ignore[arg-type]
        assert result.success is False
        assert "directory" in (result.error or "").lower()

    async def test_binary_file(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "image.bin"  # type: ignore[union-attr]
        f.write_bytes(b"\x00\x01\x02\x03\x00\x05\x06\x07")  # type: ignore[union-attr]
        result = await tool_registry.execute("read_file", {"path": str(f)})
        assert result.success is False
        assert "binary" in (result.error or "").lower()

    async def test_metadata(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "meta.txt"  # type: ignore[union-attr]
        f.write_text("line1\nline2\nline3\n")  # type: ignore[union-attr]
        result = await tool_registry.execute("read_file", {"path": str(f)})
        assert result.metadata["total_lines"] == 3
        assert result.metadata["returned_lines"] == 3

    async def test_empty_file(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "empty.txt"  # type: ignore[union-attr]
        f.write_text("")  # type: ignore[union-attr]
        result = await tool_registry.execute("read_file", {"path": str(f)})
        assert result.success is True
        assert result.output == ""
        assert result.metadata["total_lines"] == 0

    async def test_single_line_no_newline(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "single.txt"  # type: ignore[union-attr]
        f.write_text("just one line")  # type: ignore[union-attr]
        result = await tool_registry.execute("read_file", {"path": str(f)})
        assert result.success is True
        assert "1: just one line" in result.output
        assert result.metadata["total_lines"] == 1

    async def test_offset_beyond_file_length(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "short.txt"  # type: ignore[union-attr]
        f.write_text("a\nb\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "read_file", {"path": str(f), "offset": 100}
        )
        assert result.success is True
        assert result.output == ""
        assert result.metadata["returned_lines"] == 0

    async def test_limit_larger_than_file(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "tiny.txt"  # type: ignore[union-attr]
        f.write_text("x\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "read_file", {"path": str(f), "limit": 100}
        )
        assert result.success is True
        assert "1: x" in result.output
        assert result.metadata["returned_lines"] == 1

    async def test_multiline_content(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "multi.txt"  # type: ignore[union-attr]
        content = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        f.write_text(content)  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "read_file", {"path": str(f), "offset": 2, "limit": 3}
        )
        assert result.success is True
        lines = result.output.strip().split("\n")
        assert len(lines) == 3
        assert "2: line 2" in lines[0]
        assert "3: line 3" in lines[1]
        assert "4: line 4" in lines[2]

    async def test_non_utf8_file(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "binary.txt"  # type: ignore[union-attr]
        f.write_bytes(b"\x80\x81\x82\x83")  # type: ignore[union-attr]
        result = await tool_registry.execute("read_file", {"path": str(f)})
        assert result.success is False
        assert "utf-8" in (result.error or "").lower()


# ------------------------------------------------------------------
# write_file tests
# ------------------------------------------------------------------


class TestWriteFile:
    async def test_creates_new_file(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "new.txt"  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "write_file", {"path": str(f), "content": "hello world"}
        )
        assert result.success is True
        assert f.read_text() == "hello world"  # type: ignore[union-attr]

    async def test_creates_parent_dirs(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "a" / "b" / "c.txt"  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "write_file", {"path": str(f), "content": "nested"}
        )
        assert result.success is True
        assert f.read_text() == "nested"  # type: ignore[union-attr]

    async def test_overwrites_existing(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "existing.txt"  # type: ignore[union-attr]
        f.write_text("old content")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "write_file", {"path": str(f), "content": "new content"}
        )
        assert result.success is True
        assert f.read_text() == "new content"  # type: ignore[union-attr]

    async def test_metadata_bytes_written(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "count.txt"  # type: ignore[union-attr]
        content = "hello"
        result = await tool_registry.execute(
            "write_file", {"path": str(f), "content": content}
        )
        assert result.metadata["bytes_written"] == len(content.encode("utf-8"))

    async def test_success_message(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "msg.txt"  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "write_file", {"path": str(f), "content": "data"}
        )
        assert "Successfully wrote" in result.output

    async def test_empty_content(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "empty.txt"  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "write_file", {"path": str(f), "content": ""}
        )
        assert result.success is True
        assert f.read_text() == ""  # type: ignore[union-attr]
        assert result.metadata["bytes_written"] == 0

    async def test_unicode_content(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "unicode.txt"  # type: ignore[union-attr]
        content = "Hello 世界 🌍 café"
        result = await tool_registry.execute(
            "write_file", {"path": str(f), "content": content}
        )
        assert result.success is True
        assert f.read_text(encoding="utf-8") == content  # type: ignore[union-attr]

    async def test_content_with_newlines(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "newlines.txt"  # type: ignore[union-attr]
        content = "line1\nline2\n\nline4\n"
        result = await tool_registry.execute(
            "write_file", {"path": str(f), "content": content}
        )
        assert result.success is True
        assert f.read_text() == content  # type: ignore[union-attr]

    async def test_metadata_path(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "path_test.txt"  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "write_file", {"path": str(f), "content": "data"}
        )
        assert result.metadata["path"] == str(f)


# ------------------------------------------------------------------
# edit_file tests
# ------------------------------------------------------------------


class TestEditFile:
    async def test_replaces_text(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "edit.txt"  # type: ignore[union-attr]
        f.write_text("def old_name():\n    pass\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "edit_file",
            {"path": str(f), "old_text": "old_name", "new_text": "new_name"},
        )
        assert result.success is True
        assert "new_name" in f.read_text()  # type: ignore[union-attr]
        assert "old_name" not in f.read_text()  # type: ignore[union-attr]

    async def test_file_not_found(self) -> None:
        result = await tool_registry.execute(
            "edit_file",
            {"path": "/nonexistent/file.txt", "old_text": "a", "new_text": "b"},
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_old_text_not_found(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "content.txt"  # type: ignore[union-attr]
        f.write_text("hello world")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "edit_file",
            {"path": str(f), "old_text": "nonexistent", "new_text": "replacement"},
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_multiple_matches_error(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "dupes.txt"  # type: ignore[union-attr]
        f.write_text("foo bar foo baz foo")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "edit_file", {"path": str(f), "old_text": "foo", "new_text": "qux"}
        )
        assert result.success is False
        assert "3 times" in (result.error or "")

    async def test_metadata_previews(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "preview.txt"  # type: ignore[union-attr]
        f.write_text("aaa bbb ccc")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "edit_file", {"path": str(f), "old_text": "bbb", "new_text": "BBB"}
        )
        assert "old_preview" in result.metadata
        assert "new_preview" in result.metadata

    async def test_is_directory(self, tmp_path: object) -> None:
        result = await tool_registry.execute(
            "edit_file",
            {"path": str(tmp_path), "old_text": "a", "new_text": "b"},  # type: ignore[arg-type]
        )
        assert result.success is False
        assert "directory" in (result.error or "").lower()

    async def test_multiline_replacement(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "multi.txt"  # type: ignore[union-attr]
        f.write_text("line1\nline2\nline3\n")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "edit_file",
            {
                "path": str(f),
                "old_text": "line1\nline2",
                "new_text": "replaced\nline2",
            },
        )
        assert result.success is True
        content = f.read_text()  # type: ignore[union-attr]
        assert "replaced" in content
        assert "line1" not in content

    async def test_preserves_surrounding_content(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "preserve.txt"  # type: ignore[union-attr]
        f.write_text("before middle after")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "edit_file",
            {"path": str(f), "old_text": "middle", "new_text": "CENTER"},
        )
        assert result.success is True
        assert f.read_text() == "before CENTER after"  # type: ignore[union-attr]

    async def test_metadata_path(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "meta.txt"  # type: ignore[union-attr]
        f.write_text("aaa")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "edit_file", {"path": str(f), "old_text": "aaa", "new_text": "bbb"}
        )
        assert result.metadata["path"] == str(f)


# ------------------------------------------------------------------
# list_files tests
# ------------------------------------------------------------------


class TestListFiles:
    async def test_lists_files(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.txt").write_text("a")  # type: ignore[union-attr]
        (p / "b.py").write_text("b")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.success is True
        assert "a.txt" in result.output
        assert "b.py" in result.output

    async def test_with_pattern(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.txt").write_text("a")  # type: ignore[union-attr]
        (p / "b.py").write_text("b")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "list_files", {"path": str(p), "pattern": "*.py"}
        )
        assert result.success is True
        assert "b.py" in result.output
        assert "a.txt" not in result.output

    async def test_excludes_pycache(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "main.py").write_text("code")  # type: ignore[union-attr]
        cache = p / "__pycache__"  # type: ignore[union-attr]
        cache.mkdir()  # type: ignore[union-attr]
        (cache / "cached.pyc").write_bytes(b"\x00")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.success is True
        assert "__pycache__" not in result.output
        assert "main.py" in result.output

    async def test_excludes_gitignored(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / ".gitignore").write_text("*.log\n")  # type: ignore[union-attr]
        (p / "app.py").write_text("code")  # type: ignore[union-attr]
        (p / "debug.log").write_text("log")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.success is True
        assert "app.py" in result.output
        assert "debug.log" not in result.output

    async def test_path_not_found(self) -> None:
        result = await tool_registry.execute("list_files", {"path": "/nonexistent/dir"})
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_not_a_directory(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "file.txt"  # type: ignore[union-attr]
        f.write_text("x")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(f)})
        assert result.success is False
        assert "not a directory" in (result.error or "").lower()

    async def test_empty_directory(self, tmp_path: object) -> None:
        result = await tool_registry.execute(
            "list_files",
            {"path": str(tmp_path)},  # type: ignore[arg-type]
        )
        assert result.success is True
        assert "No files found" in result.output

    async def test_metadata_count(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "a.txt").write_text("a")  # type: ignore[union-attr]
        (p / "b.txt").write_text("b")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.metadata["count"] == 2

    async def test_sorted_output(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "z.txt").write_text("z")  # type: ignore[union-attr]
        (p / "a.txt").write_text("a")  # type: ignore[union-attr]
        (p / "m.txt").write_text("m")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.success is True
        lines = result.output.split("\n")
        names = [line.split("  ")[0] for line in lines]
        assert names == sorted(names)

    async def test_excludes_git_directory(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "main.py").write_text("code")  # type: ignore[union-attr]
        git = p / ".git"  # type: ignore[union-attr]
        git.mkdir()  # type: ignore[union-attr]
        (git / "config").write_text("")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.success is True
        assert ".git" not in result.output

    async def test_excludes_node_modules(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        (p / "app.js").write_text("code")  # type: ignore[union-attr]
        nm = p / "node_modules"  # type: ignore[union-attr]
        nm.mkdir()  # type: ignore[union-attr]
        (nm / "pkg").write_text("")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.success is True
        assert "node_modules" not in result.output

    async def test_directory_shows_trailing_slash(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        sub = p / "subdir"  # type: ignore[union-attr]
        sub.mkdir()  # type: ignore[union-attr]
        (p / "file.txt").write_text("x")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.success is True
        assert "subdir/" in result.output
        assert "file.txt" in result.output

    async def test_file_shows_size(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        f = p / "sized.txt"  # type: ignore[union-attr]
        f.write_text("hello")  # type: ignore[union-attr]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.success is True
        assert "5 bytes" in result.output

    async def test_metadata_path(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        result = await tool_registry.execute("list_files", {"path": str(p)})
        assert result.metadata["path"] == str(p)

    async def test_nested_directories_not_expanded(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        sub = p / "src"  # type: ignore[union-attr]
        sub.mkdir()  # type: ignore[union-attr]
        (sub / "main.py").write_text("code")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "list_files", {"path": str(p), "pattern": "*"}
        )
        assert result.success is True
        assert "src/" in result.output
        assert "main.py" not in result.output

    async def test_pattern_with_subdirectory(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        sub = p / "src"  # type: ignore[union-attr]
        sub.mkdir()  # type: ignore[union-attr]
        (sub / "app.py").write_text("code")  # type: ignore[union-attr]
        (sub / "util.py").write_text("util")  # type: ignore[union-attr]
        result = await tool_registry.execute(
            "list_files", {"path": str(p), "pattern": "src/*.py"}
        )
        assert result.success is True
        assert "app.py" in result.output
        assert "util.py" in result.output


# ------------------------------------------------------------------
# Registry integration tests
# ------------------------------------------------------------------


class TestRegistryIntegration:
    def test_all_tools_registered(self) -> None:
        expected = {"read_file", "write_file", "edit_file", "list_files", "apply_patch", "multi_edit"}
        registered = set(tool_registry.list_tools())
        assert expected.issubset(registered)

    def test_schemas_are_valid(self) -> None:
        schemas = tool_registry.get_schemas()
        names = {s["function"]["name"] for s in schemas}
        assert "read_file" in names
        assert "write_file" in names
        assert "edit_file" in names
        assert "list_files" in names
        assert "apply_patch" in names
        assert "multi_edit" in names

    def test_read_file_permission(self) -> None:
        tool = tool_registry.get("read_file")
        assert tool.permission_level == "read"

    def test_write_file_permission(self) -> None:
        tool = tool_registry.get("write_file")
        assert tool.permission_level == "write"

    def test_edit_file_permission(self) -> None:
        tool = tool_registry.get("edit_file")
        assert tool.permission_level == "write"

    def test_list_files_permission(self) -> None:
        tool = tool_registry.get("list_files")
        assert tool.permission_level == "read"

    def test_apply_patch_permission(self) -> None:
        tool = tool_registry.get("apply_patch")
        assert tool.permission_level == "write"

    def test_multi_edit_permission(self) -> None:
        tool = tool_registry.get("multi_edit")
        assert tool.permission_level == "write"

    def test_read_file_schema_has_path(self) -> None:
        schema = tool_registry.get_schema("read_file")
        props = schema["function"]["parameters"]["properties"]
        assert "path" in props
        assert props["path"]["type"] == "string"

    def test_write_file_schema_has_content(self) -> None:
        schema = tool_registry.get_schema("write_file")
        props = schema["function"]["parameters"]["properties"]
        assert "path" in props
        assert "content" in props

    def test_edit_file_schema_has_old_new(self) -> None:
        schema = tool_registry.get_schema("edit_file")
        props = schema["function"]["parameters"]["properties"]
        assert "old_text" in props
        assert "new_text" in props

    def test_list_files_schema_has_pattern(self) -> None:
        schema = tool_registry.get_schema("list_files")
        props = schema["function"]["parameters"]["properties"]
        assert "path" in props
        assert "pattern" in props


# ------------------------------------------------------------------
# apply_patch tests
# ------------------------------------------------------------------


class TestApplyPatch:
    """Tests for the apply_patch tool."""

    async def test_apply_single_hunk(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("line1\nline2\nline3\n")  # type: ignore[union-attr]

        patch = """@@ -1,3 +1,3 @@
 line1
-line2
+line2_modified
 line3"""

        result = await tool_registry.execute("apply_patch", {"path": str(file), "patch": patch})
        assert result.success is True
        assert "1 hunk" in result.output
        assert file.read_text() == "line1\nline2_modified\nline3\n"  # type: ignore[union-attr]

    async def test_apply_multi_hunk(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("aaa\nbbb\nccc\nddd\neee\n")  # type: ignore[union-attr]

        patch = """@@ -1,2 +1,2 @@
 aaa
-bbb
+BBB
@@ -4,2 +4,2 @@
 ddd
-eee
+EEE"""

        result = await tool_registry.execute("apply_patch", {"path": str(file), "patch": patch})
        assert result.success is True
        assert "2 hunk" in result.output
        assert file.read_text() == "aaa\nBBB\nccc\nddd\nEEE\n"  # type: ignore[union-attr]

    async def test_file_not_found(self) -> None:
        result = await tool_registry.execute("apply_patch", {"path": "/nonexistent/file.py", "patch": "@@ -0,0 +1 @@\n+hello"})
        assert result.success is False
        assert "not found" in result.error

    async def test_directory_not_file(self, tmp_path: object) -> None:
        result = await tool_registry.execute("apply_patch", {"path": str(tmp_path), "patch": "@@ -0,0 +1 @@\n+hello"})  # type: ignore[arg-type]
        assert result.success is False
        assert "directory" in result.error

    async def test_no_hunks(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("hello\n")  # type: ignore[union-attr]

        result = await tool_registry.execute("apply_patch", {"path": str(file), "patch": "this is not a diff"})
        assert result.success is False
        assert "No valid hunks" in result.error

    async def test_hunk_does_not_match(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("hello\nworld\n")  # type: ignore[union-attr]

        patch = """@@ -1,2 +1,2 @@
 goodbye
-world
+universe"""

        result = await tool_registry.execute("apply_patch", {"path": str(file), "patch": patch})
        assert result.success is False
        assert "does not match" in result.error

    async def test_preserves_trailing_newline(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("aaa\nbbb\n")  # type: ignore[union-attr]

        patch = """@@ -1,2 +1,2 @@
 aaa
-bbb
+ccc"""

        result = await tool_registry.execute("apply_patch", {"path": str(file), "patch": patch})
        assert result.success is True
        content = file.read_text()  # type: ignore[union-attr]
        assert content.endswith("\n")
        assert content == "aaa\nccc\n"


# ------------------------------------------------------------------
# multi_edit tests
# ------------------------------------------------------------------


class TestMultiEdit:
    """Tests for the multi_edit tool."""

    async def test_single_edit(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("def foo(): pass\n")  # type: ignore[union-attr]

        result = await tool_registry.execute("multi_edit", {
            "path": str(file),
            "edits": [{"old_text": "def foo():", "new_text": "def bar():"}],
        })
        assert result.success is True
        assert "1 edit" in result.output
        assert file.read_text() == "def bar(): pass\n"  # type: ignore[union-attr]

    async def test_multiple_edits(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("a = 1\nb = 2\nc = 3\n")  # type: ignore[union-attr]

        edits = [
            {"old_text": "a = 1", "new_text": "a = 10"},
            {"old_text": "b = 2", "new_text": "b = 20"},
            {"old_text": "c = 3", "new_text": "c = 30"},
        ]
        result = await tool_registry.execute("multi_edit", {"path": str(file), "edits": edits})
        assert result.success is True
        assert "3 edit" in result.output
        assert file.read_text() == "a = 10\nb = 20\nc = 30\n"  # type: ignore[union-attr]

    async def test_no_edits(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("hello\n")  # type: ignore[union-attr]

        result = await tool_registry.execute("multi_edit", {"path": str(file), "edits": []})
        assert result.success is False
        assert "No edits" in result.error

    async def test_old_text_not_found(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("hello\n")  # type: ignore[union-attr]

        result = await tool_registry.execute("multi_edit", {
            "path": str(file),
            "edits": [{"old_text": "goodbye", "new_text": "hi"}],
        })
        assert result.success is False
        assert "not found" in result.error

    async def test_old_text_multiple_matches(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("a = 1\na = 2\n")  # type: ignore[union-attr]

        result = await tool_registry.execute("multi_edit", {
            "path": str(file),
            "edits": [{"old_text": "a = ", "new_text": "b = "}],
        })
        assert result.success is False
        assert "appears" in result.error

    async def test_file_not_found(self) -> None:
        result = await tool_registry.execute("multi_edit", {
            "path": "/nonexistent/file.py",
            "edits": [{"old_text": "a", "new_text": "b"}],
        })
        assert result.success is False
        assert "not found" in result.error

    async def test_validates_all_before_applying(self, tmp_path: object) -> None:
        p = tmp_path  # type: ignore[assignment]
        file = p / "test.py"  # type: ignore[union-attr]
        file.write_text("hello\n")  # type: ignore[union-attr]

        # Second edit will fail — first should not be applied
        edits = [
            {"old_text": "hello", "new_text": "world"},
            {"old_text": "nonexistent", "new_text": "gone"},
        ]
        result = await tool_registry.execute("multi_edit", {"path": str(file), "edits": edits})
        assert result.success is False
        # File should be unchanged because validation happens before application
        assert file.read_text() == "hello\n"  # type: ignore[union-attr]
