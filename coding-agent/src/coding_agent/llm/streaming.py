"""Stream parsing for LLM responses.

Handles token-by-token streaming and accumulates partial tool call JSON
so callers can yield text tokens immediately and parse tool calls once
the stream finishes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StreamEventType(Enum):
    """Type of event produced by the stream parser."""

    TEXT = "text"
    TOOL_CALL = "tool_call"
    USAGE = "usage"
    DONE = "done"


@dataclass
class StreamEvent:
    """A single parsed event from the LLM stream."""

    type: StreamEventType
    data: str | dict[str, Any] | None = None


@dataclass
class ToolCallAccumulator:
    """Accumulates partial tool call data across streaming chunks."""

    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class StreamParser:
    """Parses streaming LLM response chunks into events.

    Usage:
        parser = StreamParser()
        for chunk in raw_stream:
            for event in parser.feed(chunk):
                if event.type == StreamEventType.TEXT:
                    display(event.data)
                elif event.type == StreamEventType.TOOL_CALL:
                    execute(event.data)
    """

    _tool_calls: dict[int, ToolCallAccumulator] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]
    _text_buffer: str = ""
    _finished: bool = False

    def feed(self, chunk: dict[str, Any]) -> list[StreamEvent]:
        """Process a single streaming chunk and return parsed events."""
        events: list[StreamEvent] = []

        if self._finished:
            # Even after stream end, extract usage from final chunks
            # (OmniRoute sends actual usage in a chunk after finish_reason)
            usage_data: dict[str, Any] | None = chunk.get("usage")  # type: ignore[assignment]
            if usage_data:
                events.append(StreamEvent(type=StreamEventType.USAGE, data=usage_data))
            return events

        choices: list[dict[str, Any]] = chunk.get("choices", [])

        # Usage can arrive in a chunk with empty choices (standard OpenAI behavior)
        usage_data: dict[str, Any] | None = chunk.get("usage")  # type: ignore[assignment]
        if usage_data:
            events.append(StreamEvent(type=StreamEventType.USAGE, data=usage_data))

        if not choices:
            return events

        choice: dict[str, Any] = choices[0]
        delta: dict[str, Any] = choice.get("delta", {})
        finish_reason: str | None = choice.get("finish_reason")

        # Text content
        content: str | None = delta.get("content")
        if content:
            events.append(StreamEvent(type=StreamEventType.TEXT, data=content))

        # Tool calls (arrive incrementally across chunks)
        for tc_delta in delta.get("tool_calls", []):
            idx: int = tc_delta.get("index", 0)
            if idx not in self._tool_calls:
                self._tool_calls[idx] = ToolCallAccumulator(index=idx)

            acc = self._tool_calls[idx]
            tc_fn: dict[str, Any] = tc_delta.get("function", {})
            if tc_fn.get("name"):
                acc.name = tc_fn["name"]
            if tc_fn.get("arguments"):
                acc.arguments += tc_fn["arguments"]
            if tc_delta.get("id"):
                acc.id = tc_delta["id"]

            # Emit tool call incrementally if it's complete
            if acc.name and acc.arguments:
                try:
                    json.loads(acc.arguments)
                    tool_call = _build_tool_call(acc)
                    if tool_call:
                        events.append(
                            StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call)
                        )
                        # Mark as emitted so we don't emit again at finish
                        acc.name = ""
                except json.JSONDecodeError:
                    pass  # Arguments still incomplete, wait for more chunks

        # Check for stream end
        if finish_reason is not None:
            self._finished = True
            # Emit any remaining tool calls not yet emitted
            for acc in self._tool_calls.values():
                if acc.name:  # Only emit if not already emitted
                    tool_call = _build_tool_call(acc)
                    if tool_call:
                        events.append(
                            StreamEvent(type=StreamEventType.TOOL_CALL, data=tool_call)
                        )
            # Emit usage if present (already handled above for empty-choices chunks)
            events.append(StreamEvent(type=StreamEventType.DONE))

        return events

    @property
    def is_finished(self) -> bool:
        return self._finished

    def get_tool_calls(self) -> list[dict[str, Any]]:
        """Return all accumulated tool calls (call after stream ends)."""
        calls: list[dict[str, Any]] = []
        for acc in self._tool_calls.values():
            tc = _build_tool_call(acc)
            if tc:
                calls.append(tc)
        return calls


def _build_tool_call(acc: ToolCallAccumulator) -> dict[str, Any] | None:
    """Build a complete tool call dict from an accumulator."""
    if not acc.name:
        return None

    # Parse arguments JSON — handle partial JSON gracefully
    args: dict[str, Any] = {}
    if acc.arguments:
        try:
            args = json.loads(acc.arguments)
        except json.JSONDecodeError:
            args = {"_raw": acc.arguments}

    return {
        "id": acc.id or f"call_{acc.index}",
        "type": "function",
        "function": {
            "name": acc.name,
            "arguments": json.dumps(args),
        },
    }
