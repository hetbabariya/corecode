"""Workspace index — lightweight file tree awareness for the agent.

Scans the workspace on startup to build an in-memory index of files,
directories, and language statistics. This avoids expensive tool calls
for basic workspace navigation.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coding_agent.logging import logger


# Directories always excluded from indexing
_IGNORE_DIRS = frozenset({
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pyright",
    ".tox",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
    ".hypothesis",
})

# Extension to language mapping (common types)
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".R": "r",
    ".m": "objective-c",
    ".mm": "objective-cpp",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".svg": "svg",
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".txt": "text",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".dockerfile": "dockerfile",
    ".tf": "terraform",
    ".hcl": "hcl",
    ".env": "dotenv",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "config",
    ".lock": "lock",
    ".log": "log",
}


@dataclass
class WorkspaceIndex:
    """Lightweight in-memory index of the workspace.

    Attributes
    ----------
    tree:
        Directory structure as ``{dir_path: [file_names]}``.
    languages:
        Language statistics as ``{language_name: file_count}``.
    total_files:
        Total number of indexed files.
    total_lines:
        Approximate total line count (sampled).
    last_scanned:
        Timestamp of the last full scan.
    """

    tree: dict[str, list[str]] = field(default_factory=dict)
    languages: dict[str, int] = field(default_factory=dict)
    total_files: int = 0
    total_lines: int = 0
    last_scanned: datetime | None = None

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self, workspace: Path, max_files: int = 10000) -> None:
        """Walk the workspace and build the index.

        Parameters
        ----------
        workspace:
            Root directory to scan.
        max_files:
            Stop scanning after this many files (safety limit).
        """
        workspace = workspace.resolve()
        scan_start = time.monotonic()
        tree: dict[str, list[str]] = {}
        lang_counter: Counter[str] = Counter()
        total_files = 0
        total_lines = 0
        line_sample_count = 0

        for root, dirs, files in os.walk(workspace):
            # Skip ignored directories
            dirs[:] = [
                d for d in dirs
                if d not in _IGNORE_DIRS and not d.startswith(".")
            ]

            root_path = Path(root)
            try:
                rel_dir = root_path.relative_to(workspace)
                dir_key = str(rel_dir) if str(rel_dir) != "." else ""
            except ValueError:
                continue

            if not files:
                continue

            tree[dir_key] = sorted(files)

            for fname in files:
                if total_files >= max_files:
                    break

                total_files += 1
                ext = root_path.joinpath(fname).suffix.lower()
                lang = _EXT_TO_LANG.get(ext, ext.lstrip(".") or "unknown")
                lang_counter[lang] += 1

                # Sample line counts (first 100 files)
                if line_sample_count < 100:
                    try:
                        fp = root_path / fname
                        if fp.stat().st_size < 1_000_000:  # skip >1MB files
                            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                                total_lines += sum(1 for _ in f)
                            line_sample_count += 1
                    except (OSError, UnicodeDecodeError):
                        pass

            if total_files >= max_files:
                break

        self.tree = tree
        self.languages = dict(lang_counter.most_common())
        self.total_files = total_files
        self.total_lines = total_lines
        self.last_scanned = datetime.now(timezone.utc)

        scan_duration = (time.monotonic() - scan_start) * 1000
        top_langs = list(self.languages.items())[:5]
        logger.info(
            "workspace_scan_complete",
            files=total_files,
            dirs=len(tree),
            duration_ms=round(scan_duration, 1),
            languages=top_langs,
        )

    # ------------------------------------------------------------------
    # Incremental updates
    # ------------------------------------------------------------------

    def update_file(self, path: Path, action: str, workspace: Path | None = None) -> None:
        """Update the index after a file is created, modified, or deleted.

        Parameters
        ----------
        path:
            Absolute path to the file.
        action:
            ``"created"``, ``"modified"``, or ``"deleted"``.
        workspace:
            Workspace root. If None, tries to infer from path.
        """
        if workspace is None:
            # Try to find workspace by looking for a known root marker
            workspace = Path(".")

        workspace = workspace.resolve()
        try:
            rel = path.resolve().relative_to(workspace)
        except ValueError:
            return

        dir_key = str(rel.parent) if str(rel.parent) != "." else ""
        fname = rel.name

        if action == "deleted":
            if dir_key in self.tree and fname in self.tree[dir_key]:
                self.tree[dir_key].remove(fname)
                if not self.tree[dir_key]:
                    del self.tree[dir_key]
                self.total_files = max(0, self.total_files - 1)
        elif action == "created":
            if dir_key not in self.tree:
                self.tree[dir_key] = []
            if fname not in self.tree[dir_key]:
                self.tree[dir_key].append(fname)
                self.tree[dir_key].sort()
                self.total_files += 1
                # Update language count
                ext = path.suffix.lower()
                lang = _EXT_TO_LANG.get(ext, ext.lstrip(".") or "unknown")
                self.languages[lang] = self.languages.get(lang, 0) + 1

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def to_summary(self, max_files: int = 100) -> str:
        """Format the file tree as a readable string for the system prompt.

        Parameters
        ----------
        max_files:
            Maximum number of files to include in the output.
        """
        if not self.tree:
            return "Workspace is empty or not indexed."

        lines: list[str] = []
        file_count = 0

        for dir_key in sorted(self.tree.keys()):
            files = self.tree[dir_key]
            if dir_key:
                lines.append(f"\n{dir_key}/")
            for fname in files:
                if file_count >= max_files:
                    remaining = self.total_files - file_count
                    if remaining > 0:
                        lines.append(f"\n  ... and {remaining} more files")
                    break
                lines.append(f"  {fname}")
                file_count += 1
            if file_count >= max_files:
                break

        return "\n".join(lines)

    def get_language_stats(self) -> dict[str, int]:
        """Return language statistics sorted by file count."""
        return dict(sorted(self.languages.items(), key=lambda x: -x[1]))

    def search_files(self, pattern: str) -> list[str]:
        """Search for files matching a pattern (simple substring match).

        Parameters
        ----------
        pattern:
            Substring to match against file names (case-insensitive).
        """
        pattern_lower = pattern.lower()
        results: list[str] = []
        for dir_key, files in self.tree.items():
            for fname in files:
                if pattern_lower in fname.lower():
                    if dir_key:
                        results.append(f"{dir_key}/{fname}")
                    else:
                        results.append(fname)
        return sorted(results)

    def get_file_count(self) -> int:
        """Return total file count."""
        return self.total_files

    def get_dir_count(self) -> int:
        """Return total directory count."""
        return len(self.tree)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the index for JSON storage."""
        return {
            "tree": self.tree,
            "languages": self.languages,
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "last_scanned": self.last_scanned.isoformat() if self.last_scanned else None,
        }
