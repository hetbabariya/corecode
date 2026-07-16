"""Tests for checkpoint system."""

import tempfile
from pathlib import Path

import pytest

from coding_agent.sandbox.checkpoint import CheckpointManager


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    return tmp_path


class TestCheckpointManager:
    """Tests for CheckpointManager."""

    def test_create_checkpoint(self, git_repo: Path) -> None:
        """Test creating a checkpoint."""
        # Create a file
        (git_repo / "test.txt").write_text("hello")

        manager = CheckpointManager(git_repo)
        checkpoint = manager.create_checkpoint("test checkpoint")

        assert checkpoint.id
        assert checkpoint.label == "test checkpoint"
        assert checkpoint.commit_hash

    def test_list_checkpoints(self, git_repo: Path) -> None:
        """Test listing checkpoints."""
        manager = CheckpointManager(git_repo)

        # Create some checkpoints
        (git_repo / "file1.txt").write_text("content1")
        manager.create_checkpoint("first")

        (git_repo / "file2.txt").write_text("content2")
        manager.create_checkpoint("second")

        checkpoints = manager.list_checkpoints()
        assert len(checkpoints) == 2
        assert checkpoints[0].label == "second"
        assert checkpoints[1].label == "first"

    def test_restore_checkpoint(self, git_repo: Path) -> None:
        """Test restoring to a checkpoint."""
        manager = CheckpointManager(git_repo)

        # Create first checkpoint
        (git_repo / "test.txt").write_text("version1")
        cp1 = manager.create_checkpoint("version 1")

        # Create second checkpoint
        (git_repo / "test.txt").write_text("version2")
        cp2 = manager.create_checkpoint("version 2")

        # Restore to first checkpoint
        result = manager.restore_checkpoint(cp1.id)
        assert result is True

        # Verify file is restored
        content = (git_repo / "test.txt").read_text()
        assert content == "version1"

    def test_undo(self, git_repo: Path) -> None:
        """Test undo functionality."""
        manager = CheckpointManager(git_repo)

        # Create first checkpoint
        (git_repo / "test.txt").write_text("version1")
        manager.create_checkpoint("version 1")

        # Create second checkpoint
        (git_repo / "test.txt").write_text("version2")
        manager.create_checkpoint("version 2")

        # Undo
        checkpoint = manager.undo()
        assert checkpoint is not None
        assert checkpoint.label == "version 1"

        # Verify file is restored
        content = (git_repo / "test.txt").read_text()
        assert content == "version1"

    def test_undo_no_checkpoints(self, git_repo: Path) -> None:
        """Test undo with no checkpoints."""
        manager = CheckpointManager(git_repo)
        checkpoint = manager.undo()
        assert checkpoint is None

    def test_list_checkpoints_empty(self, git_repo: Path) -> None:
        """Test listing checkpoints when none exist."""
        manager = CheckpointManager(git_repo)
        checkpoints = manager.list_checkpoints()
        assert len(checkpoints) == 0
