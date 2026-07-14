"""Post-edit verification — automatically checks code after changes.

After every edit_file or write_file call, runs:
1. Syntax check (language-specific)
2. Linter (if configured)
3. Tests (if a test file exists for the changed file)

Verification results are fed back to the LLM so it can fix issues.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coding_agent.logging import logger


@dataclass
class CheckResult:
    """Result of a single verification check."""

    passed: bool
    tool: str  # "syntax" | "lint" | "tests"
    output: str
    duration_ms: float = 0.0


@dataclass
class VerificationResult:
    """Aggregated result of all verification checks for a file."""

    file_path: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks) if self.checks else True

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def to_feedback(self) -> str:
        """Format verification results as feedback for the LLM."""
        if not self.checks:
            return ""

        if self.all_passed:
            return f"Verification passed for {self.file_path}."

        parts = [f"Verification failed for {self.file_path}:"]
        for check in self.failed_checks:
            output_preview = check.output[:500] if check.output else "(no output)"
            parts.append(f"  [{check.tool}] {output_preview}")
        return "\n".join(parts)


# Language detection from file extension
_EXT_TO_CHECKER: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
}


class PostEditVerifier:
    """Runs verification checks after file edits.

    Usage::

        verifier = PostEditVerifier(workspace=Path("."))
        result = await verifier.verify(Path("src/main.py"))
        if not result.all_passed:
            print(result.to_feedback())
    """

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = (workspace or Path(".")).resolve()

    async def verify(self, file_path: Path) -> VerificationResult:
        """Run all applicable checks on a file.

        Parameters
        ----------
        file_path:
            Absolute or relative path to the file that was edited.
        """
        file_path = file_path.resolve()
        result = VerificationResult(file_path=str(file_path))

        if not file_path.exists():
            logger.debug("verify_file_not_found", path=str(file_path))
            return result

        ext = file_path.suffix.lower()
        language = _EXT_TO_CHECKER.get(ext)

        if language is None:
            logger.debug("verify_unsupported_ext", path=str(file_path), ext=ext)
            return result

        logger.info("verify_started", path=str(file_path), language=language)

        # Run checks concurrently
        checks = await asyncio.gather(
            self._check_syntax(file_path, language),
            self._check_lint(file_path, language),
            self._check_tests(file_path, language),
        )

        result.checks = [c for c in checks if c is not None]

        for check in result.checks:
            logger.debug(
                "verify_check_result",
                path=str(file_path),
                tool=check.tool,
                passed=check.passed,
                duration_ms=round(check.duration_ms, 1),
            )

        if result.all_passed:
            logger.info("verify_passed", path=str(file_path), checks=len(result.checks))
        else:
            logger.warning(
                "verify_failed",
                path=str(file_path),
                failed=len(result.failed_checks),
                checks=len(result.checks),
            )

        return result

    async def _check_syntax(
        self, file_path: Path, language: str
    ) -> CheckResult | None:
        """Run language-specific syntax check."""
        import time

        start = time.monotonic()

        if language == "python":
            cmd = [sys.executable, "-m", "py_compile", str(file_path)]
        elif language in ("javascript", "typescript"):
            cmd = ["node", "--check", str(file_path)]
        else:
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            duration = (time.monotonic() - start) * 1000

            output = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
            return CheckResult(
                passed=proc.returncode == 0,
                tool="syntax",
                output=output,
                duration_ms=duration,
            )
        except asyncio.TimeoutError:
            duration = (time.monotonic() - start) * 1000
            return CheckResult(
                passed=False,
                tool="syntax",
                output="Syntax check timed out (10s)",
                duration_ms=duration,
            )
        except FileNotFoundError:
            # Checker not available (e.g., node not installed)
            return None
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return CheckResult(
                passed=False,
                tool="syntax",
                output=f"Syntax check error: {e}",
                duration_ms=duration,
            )

    async def _check_lint(
        self, file_path: Path, language: str
    ) -> CheckResult | None:
        """Run linter if available."""
        import time

        start = time.monotonic()

        if language == "python":
            cmd = [sys.executable, "-m", "ruff", "check", "--output-format=text", str(file_path)]
        elif language in ("javascript", "typescript"):
            cmd = ["npx", "--yes", "eslint", "--no-error-on-unmatched-pattern", str(file_path)]
        else:
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            duration = (time.monotonic() - start) * 1000

            output = (stdout or b"").decode("utf-8", errors="replace").strip()
            return CheckResult(
                passed=proc.returncode == 0,
                tool="lint",
                output=output,
                duration_ms=duration,
            )
        except asyncio.TimeoutError:
            duration = (time.monotonic() - start) * 1000
            return CheckResult(
                passed=False,
                tool="lint",
                output="Lint check timed out (30s)",
                duration_ms=duration,
            )
        except FileNotFoundError:
            return None
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return CheckResult(
                passed=False,
                tool="lint",
                output=f"Lint check error: {e}",
                duration_ms=duration,
            )

    async def _check_tests(
        self, file_path: Path, language: str
    ) -> CheckResult | None:
        """Run relevant tests if they exist."""
        if language != "python":
            return None

        # Find the test file
        test_file = self._find_test_file(file_path)
        if test_file is None:
            return None

        import time

        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pytest", str(test_file), "-x", "-q",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            duration = (time.monotonic() - start) * 1000

            output = (stdout or b"").decode("utf-8", errors="replace").strip()
            return CheckResult(
                passed=proc.returncode == 0,
                tool="tests",
                output=output,
                duration_ms=duration,
            )
        except asyncio.TimeoutError:
            duration = (time.monotonic() - start) * 1000
            return CheckResult(
                passed=False,
                tool="tests",
                output="Test execution timed out (60s)",
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return CheckResult(
                passed=False,
                tool="tests",
                output=f"Test execution error: {e}",
                duration_ms=duration,
            )

    def _find_test_file(self, file_path: Path) -> Path | None:
        """Find the test file corresponding to a source file."""
        name = file_path.stem

        # Common test file patterns
        patterns = [
            f"test_{name}.py",
            f"{name}_test.py",
            f"tests/test_{name}.py",
            f"tests/{name}_test.py",
        ]

        for pattern in patterns:
            candidate = file_path.parent / pattern
            if candidate.exists():
                return candidate

        # Try walking up to find a tests/ directory
        current = file_path.parent
        while current != current.parent:
            tests_dir = current / "tests"
            if tests_dir.is_dir():
                test_file = tests_dir / f"test_{name}.py"
                if test_file.exists():
                    return test_file
            current = current.parent

        return None
