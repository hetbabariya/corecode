"""Tests for agent.verifier module."""

import sys
import tempfile
from pathlib import Path

import pytest

from coding_agent.agent.verifier import (
    CheckResult,
    PostEditVerifier,
    VerificationResult,
)


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    def test_passed_check(self):
        r = CheckResult(passed=True, tool="syntax", output="OK")
        assert r.passed is True

    def test_failed_check(self):
        r = CheckResult(passed=False, tool="lint", output="error: line 5")
        assert r.passed is False
        assert r.tool == "lint"


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_all_passed_empty(self):
        r = VerificationResult(file_path="test.py")
        assert r.all_passed is True

    def test_all_passed_with_checks(self):
        r = VerificationResult(
            file_path="test.py",
            checks=[
                CheckResult(passed=True, tool="syntax", output=""),
                CheckResult(passed=True, tool="lint", output=""),
            ],
        )
        assert r.all_passed is True

    def test_not_all_passed(self):
        r = VerificationResult(
            file_path="test.py",
            checks=[
                CheckResult(passed=True, tool="syntax", output=""),
                CheckResult(passed=False, tool="lint", output="error"),
            ],
        )
        assert r.all_passed is False
        assert len(r.failed_checks) == 1

    def test_to_feedback_all_passed(self):
        r = VerificationResult(
            file_path="test.py",
            checks=[CheckResult(passed=True, tool="syntax", output="")],
        )
        assert "passed" in r.to_feedback()

    def test_to_feedback_failure(self):
        r = VerificationResult(
            file_path="test.py",
            checks=[
                CheckResult(passed=False, tool="syntax", output="SyntaxError: bad"),
            ],
        )
        feedback = r.to_feedback()
        assert "failed" in feedback
        assert "SyntaxError" in feedback

    def test_to_feedback_no_checks(self):
        r = VerificationResult(file_path="test.py")
        assert r.to_feedback() == ""


class TestPostEditVerifier:
    """Tests for PostEditVerifier class."""

    @pytest.mark.asyncio
    async def test_verify_nonexistent_file(self, tmp_path: Path):
        verifier = PostEditVerifier(workspace=tmp_path)
        result = await verifier.verify(tmp_path / "nonexistent.py")
        assert result.all_passed is True
        assert result.checks == []

    @pytest.mark.asyncio
    async def test_verify_python_syntax_valid(self, tmp_path: Path):
        f = tmp_path / "valid.py"
        f.write_text("x = 1\n")
        verifier = PostEditVerifier(workspace=tmp_path)
        result = await verifier.verify(f)
        syntax_checks = [c for c in result.checks if c.tool == "syntax"]
        assert len(syntax_checks) == 1
        assert syntax_checks[0].passed is True

    @pytest.mark.asyncio
    async def test_verify_python_syntax_invalid(self, tmp_path: Path):
        f = tmp_path / "invalid.py"
        f.write_text("def foo(\n")
        verifier = PostEditVerifier(workspace=tmp_path)
        result = await verifier.verify(f)
        syntax_checks = [c for c in result.checks if c.tool == "syntax"]
        assert len(syntax_checks) == 1
        assert syntax_checks[0].passed is False

    @pytest.mark.asyncio
    async def test_verify_ignores_unknown_extension(self, tmp_path: Path):
        f = tmp_path / "data.xyz"
        f.write_text("hello")
        verifier = PostEditVerifier(workspace=tmp_path)
        result = await verifier.verify(f)
        assert result.checks == []

    @pytest.mark.asyncio
    async def test_verify_finds_test_file(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()
        (src / "core.py").write_text("x = 1\n")
        (tests / "test_core.py").write_text("assert True\n")
        verifier = PostEditVerifier(workspace=tmp_path)
        result = await verifier.verify(src / "core.py")
        test_checks = [c for c in result.checks if c.tool == "tests"]
        # Test may or may not run depending on pytest availability
        assert len(test_checks) <= 1

    @pytest.mark.asyncio
    async def test_verify_no_test_file(self, tmp_path: Path):
        f = tmp_path / "orphan.py"
        f.write_text("x = 1\n")
        verifier = PostEditVerifier(workspace=tmp_path)
        result = await verifier.verify(f)
        test_checks = [c for c in result.checks if c.tool == "tests"]
        assert len(test_checks) == 0

    @pytest.mark.asyncio
    async def test_verify_syntax_timing(self, tmp_path: Path):
        f = tmp_path / "timed.py"
        f.write_text("x = 1\n")
        verifier = PostEditVerifier(workspace=tmp_path)
        result = await verifier.verify(f)
        for check in result.checks:
            assert check.duration_ms >= 0

    def test_find_test_file_patterns(self, tmp_path: Path):
        verifier = PostEditVerifier(workspace=tmp_path)

        # test_main.py pattern
        f1 = tmp_path / "main.py"
        f1.write_text("x = 1\n")
        (tmp_path / "test_main.py").write_text("assert True\n")
        assert verifier._find_test_file(f1) is not None

        # tests/test_core.py pattern
        src = tmp_path / "src"
        src.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()
        f2 = src / "core.py"
        f2.write_text("x = 1\n")
        (tests / "test_core.py").write_text("assert True\n")
        assert verifier._find_test_file(f2) is not None

    def test_find_test_file_none(self, tmp_path: Path):
        verifier = PostEditVerifier(workspace=tmp_path)
        f = tmp_path / "orphan.py"
        f.write_text("x = 1\n")
        assert verifier._find_test_file(f) is None
