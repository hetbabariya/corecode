"""Tests for agent.workspace_index module."""

import tempfile
from pathlib import Path

from coding_agent.agent.workspace_index import WorkspaceIndex


class TestWorkspaceIndexScan:
    """Tests for WorkspaceIndex.scan()."""

    def test_scan_empty_directory(self, tmp_path: Path):
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.total_files == 0
        assert index.tree == {}

    def test_scan_finds_python_files(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "utils.py").write_text("def foo(): pass")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.total_files == 2
        assert "" in index.tree
        assert "main.py" in index.tree[""]
        assert index.languages.get("python", 0) == 2

    def test_scan_finds_subdirectories(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("x = 1")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("assert True")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.total_files == 2
        assert "src" in index.tree
        assert "tests" in index.tree
        assert "app.py" in index.tree["src"]

    def test_scan_ignores_pycache(self, tmp_path: Path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "module.cpython-312.pyc").write_bytes(b"\x00")
        (tmp_path / "main.py").write_text("x = 1")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.total_files == 1
        assert "__pycache__" not in index.tree

    def test_scan_ignores_node_modules(self, tmp_path: Path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg").mkdir()
        (tmp_path / "node_modules" / "pkg" / "index.js").write_text("x")
        (tmp_path / "app.js").write_text("y")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.total_files == 1

    def test_scan_ignores_git_dir(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        (tmp_path / "main.py").write_text("y")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.total_files == 1

    def test_scan_counts_languages(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        (tmp_path / "c.js").write_text("z")
        (tmp_path / "d.ts").write_text("w")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.languages["python"] == 2
        assert index.languages["javascript"] == 1
        assert index.languages["typescript"] == 1

    def test_scan_sets_last_scanned(self, tmp_path: Path):
        index = WorkspaceIndex()
        assert index.last_scanned is None
        index.scan(tmp_path)
        assert index.last_scanned is not None

    def test_scan_respects_max_files(self, tmp_path: Path):
        for i in range(10):
            (tmp_path / f"file_{i}.py").write_text(f"x = {i}")
        index = WorkspaceIndex()
        index.scan(tmp_path, max_files=3)
        assert index.total_files == 3


class TestWorkspaceIndexUpdate:
    """Tests for WorkspaceIndex.update_file()."""

    def test_update_created(self, tmp_path: Path):
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.total_files == 0
        index.update_file(tmp_path / "new.py", "created", workspace=tmp_path)
        assert index.total_files == 1
        assert "new.py" in index.tree.get("", [])

    def test_update_deleted(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.total_files == 1
        index.update_file(tmp_path / "main.py", "deleted", workspace=tmp_path)
        assert index.total_files == 0

    def test_update_deleted_nonexistent(self, tmp_path: Path):
        index = WorkspaceIndex()
        index.scan(tmp_path)
        index.update_file(tmp_path / "nope.py", "deleted", workspace=tmp_path)
        assert index.total_files == 0

    def test_update_modified_no_change(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        index.update_file(tmp_path / "main.py", "modified", workspace=tmp_path)
        assert index.total_files == 1

    def test_update_created_in_subdir(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        index = WorkspaceIndex()
        index.scan(tmp_path)
        index.update_file(tmp_path / "src" / "new.py", "created", workspace=tmp_path)
        assert index.total_files == 1
        assert "new.py" in index.tree.get("src", [])

    def test_update_cleans_empty_dirs(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        index.update_file(tmp_path / "src" / "a.py", "deleted", workspace=tmp_path)
        assert "src" not in index.tree


class TestWorkspaceIndexQuery:
    """Tests for query methods."""

    def test_to_summary_empty(self):
        index = WorkspaceIndex()
        assert "empty" in index.to_summary().lower()

    def test_to_summary_with_files(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x")
        (tmp_path / "utils.py").write_text("y")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        summary = index.to_summary()
        assert "main.py" in summary
        assert "utils.py" in summary

    def test_to_summary_max_files(self, tmp_path: Path):
        for i in range(10):
            (tmp_path / f"f{i}.py").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        summary = index.to_summary(max_files=3)
        assert "7 more files" in summary

    def test_get_language_stats(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        (tmp_path / "c.js").write_text("z")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        stats = index.get_language_stats()
        assert stats["python"] == 2
        assert stats["javascript"] == 1

    def test_search_files(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x")
        (tmp_path / "test_main.py").write_text("y")
        (tmp_path / "utils.py").write_text("z")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        results = index.search_files("main")
        assert len(results) == 2
        assert "main.py" in results
        assert "test_main.py" in results

    def test_search_files_case_insensitive(self, tmp_path: Path):
        (tmp_path / "Main.py").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        results = index.search_files("main")
        assert len(results) == 1

    def test_get_file_count(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.get_file_count() == 1

    def test_get_dir_count(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "src" / "a.py").write_text("x")
        (tmp_path / "tests" / "b.py").write_text("y")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert index.get_dir_count() == 2

    def test_to_dict(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        d = index.to_dict()
        assert d["total_files"] == 1
        assert d["total_lines"] >= 0
        assert d["last_scanned"] is not None


class TestExtToLang:
    """Tests for extension to language mapping."""

    def test_python(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert "python" in index.languages

    def test_javascript(self, tmp_path: Path):
        (tmp_path / "a.js").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert "javascript" in index.languages

    def test_typescript(self, tmp_path: Path):
        (tmp_path / "a.ts").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert "typescript" in index.languages

    def test_unknown_extension(self, tmp_path: Path):
        (tmp_path / "a.xyz").write_text("x")
        index = WorkspaceIndex()
        index.scan(tmp_path)
        assert "xyz" in index.languages
