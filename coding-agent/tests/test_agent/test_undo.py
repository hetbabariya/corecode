"""Comprehensive tests for the undo/redo system.

Tests cover:
- UndoEntry and UndoManager core logic
- File creation, modification, and deletion undo/redo
- Disk persistence and crash recovery
- Stack limits and eviction
- Session management
"""

import json
import time
from pathlib import Path

import pytest

from coding_agent.agent.undo import UndoEntry, UndoManager
from coding_agent.agent.disk_store import DiskStore, StoredEntry, StoredStack


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    return tmp_path


@pytest.fixture
def manager(workspace: Path) -> UndoManager:
    """Create a fresh UndoManager for testing."""
    return UndoManager(workspace, max_entries=50)


# ---------------------------------------------------------------------------
# UndoEntry tests
# ---------------------------------------------------------------------------

class TestUndoEntry:
    """Tests for UndoEntry data class."""

    def test_entry_auto_generates_id(self) -> None:
        entry = UndoEntry(tool_name="write", file_path="a.py", before="", after="x")
        assert entry.id
        assert len(entry.id) == 8

    def test_entry_auto_generates_timestamp(self) -> None:
        before = time.time()
        entry = UndoEntry(tool_name="write", file_path="a.py", before="", after="x")
        after = time.time()
        assert before <= entry.timestamp <= after

    def test_entry_preserves_provided_id(self) -> None:
        entry = UndoEntry(tool_name="write", file_path="a.py", before="", after="x", id="custom123")
        assert entry.id == "custom123"


# ---------------------------------------------------------------------------
# UndoManager — push / undo / redo basics
# ---------------------------------------------------------------------------

class TestUndoManagerBasics:
    """Tests for UndoManager push, undo, redo."""

    def test_undo_empty_stack(self, manager: UndoManager) -> None:
        assert manager.undo() is None

    def test_redo_empty_stack(self, manager: UndoManager) -> None:
        assert manager.redo() is None

    def test_push_and_undo(self, manager: UndoManager) -> None:
        entry = UndoEntry(tool_name="write_file", file_path="a.py", before="", after="content")
        manager.push(entry)

        result = manager.undo()
        assert result is not None
        assert result.id == entry.id
        assert manager.undo_count == 0
        assert manager.redo_count == 1

    def test_undo_then_redo(self, manager: UndoManager) -> None:
        entry = UndoEntry(tool_name="write_file", file_path="a.py", before="", after="content")
        manager.push(entry)

        manager.undo()
        result = manager.redo()
        assert result is not None
        assert result.id == entry.id
        assert manager.undo_count == 1
        assert manager.redo_count == 0

    def test_redo_clears_on_new_push(self, manager: UndoManager) -> None:
        e1 = UndoEntry(tool_name="w", file_path="a.py", before="", after="1")
        e2 = UndoEntry(tool_name="w", file_path="b.py", before="", after="2")
        manager.push(e1)
        manager.undo()
        assert manager.can_redo

        manager.push(e2)
        assert not manager.can_redo
        # e1 was in redo, new push clears redo, so only e2 remains
        assert manager.undo_count == 1

    def test_peek_does_not_pop(self, manager: UndoManager) -> None:
        entry = UndoEntry(tool_name="w", file_path="a.py", before="", after="x")
        manager.push(entry)

        peeked = manager.peek_undo()
        assert peeked is not None
        assert manager.undo_count == 1  # still there

    def test_can_undo_redo_properties(self, manager: UndoManager) -> None:
        assert not manager.can_undo
        assert not manager.can_redo

        manager.push(UndoEntry(tool_name="w", file_path="a.py", before="", after="x"))
        assert manager.can_undo
        assert not manager.can_redo

        manager.undo()
        assert not manager.can_undo
        assert manager.can_redo

    def test_list_entries(self, manager: UndoManager) -> None:
        for i in range(5):
            manager.push(UndoEntry(tool_name="w", file_path=f"f{i}.py", before="", after=str(i)))

        entries = manager.list_entries(limit=3)
        assert len(entries) == 3
        # Newest first
        assert entries[0].file_path == "f4.py"
        assert entries[2].file_path == "f2.py"

    def test_clear(self, manager: UndoManager) -> None:
        manager.push(UndoEntry(tool_name="w", file_path="a.py", before="", after="x"))
        manager.undo()
        manager.clear()

        assert manager.undo_count == 0
        assert manager.redo_count == 0


# ---------------------------------------------------------------------------
# Stack overflow / eviction
# ---------------------------------------------------------------------------

class TestStackOverflow:
    """Tests for max entry limit."""

    def test_evicts_oldest(self, workspace: Path) -> None:
        mgr = UndoManager(workspace, max_entries=3)
        entries = []
        for i in range(5):
            e = UndoEntry(tool_name="w", file_path=f"f{i}.py", before="", after=str(i))
            mgr.push(e)
            entries.append(e)

        assert mgr.undo_count == 3
        # Oldest two (f0, f1) should be evicted
        top = mgr.peek_undo()
        assert top is not None
        assert top.file_path == "f4.py"


# ---------------------------------------------------------------------------
# File system apply (undo/redo)
# ---------------------------------------------------------------------------

class TestApplyEntry:
    """Tests for UndoManager.apply_entry file system operations."""

    def test_undo_creates_file_then_removes(self, workspace: Path) -> None:
        """Undo of a file creation should remove the file."""
        file_path = workspace / "new.py"
        entry = UndoEntry(
            tool_name="write_file",
            file_path=str(file_path),
            before="",
            after="print('hello')",
        )
        # Simulate the file was created
        file_path.write_text("print('hello')")

        # Undo should remove it
        UndoManager.apply_entry(entry, redo=False)
        assert not file_path.exists()

    def test_redo_recreates_file(self, workspace: Path) -> None:
        """Redo of a file creation should recreate the file."""
        file_path = workspace / "new.py"
        entry = UndoEntry(
            tool_name="write_file",
            file_path=str(file_path),
            before="",
            after="print('hello')",
        )

        UndoManager.apply_entry(entry, redo=True)
        assert file_path.exists()
        assert file_path.read_text() == "print('hello')"

    def test_undo_modifies_file(self, workspace: Path) -> None:
        """Undo of a modification should restore original content."""
        file_path = workspace / "edit.py"
        file_path.write_text("original")

        entry = UndoEntry(
            tool_name="edit_file",
            file_path=str(file_path),
            before="original",
            after="modified",
        )
        file_path.write_text("modified")

        UndoManager.apply_entry(entry, redo=False)
        assert file_path.read_text() == "original"

    def test_redo_modifies_file(self, workspace: Path) -> None:
        """Redo of a modification should reapply the edit."""
        file_path = workspace / "edit.py"
        file_path.write_text("original")

        entry = UndoEntry(
            tool_name="edit_file",
            file_path=str(file_path),
            before="original",
            after="modified",
        )

        UndoManager.apply_entry(entry, redo=True)
        assert file_path.read_text() == "modified"

    def test_undo_deletes_file(self, workspace: Path) -> None:
        """Undo of a deletion should restore the file."""
        file_path = workspace / "deleted.py"
        content = "was here"

        entry = UndoEntry(
            tool_name="write_file",
            file_path=str(file_path),
            before=content,
            after="",
        )
        # File is deleted (simulated)
        if file_path.exists():
            file_path.unlink()

        UndoManager.apply_entry(entry, redo=False)
        assert file_path.exists()
        assert file_path.read_text() == content

    def test_redo_deletes_file(self, workspace: Path) -> None:
        """Redo of a deletion should remove the file."""
        file_path = workspace / "to_delete.py"
        file_path.write_text("bye")

        entry = UndoEntry(
            tool_name="write_file",
            file_path=str(file_path),
            before="",
            after="",
        )

        UndoManager.apply_entry(entry, redo=True)
        assert not file_path.exists()

    def test_undo_creates_parent_dirs(self, workspace: Path) -> None:
        """Undo should create parent directories if needed."""
        file_path = workspace / "sub" / "dir" / "file.py"

        entry = UndoEntry(
            tool_name="write_file",
            file_path=str(file_path),
            before="",
            after="content",
        )

        UndoManager.apply_entry(entry, redo=True)
        assert file_path.exists()
        assert file_path.read_text() == "content"


# ---------------------------------------------------------------------------
# Disk persistence
# ---------------------------------------------------------------------------

class TestDiskPersistence:
    """Tests for disk store and persistence across sessions."""

    def test_save_and_load_stack(self, workspace: Path) -> None:
        store = DiskStore(workspace)
        stack = StoredStack(
            session_id="test123",
            created_at=time.time(),
            undo_ids=["e1", "e2"],
            redo_ids=[],
        )
        store.save_stack(stack)
        loaded = store.load_stack()

        assert loaded is not None
        assert loaded.session_id == "test123"
        assert loaded.undo_ids == ["e1", "e2"]

    def test_save_and_load_entry(self, workspace: Path) -> None:
        store = DiskStore(workspace)
        entry = StoredEntry(
            id="abc12345",
            tool_name="write_file",
            file_path="test.py",
            before="old",
            after="new",
            description="test entry",
            timestamp=time.time(),
        )
        store.save_entry(entry)
        loaded = store.load_entry("abc12345")

        assert loaded is not None
        assert loaded.tool_name == "write_file"
        assert loaded.before == "old"
        assert loaded.after == "new"

    def test_delete_entry(self, workspace: Path) -> None:
        store = DiskStore(workspace)
        entry = StoredEntry(
            id="del12345",
            tool_name="w",
            file_path="x.py",
            before="",
            after="y",
            description="",
            timestamp=time.time(),
        )
        store.save_entry(entry)
        store.delete_entry("del12345")
        assert store.load_entry("del12345") is None

    def test_manager_persists_and_resumes(self, workspace: Path) -> None:
        """Test that UndoManager persists to disk and can resume."""
        mgr1 = UndoManager(workspace)
        mgr1.init_session()
        session_id = mgr1.session_id

        mgr1.push(UndoEntry(tool_name="w", file_path="a.py", before="", after="1"))
        mgr1.push(UndoEntry(tool_name="w", file_path="b.py", before="", after="2"))

        # Create new manager (simulates restart)
        mgr2 = UndoManager(workspace)
        mgr2.init_session()

        assert mgr2.session_id == session_id
        assert mgr2.undo_count == 2
        assert mgr2.can_undo

        # Undo should work
        entry = mgr2.undo()
        assert entry is not None
        assert entry.file_path == "b.py"

    def test_manager_new_session(self, workspace: Path) -> None:
        """Test that a fresh workspace gets a new session."""
        mgr = UndoManager(workspace)
        session_id = mgr.init_session()
        assert session_id
        assert mgr.session_id == session_id

    def test_list_entry_ids(self, workspace: Path) -> None:
        store = DiskStore(workspace)
        for i in range(3):
            store.save_entry(StoredEntry(
                id=f"entry{i}",
                tool_name="w",
                file_path=f"f{i}.py",
                before="",
                after="x",
                description="",
                timestamp=time.time(),
            ))
        ids = store.list_entry_ids()
        assert len(ids) == 3
        assert "entry0" in ids


# ---------------------------------------------------------------------------
# Integration: full undo/redo cycle
# ---------------------------------------------------------------------------

class TestFullCycle:
    """Integration tests for complete undo/redo workflows."""

    def test_write_file_undo_redo_cycle(self, workspace: Path) -> None:
        """Full cycle: create file, undo removes it, redo recreates it."""
        mgr = UndoManager(workspace)
        mgr.init_session()

        file_path = workspace / "test.py"
        content = "print('hello')"

        # Simulate write_file tool: capture before (empty), write, push undo
        before = ""
        file_path.write_text(content)
        mgr.push(UndoEntry(
            tool_name="write_file",
            file_path=str(file_path),
            before=before,
            after=content,
            description="write test.py",
        ))

        assert file_path.exists()

        # Undo
        entry = mgr.undo()
        assert entry is not None
        UndoManager.apply_entry(entry, redo=False)
        assert not file_path.exists()

        # Redo
        entry = mgr.redo()
        assert entry is not None
        UndoManager.apply_entry(entry, redo=True)
        assert file_path.exists()
        assert file_path.read_text() == content

    def test_edit_file_undo_redo_cycle(self, workspace: Path) -> None:
        """Full cycle: edit file, undo restores, redo reapplies."""
        mgr = UndoManager(workspace)
        mgr.init_session()

        file_path = workspace / "edit.py"
        original = "line1\nline2\n"
        modified = "line1\nchanged\n"

        file_path.write_text(original)
        mgr.push(UndoEntry(
            tool_name="edit_file",
            file_path=str(file_path),
            before=original,
            after=modified,
            description="edit edit.py",
        ))
        file_path.write_text(modified)

        # Undo
        entry = mgr.undo()
        UndoManager.apply_entry(entry, redo=False)
        assert file_path.read_text() == original

        # Redo
        entry = mgr.redo()
        UndoManager.apply_entry(entry, redo=True)
        assert file_path.read_text() == modified

    def test_multiple_files_single_undo(self, workspace: Path) -> None:
        """Simulate multi_edit: one undo entry can affect one file with multiple changes."""
        mgr = UndoManager(workspace)
        mgr.init_session()

        file_path = workspace / "multi.py"
        original = "a\nb\nc\n"
        after_multi = "x\ny\nz\n"

        file_path.write_text(original)
        mgr.push(UndoEntry(
            tool_name="multi_edit",
            file_path=str(file_path),
            before=original,
            after=after_multi,
            description="multi-edit multi.py",
        ))
        file_path.write_text(after_multi)

        entry = mgr.undo()
        UndoManager.apply_entry(entry, redo=False)
        assert file_path.read_text() == original

    def test_undo_respects_max_entries(self, workspace: Path) -> None:
        """Ensure oldest entries are evicted when max is reached."""
        mgr = UndoManager(workspace, max_entries=3)
        mgr.init_session()

        for i in range(5):
            mgr.push(UndoEntry(
                tool_name="w",
                file_path=f"f{i}.py",
                before="",
                after=str(i),
            ))

        assert mgr.undo_count == 3

        # Verify the remaining entries are f4, f3, f2 (newest first)
        entries = mgr.list_entries()
        assert [e.file_path for e in entries] == ["f4.py", "f3.py", "f2.py"]

    def test_consecutive_undos(self, workspace: Path) -> None:
        """Multiple consecutive undos should work correctly."""
        mgr = UndoManager(workspace)
        mgr.init_session()

        files = []
        for i in range(3):
            fp = workspace / f"f{i}.py"
            fp.write_text(str(i))
            mgr.push(UndoEntry(
                tool_name="w",
                file_path=str(fp),
                before="",
                after=str(i),
            ))
            files.append(fp)

        # Undo all three
        for _ in range(3):
            entry = mgr.undo()
            assert entry is not None
            UndoManager.apply_entry(entry, redo=False)

        for fp in files:
            assert not fp.exists()

        # Nothing left to undo
        assert mgr.undo() is None

    def test_consecutive_redos(self, workspace: Path) -> None:
        """Multiple consecutive redos should work correctly."""
        mgr = UndoManager(workspace)
        mgr.init_session()

        files = []
        for i in range(3):
            fp = workspace / f"f{i}.py"
            mgr.push(UndoEntry(
                tool_name="w",
                file_path=str(fp),
                before="",
                after=str(i),
            ))
            files.append(fp)

        # Undo all
        for _ in range(3):
            mgr.undo()

        # Redo all
        for i in range(3):
            entry = mgr.redo()
            assert entry is not None
            UndoManager.apply_entry(entry, redo=True)
            assert files[i].exists()
            assert files[i].read_text() == str(i)
