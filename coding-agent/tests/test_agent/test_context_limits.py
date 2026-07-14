"""Tests for tool result truncation."""

from __future__ import annotations

from coding_agent.agent.context_limits import (
    truncate_search_results,
    truncate_tool_result,
)


class TestTruncateToolResult:
    def test_short_output_unchanged(self) -> None:
        short = "line1\nline2\nline3"
        assert truncate_tool_result(short) == short

    def test_empty_string(self) -> None:
        assert truncate_tool_result("") == ""

    def test_long_output_truncated(self) -> None:
        lines = [f"line {i}" for i in range(1000)]
        output = "\n".join(lines)
        result = truncate_tool_result(output, max_lines=100)
        assert "truncated" in result
        assert "line 0" in result
        assert "line 999" in result
        # Should have head + tail + notice
        result_lines = result.split("\n")
        assert len(result_lines) < 1000

    def test_preserves_head_and_tail(self) -> None:
        lines = [f"line {i}" for i in range(200)]
        output = "\n".join(lines)
        result = truncate_tool_result(
            output, max_lines=50, head_lines=10, tail_lines=10
        )
        assert "line 0" in result
        assert "line 9" in result
        assert "line 190" in result
        assert "line 199" in result
        assert "truncated" in result

    def test_token_based_truncation(self) -> None:
        # Create output that exceeds token limit but not line limit
        long_line = "x" * 500  # ~125 tokens per line
        lines = [long_line for _ in range(200)]
        output = "\n".join(lines)
        result = truncate_tool_result(
            output, max_tokens=1000, max_lines=10000, head_lines=10, tail_lines=10
        )
        assert "truncated" in result
        assert result.startswith("x")
        assert result.rstrip().endswith("x")

    def test_minimum_preserved_lines(self) -> None:
        lines = [f"line {i}" for i in range(100)]
        output = "\n".join(lines)
        result = truncate_tool_result(
            output, max_lines=20, head_lines=1, tail_lines=1
        )
        # Should preserve at least 10 head + 10 tail
        assert "line 0" in result
        assert "line 99" in result


class TestTruncateSearchResults:
    def test_few_results_unchanged(self) -> None:
        output = "result1\nresult2\nresult3"
        assert truncate_search_results(output, max_results=10) == output

    def test_many_results_truncated(self) -> None:
        lines = [f"match {i}" for i in range(50)]
        output = "\n".join(lines)
        result = truncate_search_results(output, max_results=10)
        assert "match 0" in result
        assert "match 9" in result
        assert "40 more results" in result
        assert "match 10" not in result

    def test_empty_string(self) -> None:
        assert truncate_search_results("") == ""

    def test_exact_limit(self) -> None:
        lines = [f"match {i}" for i in range(10)]
        output = "\n".join(lines)
        result = truncate_search_results(output, max_results=10)
        assert result == output
