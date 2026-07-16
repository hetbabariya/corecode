"""Checkpoint system for undo/redo persistence using git."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Checkpoint:
    """Represents a git checkpoint."""

    id: str
    label: str
    timestamp: float
    commit_hash: str
    files_changed: int = 0


class CheckpointManager:
    """Manages git-based checkpoints for undo/redo functionality."""

    def __init__(self, workspace: Path | str):
        self.workspace = Path(workspace)
        self._check_git()

    def _check_git(self) -> None:
        """Verify we're in a git repository."""
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.workspace,
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError(f"Not a git repository: {self.workspace}")

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command."""
        return subprocess.run(
            ["git"] + list(args),
            cwd=self.workspace,
            capture_output=True,
            text=True,
            check=check,
        )

    def create_checkpoint(self, label: str) -> Checkpoint:
        """Create a new checkpoint by committing current changes."""
        # Stage all changes
        self._run_git("add", "-A")

        # Check if there are changes to commit
        status = self._run_git("status", "--porcelain")
        if not status.stdout.strip():
            # No changes to commit - create empty commit
            result = self._run_git(
                "commit",
                "--allow-empty",
                "-m",
                f"checkpoint: {label}",
            )
        else:
            result = self._run_git(
                "commit",
                "-m",
                f"checkpoint: {label}",
            )

        # Get commit hash
        commit_hash = self._run_git("rev-parse", "HEAD").stdout.strip()

        # Count files changed
        diff_stat = self._run_git("diff", "--stat", "HEAD~1", "HEAD", check=False)
        files_changed = len(diff_stat.stdout.strip().split("\n")) if diff_stat.stdout.strip() else 0

        return Checkpoint(
            id=commit_hash[:8],
            label=label,
            timestamp=time.time(),
            commit_hash=commit_hash,
            files_changed=files_changed,
        )

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """Restore to a specific checkpoint."""
        # Find the full commit hash using cat-file
        result = self._run_git("log", "--format=%H", "--all", check=False)
        if result.returncode != 0:
            return False

        for line in result.stdout.strip().split("\n"):
            if line.startswith(checkpoint_id):
                # Reset to that commit
                self._run_git("reset", "--hard", line)
                return True
        return False

    def list_checkpoints(self, limit: int = 20) -> list[Checkpoint]:
        """List recent checkpoints."""
        result = self._run_git(
            "log",
            f"--max-count={limit}",
            "--format=%H|%s|%at",
            "--grep=^checkpoint:",
            check=False,
        )

        checkpoints = []
        if result.returncode != 0:
            return checkpoints

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) >= 3:
                commit_hash, message, timestamp = parts
                label = message.replace("checkpoint: ", "")
                checkpoints.append(
                    Checkpoint(
                        id=commit_hash[:8],
                        label=label,
                        timestamp=float(timestamp),
                        commit_hash=commit_hash,
                    )
                )

        return checkpoints

    def get_current_checkpoint(self) -> Optional[Checkpoint]:
        """Get the current HEAD as a checkpoint."""
        result = self._run_git("log", "-1", "--format=%H|%s|%at")
        if result.stdout.strip():
            parts = result.stdout.strip().split("|", 2)
            if len(parts) >= 3:
                commit_hash, message, timestamp = parts
                label = message.replace("checkpoint: ", "")
                return Checkpoint(
                    id=commit_hash[:8],
                    label=label,
                    timestamp=float(timestamp),
                    commit_hash=commit_hash,
                )
        return None

    def undo(self) -> Optional[Checkpoint]:
        """Undo the last checkpoint by resetting to the previous one."""
        # Get the last two checkpoints
        checkpoints = self.list_checkpoints(limit=2)
        if len(checkpoints) < 2:
            return None

        # Restore to the second-to-last checkpoint
        target = checkpoints[1]
        if self.restore_checkpoint(target.id):
            return target
        return None

    def redo(self) -> Optional[Checkpoint]:
        """Redo by moving forward one checkpoint."""
        # This is tricky with git - we'd need to reflog
        # For now, return None (redo not fully supported)
        return None
