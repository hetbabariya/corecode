"""Tests for Reflector."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from coding_agent.agent.reflector import Assessment, Reflector, ReflectionResult
from coding_agent.tools.base import ToolResult


@pytest.fixture
def reflector() -> Reflector:
    return Reflector()


class TestReflectorFailure:
    def test_failure_assessment_on_generic_error(self, reflector: Reflector) -> None:
        result = ToolResult(success=False, output="", error="something broke")
        reflection = reflector.reflect_on_tool("execute_command", {}, result)
        assert reflection.assessment == Assessment.FAILURE
        assert "something broke" in reflection.reason

    def test_failure_assessment_on_file_not_found(self, reflector: Reflector) -> None:
        result = ToolResult(success=False, output="", error="File not found: x.py")
        reflection = reflector.reflect_on_tool("read_file", {"path": "x.py"}, result)
        assert reflection.assessment == Assessment.FAILURE
        assert "File not found" in reflection.reason

    def test_failure_assessment_on_permission_denied(self, reflector: Reflector) -> None:
        result = ToolResult(success=False, output="", error="Permission denied: /etc/passwd")
        reflection = reflector.reflect_on_tool("write_file", {"path": "/etc/passwd"}, result)
        assert reflection.assessment == Assessment.FAILURE
        assert "Permission denied" in reflection.reason

    def test_failure_assessment_on_syntax_error(self, reflector: Reflector) -> None:
        result = ToolResult(success=False, output="", error="SyntaxError: invalid syntax")
        reflection = reflector.reflect_on_tool("apply_patch", {}, result)
        assert reflection.assessment == Assessment.FAILURE
        assert "Syntax error" in reflection.reason

    def test_failure_assessment_on_type_error(self, reflector: Reflector) -> None:
        result = ToolResult(success=False, output="", error="TypeError: expected str")
        reflection = reflector.reflect_on_tool("edit_file", {}, result)
        assert reflection.assessment == Assessment.FAILURE
        assert "Invalid arguments" in reflection.reason

    def test_consecutive_failures_reflected(self, reflector: Reflector) -> None:
        result = ToolResult(success=False, output="", error="something")
        for _ in range(3):
            reflector.reflect_on_tool("execute_command", {}, result)
        reflection = reflector.reflect_on_tool("execute_command", {}, result)
        assert reflection.assessment == Assessment.FAILURE
        assert "4 times consecutively" in reflection.reason
        assert reflection.confidence == 0.8

    def test_success_resets_consecutive_failures(self, reflector: Reflector) -> None:
        fail = ToolResult(success=False, output="", error="something")
        for _ in range(2):
            reflector.reflect_on_tool("edit_file", {}, fail)
        # Reset via success
        ok = ToolResult(success=True, output="done")
        reflector.reflect_on_tool("edit_file", {}, ok)
        # 2 more failures — should be at 2, not 4
        for _ in range(2):
            reflector.reflect_on_tool("edit_file", {}, fail)
        reflection = reflector.reflect_on_tool("edit_file", {}, fail)
        assert reflection.assessment == Assessment.FAILURE
        assert "3 times" in reflection.reason
        # Different tool unaffected
        ok_file = ToolResult(success=True, output="def foo():\n    pass\n")
        reflection2 = reflector.reflect_on_tool("read_file", {}, ok_file)
        assert reflection2.assessment == Assessment.SUCCESS


class TestReflectorSuccess:
    def test_read_file_success(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="def foo():\n    pass\n")
        reflection = reflector.reflect_on_tool("read_file", {"path": "x.py"}, result)
        assert reflection.assessment == Assessment.SUCCESS
        assert reflection.confidence == 0.9

    def test_read_file_partial_empty(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="")
        reflection = reflector.reflect_on_tool("read_file", {"path": "x.py"}, result)
        assert reflection.assessment == Assessment.PARTIAL

    def test_edit_file_success(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="File edited")
        reflection = reflector.reflect_on_tool("edit_file", {}, result)
        assert reflection.assessment == Assessment.SUCCESS

    def test_search_no_results(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="No results found")
        reflection = reflector.reflect_on_tool("search_content", {"pattern": "xyz"}, result)
        assert reflection.assessment == Assessment.PARTIAL

    def test_search_no_matches(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="No matches found for xyz")
        reflection = reflector.reflect_on_tool("search_content", {"pattern": "xyz"}, result)
        assert reflection.assessment == Assessment.PARTIAL

    def test_search_with_results(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="Found 3 matches in foo.py")
        reflection = reflector.reflect_on_tool("search_content", {"pattern": "foo"}, result)
        assert reflection.assessment == Assessment.SUCCESS

    def test_execute_command_with_errors(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="error: compilation failed")
        reflection = reflector.reflect_on_tool("execute_command", {"cmd": "make"}, result)
        assert reflection.assessment == Assessment.PARTIAL

    def test_execute_command_success(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="Build succeeded")
        reflection = reflector.reflect_on_tool("execute_command", {"cmd": "make"}, result)
        assert reflection.assessment == Assessment.SUCCESS

    def test_git_tool_success(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="abc123 commit msg")
        reflection = reflector.reflect_on_tool("git_log", {"oneline": True}, result)
        assert reflection.assessment == Assessment.SUCCESS

    def test_plan_tool_success(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="Plan created")
        reflection = reflector.reflect_on_tool("create_plan", {"plan": "do stuff"}, result)
        assert reflection.assessment == Assessment.SUCCESS

    def test_memory_tool_success(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="Remembered")
        reflection = reflector.reflect_on_tool("remember", {"fact": "x"}, result)
        assert reflection.assessment == Assessment.SUCCESS

    def test_unknown_tool_success(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="ok")
        reflection = reflector.reflect_on_tool("custom_tool", {}, result)
        assert reflection.assessment == Assessment.SUCCESS


class TestReflectorReset:
    def test_reset_clears_consecutive_failures(self, reflector: Reflector) -> None:
        result = ToolResult(success=False, output="", error="err")
        for _ in range(3):
            reflector.reflect_on_tool("execute_command", {}, result)
        reflector.reset()
        reflection = reflector.reflect_on_tool("execute_command", {}, result)
        # After reset, first failure — low confidence generic
        assert reflection.confidence == 0.5
        assert "failed" in reflection.reason


class TestOutcomeAssessment:
    """Test assess_outcome with and without LLM client."""

    @pytest.mark.asyncio
    async def test_no_expected_falls_back_to_heuristic(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="File edited")
        assessment = await reflector.assess_outcome(
            "edit_file", {}, result, expected_outcome=None, llm_client=None,
        )
        assert assessment.assessment == Assessment.SUCCESS

    @pytest.mark.asyncio
    async def test_no_llm_falls_back_to_heuristic(self, reflector: Reflector) -> None:
        result = ToolResult(success=True, output="File edited")
        assessment = await reflector.assess_outcome(
            "edit_file", {}, result, expected_outcome="file should be edited", llm_client=None,
        )
        assert assessment.assessment == Assessment.SUCCESS

    @pytest.mark.asyncio
    async def test_llm_based_assessment_success(self, reflector: Reflector) -> None:
        mock_client = AsyncMock()
        mock_client.complete.return_value = MagicMock(
            content=json.dumps({
                "assessment": "success",
                "reason": "File was modified correctly",
                "confidence": 0.9,
            })
        )
        result = ToolResult(success=True, output="File edited successfully")
        assessment = await reflector.assess_outcome(
            "edit_file", {}, result,
            expected_outcome="file should contain new function",
            llm_client=mock_client,
        )
        assert assessment.assessment == Assessment.SUCCESS
        assert assessment.confidence == 0.9

    @pytest.mark.asyncio
    async def test_llm_based_assessment_failure(self, reflector: Reflector) -> None:
        mock_client = AsyncMock()
        mock_client.complete.return_value = MagicMock(
            content=json.dumps({
                "assessment": "failure",
                "reason": "File was not modified",
                "confidence": 0.85,
            })
        )
        result = ToolResult(success=True, output="")
        assessment = await reflector.assess_outcome(
            "edit_file", {}, result,
            expected_outcome="file should contain new function",
            llm_client=mock_client,
        )
        assert assessment.assessment == Assessment.FAILURE

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self, reflector: Reflector) -> None:
        mock_client = AsyncMock()
        mock_client.complete.side_effect = Exception("API error")
        result = ToolResult(success=True, output="File edited")
        assessment = await reflector.assess_outcome(
            "edit_file", {}, result,
            expected_outcome="file should be edited",
            llm_client=mock_client,
        )
        # Falls back to heuristic
        assert assessment.assessment == Assessment.SUCCESS

    @pytest.mark.asyncio
    async def test_llm_json_in_markdown(self, reflector: Reflector) -> None:
        mock_client = AsyncMock()
        mock_client.complete.return_value = MagicMock(
            content='```json\n{"assessment": "partial", "reason": "Partial edit", "confidence": 0.6}\n```'
        )
        result = ToolResult(success=True, output="some output")
        assessment = await reflector.assess_outcome(
            "edit_file", {}, result,
            expected_outcome="full replacement",
            llm_client=mock_client,
        )
        assert assessment.assessment == Assessment.PARTIAL
