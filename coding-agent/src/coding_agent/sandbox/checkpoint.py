"""Checkpoint system for undo/redo persistence using git."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Checkpoint:
    """Represents a git checkpoint."""

    id: str
    label: str
    timestamp: float
    commit_hash: str
    parent_hash: str = ""
    files_changed: int = 0


class CheckpointManager:
    """Manages git-based checkpoints for undo/redo functionality."""

    # File to track session checkpoints
    CHECKPOINT_FILE = ".coding-agent-checkpoints.json"

    def __init__(self, workspace: Path | str):
        self.workspace = Path(workspace)
        self._session_checkpoints: list[Checkpoint] = []
        self._check_git()
        self._load_session_checkpoints()

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

    def _get_current_hash(self) -> str:
        """Get the current HEAD commit hash."""
        result = self._run_git("rev-parse", "HEAD", check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    def _load_session_checkpoints(self) -> None:
        """Load session checkpoints from file."""
        checkpoint_file = self.workspace / self.CHECKPOINT_FILE
        if checkpoint_file.exists():
            try:
                data = json.loads(checkpoint_file.read_text())
                self._session_checkpoints = [
                    Checkpoint(**cp) for cp in data.get("checkpoints", [])
                ]
            except (json.JSONDecodeError, TypeError):
                self._session_checkpoints = []

    def _save_session_checkpoints(self) -> None:
        """Save session checkpoints to file."""
        checkpoint_file = self.workspace / self.CHECKPOINT_FILE
        data = {
            "checkpoints": [asdict(cp) for cp in self._session_checkpoints]
        }
        checkpoint_file.write_text(json.dumps(data, indent=2))

    def create_checkpoint(self, label: str) -> Checkpoint:
        """Create a new checkpoint by committing current changes."""
        # Get the current HEAD before committing (this becomes the parent)
        parent_hash = self._get_current_hash()

        # Stage all changes
        self._run_git("add", "-A")

        # Check if there are changes to commit
        status = self._run_git("status", "--porcelain")
        if not status.stdout.strip():
            # No changes - create empty commit to mark the point
            self._run_git(
                "commit",
                "--allow-empty",
                "-m",
                f"checkpoint: {label}",
            )
        else:
            self._run_git(
                "commit",
                "-m",
                f"checkpoint: {label}",
            )

        # Get new commit hash
        commit_hash = self._run_git("rev-parse", "HEAD").stdout.strip()

        # Count files changed
        diff_stat = self._run_git("diff", "--stat", "HEAD~1", "HEAD", check=False)
        files_changed = len(diff_stat.stdout.strip().split("\n")) if diff_stat.stdout.strip() else 0

        checkpoint = Checkpoint(
            id=commit_hash[:8],
            label=label,
            timestamp=time.time(),
            commit_hash=commit_hash,
            parent_hash=parent_hash,
            files_changed=files_changed,
        )

        # Track in session
        self._session_checkpoints.append(checkpoint)
        self._save_session_checkpoints()

        return checkpoint

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """Restore to a specific checkpoint."""
        # Find the full commit hash
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
        """Undo the last checkpoint within the current session."""
        if not self._session_checkpoints:
            return None

        # Get the last checkpoint from this session
        last_cp = self._session_checkpoints[-1]

        # Reset to the parent of that checkpoint
        if last_cp.parent_hash:
            result = self._run_git("reset", "--hard", last_cp.parent_hash, check=False)
            if result.returncode == 0:
                # Remove from session tracking
                self._session_checkpoints.pop()
                self._save_session_checkpoints()
                return last_cp
        else:
            # No parent - try HEAD~1
            result = self._run_git("reset", "--hard", "HEAD~1", check=False)
            if result.returncode == 0:
                self._session_checkpoints.pop()
                self._save_session_checkpoints()
                return last_cp

        return None

    def redo(self) -> Optional[Checkpoint]:
        """Redo is not fully supported yet."""
        return None

    def clear_session(self) -> None:
        """Clear session checkpoints."""
        self._session_checkpoints = []
        self._save_session_checkpoints()
