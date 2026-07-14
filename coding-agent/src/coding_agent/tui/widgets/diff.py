"""Diff rendering widget ΓÇö renders file edits as colored git diff."""

from __future__ import annotations

import difflib
import re

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

# Max consecutive context lines before collapsing
_CONTEXT_COLLAPSE_THRESHOLD = 5


class DiffLine(Static):
    """A single line of diff output with optional line numbers."""

    def __init__(
        self, prefix: str, content: str, kind: str,
        old_num: int | None = None, new_num: int | None = None,
    ) -> None:
        if old_num is not None and new_num is not None:
            line_info = f"{old_num:>4} {new_num:>4} "
        elif old_num is not None:
            line_info = f"{old_num:>4}      "
        elif new_num is not None:
            line_info = f"     {new_num:>4} "
        else:
            line_info = ""
        super().__init__(f"{line_info}{prefix}{content}")
        self.add_class("diff-line")
        if kind == "add":
            self.add_class("diff-add")
        elif kind == "del":
            self.add_class("diff-del")
        elif kind == "ctx":
            self.add_class("diff-ctx")
        elif kind == "hunk":
            self.add_class("diff-hunk")


class DiffWidget(VerticalScroll):
    """Renders a unified diff between two file contents.

    Usage::

        widget = DiffWidget.from_strings(old_text, new_text, filename="main.py")
    """

    def __init__(self, filename: str = "", **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.filename = filename
        self._pending_lines: list[tuple[str, str, str, int | None, int | None]] = []

    def compose(self) -> ComposeResult:
        if self.filename:
            yield Static(f"  {self.filename}", classes="diff-header")
        yield from ()

    @classmethod
    def from_strings(
        cls,
        old: str,
        new: str,
        filename: str = "",
    ) -> DiffWidget:
        """Create a diff widget from two strings."""
        widget = cls(filename=filename)
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{filename}" if filename else "a/",
            tofile=f"b/{filename}" if filename else "b/",
            lineterm="",
        ))

        old_num = 0
        new_num = 0
        context_run: list[tuple[str, str, str, int | None, int | None]] = []

        for line in diff:
            line_stripped = line.rstrip("\n\r")

            if line_stripped.startswith("+++") or line_stripped.startswith("---"):
                kind = "hunk"
                prefix = "  "
                widget._pending_lines.append((prefix, line_stripped, kind, None, None))
                continue

            hunk_match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line_stripped)
            if hunk_match:
                # Flush any accumulated context run
                widget._flush_context(context_run)
                context_run = []
                old_num = int(hunk_match.group(1))
                new_num = int(hunk_match.group(2))
                kind = "hunk"
                prefix = "  "
                widget._pending_lines.append((prefix, line_stripped, kind, None, None))
                continue

            if line_stripped.startswith("+"):
                widget._flush_context(context_run)
                context_run = []
                kind = "add"
                prefix = "+ "
                content = line_stripped[1:]
                widget._pending_lines.append((prefix, content, kind, None, new_num))
                new_num += 1
            elif line_stripped.startswith("-"):
                widget._flush_context(context_run)
                context_run = []
                kind = "del"
                prefix = "- "
                content = line_stripped[1:]
                widget._pending_lines.append((prefix, content, kind, old_num, None))
                old_num += 1
            else:
                kind = "ctx"
                prefix = "  "
                content = line_stripped.lstrip()
                context_run.append((prefix, content, kind, old_num, new_num))
                old_num += 1
                new_num += 1

        widget._flush_context(context_run)
        return widget

    def _flush_context(
        self,
        run: list[tuple[str, str, str, int | None, int | None]],
    ) -> None:
        """Flush accumulated context lines, collapsing long runs."""
        if len(run) <= _CONTEXT_COLLAPSE_THRESHOLD:
            self._pending_lines.extend(run)
        else:
            # Keep first 2 and last 2, collapse the rest
            self._pending_lines.extend(run[:2])
            hidden = len(run) - 4
            self._pending_lines.append(
                (" ", f"... {hidden} lines hidden ...", "hunk", None, None)
            )
            self._pending_lines.extend(run[-2:])

    def _on_mount(self) -> None:
        """Mount diff lines after widget is mounted."""
        for prefix, content, kind, old_num, new_num in self._pending_lines:
            self.mount(DiffLine(prefix, content, kind, old_num, new_num))
