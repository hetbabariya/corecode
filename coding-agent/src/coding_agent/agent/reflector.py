"""Post-action reflection for the agent loop.

Evaluates whether tool calls achieved their intended purpose.
Signal-only — no suggestions, the agent decides what to do next.
Uses rule-based heuristics — no LLM calls.

Usage::

    reflector = Reflector()
    result = reflector.reflect_on_tool("edit_file", args, tool_result)
    # result.assessment tells you what happened
    # result.reason explains why
    # result.confidence shows certainty
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult


class Assessment(str, Enum):
    """Outcome assessment of a tool call."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    UNEXPECTED = "unexpected"


@dataclass
class ReflectionResult:
    """Result of reflecting on a tool call."""

    assessment: Assessment
    reason: str
    confidence: float  # 0.0 - 1.0


class Reflector:
    """Post-action reflection for the agent loop.

    Uses rule-based heuristics for common patterns.
    Each tool call is evaluated independently — no LLM overhead.
    """

    def __init__(self) -> None:
        self._consecutive_failures: dict[str, int] = {}

    def reflect_on_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: ToolResult,
    ) -> ReflectionResult:
        """Evaluate whether a tool call achieved its purpose.

        Parameters
        ----------
        tool_name:
            Name of the tool that was called.
        args:
            Arguments passed to the tool.
        result:
            ToolResult returned by the tool.
        """
        if not result.success:
            return self._assess_failure(tool_name, args, result)

        return self._assess_success(tool_name, args, result)

    async def assess_outcome(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: ToolResult,
        expected_outcome: str | None = None,
        llm_client: Any | None = None,
    ) -> ReflectionResult:
        """Assess whether the tool call achieved the expected outcome.

        Parameters
        ----------
        tool_name:
            Name of the tool that was called.
        args:
            Arguments passed to the tool.
        result:
            ToolResult returned by the tool.
        expected_outcome:
            Optional description of what was expected.
            If None, uses rule-based heuristics (same as reflect_on_tool).
        llm_client:
            Optional LLM client for LLM-based assessment.
            Required when expected_outcome is provided.
        """
        if not expected_outcome or llm_client is None:
            return self.reflect_on_tool(tool_name, args, result)

        # LLM-based assessment: compare expected vs actual
        actual_output = result.output or result.error or ""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are evaluating whether a tool call achieved its expected outcome. "
                    "Be rigorous and honest in your assessment. "
                    "Before assessing, reason through:\n"
                    "1. What was the expected outcome?\n"
                    "2. What actually happened? (Describe the actual result)\n"
                    "3. What is the gap between expected and actual?\n"
                    "4. Is this gap acceptable or does it indicate failure?\n"
                    "5. What would have made this succeed? (Missing information, different approach, etc.)\n"
                    "6. Is there a systemic issue, or was this a one-off failure?\n\n"
                    "Return ONLY a JSON object: "
                    '{"assessment": "success"|"partial"|"failure", "reason": "...", "confidence": 0.0-1.0}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Tool: {tool_name}\n"
                    f"Expected: {expected_outcome}\n"
                    f"Actual output: {actual_output[:500]}\n"
                    f"Success flag: {result.success}\n\n"
                    "Did the tool achieve the expected outcome? Why or why not?"
                ),
            },
        ]

        try:
            import json

            response = await llm_client.complete(messages)
            text = response.content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            assessment_str = data.get("assessment", "partial")
            try:
                assessment = Assessment(assessment_str)
            except ValueError:
                assessment = Assessment.PARTIAL

            return ReflectionResult(
                assessment=assessment,
                reason=data.get("reason", "LLM assessment"),
                confidence=float(data.get("confidence", 0.7)),
            )
        except Exception as e:
            logger.warning("outcome_assess_llm_failed", error=str(e))
            # Fall back to rule-based
            return self.reflect_on_tool(tool_name, args, result)

    def _assess_failure(
        self, tool_name: str, args: dict[str, Any], result: ToolResult
    ) -> ReflectionResult:
        """Assess a failed tool call."""
        error = (result.error or "").lower()

        # Track consecutive failures per tool
        self._consecutive_failures[tool_name] = (
            self._consecutive_failures.get(tool_name, 0) + 1
        )
        consecutive = self._consecutive_failures[tool_name]

        # Same tool failed 3+ times in a row
        if consecutive >= 3:
            return ReflectionResult(
                assessment=Assessment.FAILURE,
                reason=f"Tool '{tool_name}' has failed {consecutive} times consecutively",
                confidence=0.8,
            )

        # File not found
        if "not found" in error or "no such file" in error:
            return ReflectionResult(
                assessment=Assessment.FAILURE,
                reason=f"File not found: {error}",
                confidence=0.8,
            )

        # Permission denied
        if "permission denied" in error:
            return ReflectionResult(
                assessment=Assessment.FAILURE,
                reason=f"Permission denied: {error}",
                confidence=0.9,
            )

        # Syntax / parse error
        if "syntax" in error or "parse" in error:
            return ReflectionResult(
                assessment=Assessment.FAILURE,
                reason=f"Syntax error: {error}",
                confidence=0.9,
            )

        # TypeError / ValueError (bad args)
        if "typeerror" in error or "valueerror" in error:
            return ReflectionResult(
                assessment=Assessment.FAILURE,
                reason=f"Invalid arguments: {error}",
                confidence=0.8,
            )

        # Generic failure
        return ReflectionResult(
            assessment=Assessment.FAILURE,
            reason=f"Tool failed: {error}",
            confidence=0.5,
        )

    def _assess_success(
        self, tool_name: str, args: dict[str, Any], result: ToolResult
    ) -> ReflectionResult:
        """Assess a successful tool call."""
        # Reset consecutive failure count on success
        self._consecutive_failures[tool_name] = 0

        output = (result.output or "").lower()

        # Read file — check if content is meaningful
        if tool_name == "read_file":
            if not output or len(output.strip()) < 10:
                return ReflectionResult(
                    assessment=Assessment.PARTIAL,
                    reason="File appears empty or minimal",
                    confidence=0.6,
                )
            return ReflectionResult(
                assessment=Assessment.SUCCESS,
                reason="File read successfully",
                confidence=0.9,
            )

        # Edit/write file — success
        if tool_name in ("edit_file", "write_file", "apply_patch", "multi_edit"):
            return ReflectionResult(
                assessment=Assessment.SUCCESS,
                reason="File modified successfully",
                confidence=0.9,
            )

        # Search — check if results found
        if tool_name in ("search_content", "search_files"):
            if "no results" in output or "no matches" in output or not output.strip():
                return ReflectionResult(
                    assessment=Assessment.PARTIAL,
                    reason="No search results found",
                    confidence=0.7,
                )
            return ReflectionResult(
                assessment=Assessment.SUCCESS,
                reason="Search returned results",
                confidence=0.8,
            )

        # Execute command — check for errors in output
        if tool_name == "execute_command":
            if "error" in output or "failed" in output:
                return ReflectionResult(
                    assessment=Assessment.PARTIAL,
                    reason="Command may have errors in output",
                    confidence=0.6,
                )
            return ReflectionResult(
                assessment=Assessment.SUCCESS,
                reason="Command executed",
                confidence=0.7,
            )

        # Plan tools
        if tool_name in ("create_plan", "update_plan"):
            return ReflectionResult(
                assessment=Assessment.SUCCESS,
                reason="Plan updated",
                confidence=0.8,
            )

        # Memory tools
        if tool_name in ("remember", "recall"):
            return ReflectionResult(
                assessment=Assessment.SUCCESS,
                reason="Memory operation completed",
                confidence=0.8,
            )

        # Git tools
        if tool_name.startswith("git_"):
            return ReflectionResult(
                assessment=Assessment.SUCCESS,
                reason="Git operation completed",
                confidence=0.8,
            )

        # Default: success
        return ReflectionResult(
            assessment=Assessment.SUCCESS,
            reason="Tool completed",
            confidence=0.7,
        )

    def reset(self) -> None:
        """Reset consecutive failure tracking."""
        self._consecutive_failures.clear()
