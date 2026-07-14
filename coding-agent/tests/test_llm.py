"""Tests for the LLM client, streaming parser, token utilities, and key pool."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coding_agent.config import Settings
from coding_agent.llm.client import (
    LLMClient,
    LLMResponse,
    _is_key_specific_error,
    _is_rate_limit,
)
from coding_agent.llm.streaming import StreamEventType, StreamParser
from coding_agent.llm.tokens import (
    TokenUsage,
    accumulate_usage,
    count_tokens,
    format_usage,
    usage_from_chunk,
    usage_from_response,
)

# ---------------------------------------------------------------------------
# Helpers — fake Google GenAI response objects
# ---------------------------------------------------------------------------


@dataclass
class _FakeUsageMetadata:
    prompt_token_count: int
    candidates_token_count: int
    total_token_count: int


@dataclass
class _FakeFunctionCall:
    name: str
    args: dict[str, Any]


class _FakeCandidate:
    def __init__(self, finish_reason: str = "STOP") -> None:
        self.finish_reason = finish_reason
        self.content = MagicMock()


class _FakeGoogleResponse:
    """Mimics a google.genai GenerateContentResponse."""

    def __init__(
        self,
        text: str = "",
        function_calls: list[_FakeFunctionCall] | None = None,
        prompt_tokens: int = 10,
        completion_tokens: int = 20,
        finish_reason: str = "STOP",
    ) -> None:
        self.text = text
        self.function_calls = function_calls or []
        self.candidates = [_FakeCandidate(finish_reason)]
        self.usage_metadata = _FakeUsageMetadata(
            prompt_token_count=prompt_tokens,
            candidates_token_count=completion_tokens,
            total_token_count=prompt_tokens + completion_tokens,
        )


class _FakeStreamChunk:
    """Mimics a single streaming chunk from Google GenAI."""

    def __init__(
        self,
        text: str = "",
        function_calls: list[_FakeFunctionCall] | None = None,
        finish_reason: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        self.text = text
        self.function_calls = function_calls or []
        self.candidates = [_FakeCandidate(finish_reason)] if finish_reason else []
        self.usage_metadata = (
            _FakeUsageMetadata(
                prompt_tokens, completion_tokens, prompt_tokens + completion_tokens
            )
            if prompt_tokens or completion_tokens
            else None
        )


async def _fake_aiter(*chunks: _FakeStreamChunk):
    for c in chunks:
        yield c


# ===================================================================
# Token tests
# ===================================================================


class TestTokenUsage:
    def test_total_tokens(self) -> None:
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, model="gpt-4o")
        assert usage.total_tokens == 150

    def test_estimated_cost(self) -> None:
        usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=0, model="gpt-4o")
        assert usage.estimated_cost == pytest.approx(2.50, rel=0.01)

    def test_unknown_model_zero_cost(self) -> None:
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, model="unknown")
        assert usage.estimated_cost == 0.0

    def test_empty_model_zero_cost(self) -> None:
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, model="")
        assert usage.estimated_cost == 0.0


class TestCountTokens:
    def test_returns_positive_int(self) -> None:
        result = count_tokens("Hello, World!")
        assert isinstance(result, int)
        assert result > 0

    def test_empty_string(self) -> None:
        result = count_tokens("")
        assert result == 0

    def test_accurate_on_known_string(self) -> None:
        # "hello world" is 2 tokens in cl100k_base/o200k_base
        result = count_tokens("hello world")
        assert result == 2

    def test_code_tokens_reasonable(self) -> None:
        code = "def hello_world():\n    print('Hello, World!')\n"
        tokens = count_tokens(code)
        # Should be much more accurate than len(code)//4 = 10
        # Actual tiktoken count is ~12-14 tokens
        assert 8 <= tokens <= 20

    def test_long_text(self) -> None:
        text = "The quick brown fox jumps over the lazy dog. " * 100
        tokens = count_tokens(text)
        # Should be roughly 1/4 to 1/3 of character count
        assert tokens > 0
        assert tokens < len(text) // 2

    def test_fallback_on_bad_model(self) -> None:
        # Unknown models should still work (fallback to o200k_base)
        result = count_tokens("test", model="unknown-model-xyz")
        assert result > 0


class TestFormatUsage:
    def test_contains_tokens(self) -> None:
        usage = TokenUsage(prompt_tokens=10, completion_tokens=20, model="gpt-4o")
        formatted = format_usage(usage)
        assert "10" in formatted
        assert "20" in formatted
        assert "30" in formatted


class TestAccumulateUsage:
    def test_sums_tokens(self) -> None:
        a = TokenUsage(prompt_tokens=10, completion_tokens=20, model="gpt-4o")
        b = TokenUsage(prompt_tokens=5, completion_tokens=15, model="gpt-4o")
        result = accumulate_usage(a, b)
        assert result.prompt_tokens == 15
        assert result.completion_tokens == 35
        assert result.total_tokens == 50


class TestUsageFromResponse:
    def test_extracts_usage(self) -> None:
        resp = {
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "model": "gpt-4o",
        }
        usage = usage_from_response(resp, model="gpt-4o")
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.model == "gpt-4o"


class TestUsageFromChunk:
    def test_returns_none_when_no_usage(self) -> None:
        chunk = {"choices": []}
        assert usage_from_chunk(chunk) is None

    def test_extracts_usage(self) -> None:
        chunk = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        usage = usage_from_chunk(chunk, model="test")
        assert usage is not None
        assert usage.prompt_tokens == 10


# ===================================================================
# StreamParser tests
# ===================================================================


class TestStreamParser:
    def test_text_tokens(self) -> None:
        parser = StreamParser()
        events = parser.feed(
            {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}
        )
        assert len(events) == 1
        assert events[0].type == StreamEventType.TEXT
        assert events[0].data == "Hello"

    def test_tool_call_across_chunks(self) -> None:
        parser = StreamParser()
        # First chunk: tool call starts (name only, no args yet)
        events1 = parser.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "read_file", "arguments": ""},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
        )
        assert len(events1) == 0  # No complete args yet

        # Second chunk: arguments arrive — tool call is now complete
        events2 = parser.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": '{"path": "test.py"}'},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
        )
        # Tool call emitted incrementally since name + valid JSON args are present
        tool_events = [e for e in events2 if e.type == StreamEventType.TOOL_CALL]
        assert len(tool_events) == 1
        tc = tool_events[0].data
        assert tc["function"]["name"] == "read_file"
        assert json.loads(tc["function"]["arguments"]) == {"path": "test.py"}

        # Final chunk — should NOT emit the tool call again
        events3 = parser.feed(
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
        )
        tool_events3 = [e for e in events3 if e.type == StreamEventType.TOOL_CALL]
        assert len(tool_events3) == 0  # Already emitted

    def test_done_emitted(self) -> None:
        parser = StreamParser()
        events = parser.feed(
            {"choices": [{"delta": {"content": "Hi"}, "finish_reason": "stop"}]}
        )
        types = [e.type for e in events]
        assert StreamEventType.DONE in types
        assert parser.is_finished

    def test_usage_emitted_when_present(self) -> None:
        parser = StreamParser()
        events = parser.feed(
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )
        usage_events = [e for e in events if e.type == StreamEventType.USAGE]
        assert len(usage_events) == 1

    def test_partial_json_in_arguments(self) -> None:
        parser = StreamParser()
        parser.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "test",
                                        "arguments": "invalid json",
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
        )
        events = parser.feed(
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
        )
        tool_events = [e for e in events if e.type == StreamEventType.TOOL_CALL]
        assert len(tool_events) == 1
        # Should contain _raw key for unparseable JSON
        args = json.loads(tool_events[0].data["function"]["arguments"])
        assert "_raw" in args


# ===================================================================
# LLMClient tests
# ===================================================================


class TestExtractSystemPrompt:
    def test_single_system_message(self) -> None:
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        assert LLMClient._extract_system_prompt(msgs) == "You are helpful."

    def test_multiple_system_messages(self) -> None:
        msgs = [
            {"role": "system", "content": "Rule 1"},
            {"role": "system", "content": "Rule 2"},
            {"role": "user", "content": "Hi"},
        ]
        assert LLMClient._extract_system_prompt(msgs) == "Rule 1\n\nRule 2"

    def test_no_system_messages(self) -> None:
        msgs = [{"role": "user", "content": "Hi"}]
        assert LLMClient._extract_system_prompt(msgs) is None

    def test_empty_system_content(self) -> None:
        msgs = [{"role": "system", "content": ""}]
        assert LLMClient._extract_system_prompt(msgs) is None

    def test_empty_list(self) -> None:
        assert LLMClient._extract_system_prompt([]) is None


class TestLLMClientComplete:
    @pytest.mark.asyncio
    async def test_basic_completion(self) -> None:
        fake_resp = _FakeGoogleResponse(text="Hello there!")
        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(return_value=fake_resp)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            result = await client.complete(messages=[{"role": "user", "content": "Hi"}])
            assert isinstance(result, LLMResponse)
            assert result.content == "Hello there!"
            assert result.tool_calls == []
            assert result.usage.prompt_tokens == 10
            assert result.usage.completion_tokens == 20

    @pytest.mark.asyncio
    async def test_system_prompt_injected_to_gemini(self) -> None:
        """System messages must reach Gemini via system_instruction, not as content."""
        fake_resp = _FakeGoogleResponse(text="Got it")
        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(return_value=fake_resp)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            messages = [
                {"role": "system", "content": "You are a code assistant."},
                {"role": "user", "content": "Fix the bug"},
            ]
            await client.complete(messages=messages)

            call_kwargs = mock_aclient.models.generate_content.call_args.kwargs
            config = call_kwargs["config"]
            assert config is not None
            assert hasattr(config, "system_instruction")
            assert config.system_instruction == "You are a code assistant."

    @pytest.mark.asyncio
    async def test_multiple_system_messages_combined(self) -> None:
        """Multiple system messages are joined with double-newline."""
        fake_resp = _FakeGoogleResponse(text="ok")
        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(return_value=fake_resp)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            messages = [
                {"role": "system", "content": "Rule 1: be concise."},
                {"role": "system", "content": "Rule 2: use python."},
                {"role": "user", "content": "Hi"},
            ]
            await client.complete(messages=messages)

            call_kwargs = mock_aclient.models.generate_content.call_args.kwargs
            config = call_kwargs["config"]
            assert config.system_instruction == "Rule 1: be concise.\n\nRule 2: use python."

    @pytest.mark.asyncio
    async def test_no_system_message_no_instruction(self) -> None:
        """When there are no system messages, system_instruction should not be set."""
        fake_resp = _FakeGoogleResponse(text="ok")
        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(return_value=fake_resp)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            await client.complete(messages=[{"role": "user", "content": "Hi"}])

            call_kwargs = mock_aclient.models.generate_content.call_args.kwargs
            config = call_kwargs["config"]
            assert config.system_instruction is None

    @pytest.mark.asyncio
    async def test_completion_with_tool_calls(self) -> None:
        fake_resp = _FakeGoogleResponse(
            text="",
            function_calls=[
                _FakeFunctionCall(name="read_file", args={"path": "main.py"})
            ],
            finish_reason="STOP",
        )
        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(return_value=fake_resp)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            result = await client.complete(
                messages=[{"role": "user", "content": "Read main.py"}]
            )
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0]["function"]["name"] == "read_file"
            args = json.loads(result.tool_calls[0]["function"]["arguments"])
            assert args["path"] == "main.py"

    @pytest.mark.asyncio
    async def test_usage_accumulates(self) -> None:
        fake_resp = _FakeGoogleResponse(prompt_tokens=10, completion_tokens=20)
        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(return_value=fake_resp)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            await client.complete(messages=[{"role": "user", "content": "A"}])
            await client.complete(messages=[{"role": "user", "content": "B"}])
            assert client.total_usage.prompt_tokens == 20
            assert client.total_usage.completion_tokens == 40

    @pytest.mark.asyncio
    async def test_retry_on_api_error(self) -> None:
        from google.genai import errors as genai_errors

        call_count = 0

        async def _side_effect(**kwargs):  # type: ignore[no-undef]
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise genai_errors.APIError(
                    code=429, response_json={"error": "rate limited"}
                )
            return _FakeGoogleResponse(text="ok")

        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(side_effect=_side_effect)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            result = await client.complete(
                messages=[{"role": "user", "content": "test"}]
            )
            assert result.content == "ok"
            assert call_count == 3


class TestLLMClientStream:
    @pytest.mark.asyncio
    async def test_stream_yields_text_events(self) -> None:
        chunks = [
            _FakeStreamChunk(text="Hello"),
            _FakeStreamChunk(text=" world"),
            _FakeStreamChunk(finish_reason="STOP"),
        ]

        async def _mock_stream(**kwargs):  # type: ignore[no-undef]
            for c in chunks:
                yield c

        mock_aclient = MagicMock()
        mock_aclient.models.generate_content_stream = AsyncMock(
            side_effect=_mock_stream
        )
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            events = []
            async for event in client.stream(
                messages=[{"role": "user", "content": "Hi"}]
            ):
                events.append(event)

        text_events = [e for e in events if e.type == StreamEventType.TEXT]
        assert len(text_events) == 2
        assert text_events[0].data == "Hello"
        assert text_events[1].data == " world"
        assert any(e.type == StreamEventType.DONE for e in events)

    @pytest.mark.asyncio
    async def test_stream_yields_tool_call_events(self) -> None:
        chunks = [
            _FakeStreamChunk(
                function_calls=[_FakeFunctionCall(name="read", args={"p": "x"})],
                finish_reason="STOP",
            ),
        ]

        async def _mock_stream(**kwargs):  # type: ignore[no-undef]
            for c in chunks:
                yield c

        mock_aclient = MagicMock()
        mock_aclient.models.generate_content_stream = AsyncMock(
            side_effect=_mock_stream
        )
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            events = []
            async for event in client.stream(
                messages=[{"role": "user", "content": "do it"}]
            ):
                events.append(event)

        tool_events = [e for e in events if e.type == StreamEventType.TOOL_CALL]
        assert len(tool_events) == 1
        assert tool_events[0].data["function"]["name"] == "read"

    @pytest.mark.asyncio
    async def test_stream_emits_done_when_not_finished(self) -> None:
        async def _mock_stream(**kwargs):  # type: ignore[no-undef]
            yield _FakeStreamChunk(text="x")
            # Stream ends without finish_reason

        mock_aclient = MagicMock()
        mock_aclient.models.generate_content_stream = AsyncMock(
            side_effect=_mock_stream
        )
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="fake")
            events = []
            async for event in client.stream(
                messages=[{"role": "user", "content": "Hi"}]
            ):
                events.append(event)

        assert any(e.type == StreamEventType.DONE for e in events)


# ===================================================================
# _is_rate_limit tests
# ===================================================================


class TestIsRateLimit:
    def test_429_in_message(self) -> None:
        assert _is_rate_limit(Exception("Error 429"))

    def test_rate_in_message(self) -> None:
        assert _is_rate_limit(Exception("Rate limit exceeded"))

    def test_quota_in_message(self) -> None:
        assert _is_rate_limit(Exception("Quota exceeded"))

    def test_too_many_in_message(self) -> None:
        assert _is_rate_limit(Exception("Too many requests"))

    def test_normal_error_not_rate_limit(self) -> None:
        assert not _is_rate_limit(Exception("Connection refused"))

    def test_genai_429_error(self) -> None:
        from google.genai import errors as genai_errors

        exc = genai_errors.APIError(code=429, response_json={"error": "rate limited"})
        assert _is_rate_limit(exc)


# ===================================================================
# _is_key_specific_error tests
# ===================================================================


class TestIsKeySpecificError:
    def test_429_is_key_specific(self) -> None:
        assert _is_key_specific_error(Exception("Error 429"))

    def test_404_is_key_specific(self) -> None:
        assert _is_key_specific_error(Exception("Error 404 Not Found"))

    def test_not_found_is_key_specific(self) -> None:
        assert _is_key_specific_error(Exception("Model not found"))

    def test_server_error_not_key_specific(self) -> None:
        assert not _is_key_specific_error(Exception("500 Internal Server Error"))

    def test_connection_error_not_key_specific(self) -> None:
        assert not _is_key_specific_error(Exception("Connection refused"))

    def test_genai_404_error(self) -> None:
        from google.genai import errors as genai_errors

        exc = genai_errors.APIError(
            code=404, response_json={"error": "model not found"}
        )
        assert _is_key_specific_error(exc)


# ===================================================================
# LLMClient key-pool rotation tests
# ===================================================================


class TestLLMClientKeyPool:
    @pytest.mark.asyncio
    async def test_pool_rotates_on_429(self) -> None:
        from google.genai import errors as genai_errors

        call_count = 0

        async def _side_effect(**kwargs):  # type: ignore[no-undef]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise genai_errors.APIError(
                    code=429, response_json={"error": "rate limited"}
                )
            return _FakeGoogleResponse(text="ok after rotate")

        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(side_effect=_side_effect)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(
                model="test-model",
                api_keys=["key-a", "key-b"],
            )
            result = await client.complete(
                messages=[{"role": "user", "content": "test"}]
            )
            assert result.content == "ok after rotate"
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_pool_all_exhausted_then_succeeds(self) -> None:
        from google.genai import errors as genai_errors

        call_count = 0

        async def _side_effect(**kwargs):  # type: ignore[no-undef]
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                raise genai_errors.APIError(
                    code=429, response_json={"error": "rate limited"}
                )
            return _FakeGoogleResponse(text="ok")

        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(side_effect=_side_effect)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(
                model="test-model",
                api_keys=["k1", "k2"],
            )
            with patch("coding_agent.llm.client.asyncio.sleep", new_callable=AsyncMock):
                result = await client.complete(
                    messages=[{"role": "user", "content": "test"}]
                )
            assert result.content == "ok"
            assert call_count == 5

    @pytest.mark.asyncio
    async def test_single_key_no_pool(self) -> None:
        fake_resp = _FakeGoogleResponse(text="single key works")
        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(return_value=fake_resp)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(model="test-model", api_key="only-key")
            assert client._key_pool is not None
            assert client._key_pool.size == 1
            result = await client.complete(
                messages=[{"role": "user", "content": "test"}]
            )
            assert result.content == "single key works"

    @pytest.mark.asyncio
    async def test_non_429_error_raises_immediately(self) -> None:
        from google.genai import errors as genai_errors

        async def _side_effect(**kwargs):  # type: ignore[no-undef]
            raise genai_errors.APIError(
                code=500, response_json={"error": "server error"}
            )

        mock_aclient = MagicMock()
        mock_aclient.models.generate_content = AsyncMock(side_effect=_side_effect)
        mock_client = MagicMock()
        mock_client.aio = mock_aclient

        with patch("coding_agent.llm.client.genai.Client", return_value=mock_client):
            client = LLMClient(
                model="test-model",
                api_keys=["k1", "k2"],
            )
            with pytest.raises(genai_errors.APIError):
                await client.complete(messages=[{"role": "user", "content": "test"}])


# ===================================================================
# Settings.get_api_keys tests
# ===================================================================


class TestGetApiKeys:
    def test_comma_separated_keys(self) -> None:
        settings = Settings(llm_api_keys="key1,key2,key3")
        assert settings.get_api_keys() == ["key1", "key2", "key3"]

    def test_single_key_fallback(self) -> None:
        settings = Settings(llm_api_key="single-key", llm_api_keys="")
        assert settings.get_api_keys() == ["single-key"]

    def test_pool_takes_precedence(self) -> None:
        settings = Settings(llm_api_key="old-key", llm_api_keys="new1,new2")
        assert settings.get_api_keys() == ["new1", "new2"]

    def test_strips_whitespace(self) -> None:
        settings = Settings(llm_api_keys=" k1 , k2 , k3 ")
        assert settings.get_api_keys() == ["k1", "k2", "k3"]

    def test_ignores_empty_segments(self) -> None:
        settings = Settings(llm_api_keys="k1,,k2,,")
        assert settings.get_api_keys() == ["k1", "k2"]

    def test_empty_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CODING_AGENT_LLM_API_KEYS", raising=False)
        monkeypatch.delenv("CODING_AGENT_LLM_API_KEY", raising=False)
        monkeypatch.setattr(Settings, "model_config", {"env_prefix": "CODING_AGENT_"})
        settings = Settings(llm_api_keys="", llm_api_key="")
        assert settings.get_api_keys() == []

    def test_empty_string_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CODING_AGENT_LLM_API_KEYS", raising=False)
        monkeypatch.delenv("CODING_AGENT_LLM_API_KEY", raising=False)
        monkeypatch.setattr(Settings, "model_config", {"env_prefix": "CODING_AGENT_"})
        settings = Settings(llm_api_keys="", llm_api_key="")
        assert settings.get_api_keys() == []


# ===================================================================
# Settings.get_openrouter_api_keys tests
# ===================================================================


class TestGetOpenRouterApiKeys:
    def test_comma_separated(self) -> None:
        settings = Settings(openrouter_api_keys="sk1,sk2,sk3")
        assert settings.get_openrouter_api_keys() == ["sk1", "sk2", "sk3"]

    def test_single_key_fallback(self) -> None:
        settings = Settings(openrouter_api_key="sk-single", openrouter_api_keys="")
        assert settings.get_openrouter_api_keys() == ["sk-single"]

    def test_pool_takes_precedence(self) -> None:
        settings = Settings(openrouter_api_key="old", openrouter_api_keys="new1,new2")
        assert settings.get_openrouter_api_keys() == ["new1", "new2"]

    def test_empty_returns_empty(self) -> None:
        settings = Settings(openrouter_api_keys="", openrouter_api_key="")
        assert settings.get_openrouter_api_keys() == []


# ===================================================================
# OpenRouter provider tests
# ===================================================================


class TestOpenRouterClient:
    def test_init_creates_http_client(self) -> None:
        client = LLMClient(
            model="openai/gpt-4o-mini",
            api_key="sk-or-v1-test",
            provider="openrouter",
        )
        assert client.provider == "openrouter"
        assert client._http_client is not None

    def test_invalid_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            LLMClient(model="test", api_key="k", provider="invalid")

    def test_parse_openrouter_stream_line_data(self) -> None:
        line = 'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}'
        result = LLMClient._parse_openrouter_stream_line(line)
        assert result is not None
        assert result["choices"][0]["delta"]["content"] == "Hi"

    def test_parse_openrouter_stream_line_done(self) -> None:
        result = LLMClient._parse_openrouter_stream_line("data: [DONE]")
        assert result is not None
        assert result["choices"][0]["finish_reason"] == "stop"

    def test_parse_openrouter_stream_line_empty(self) -> None:
        assert LLMClient._parse_openrouter_stream_line("") is None
        assert LLMClient._parse_openrouter_stream_line("event: ping") is None

    def test_parse_openrouter_response_passthrough(self) -> None:
        data = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            "model": "openai/gpt-4o-mini",
        }
        result = LLMClient._parse_openrouter_response(data)
        assert result["choices"][0]["message"]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_openrouter_complete(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello from OR"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            "model": "openai/gpt-4o-mini",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(LLMClient, "_init_openrouter"):
            client = LLMClient(
                model="openai/gpt-4o-mini",
                api_key="sk-or-v1-test",
                provider="openrouter",
            )
            client._http_client = mock_client  # type: ignore[assignment]

            result = await client.complete(messages=[{"role": "user", "content": "Hi"}])
            assert result.content == "Hello from OR"
            assert result.usage.prompt_tokens == 5
