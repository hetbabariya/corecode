"""LLM client with provider abstraction (Gemini / OpenRouter), key-pool rotation, and streaming."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from google import genai
from google.genai import types

from coding_agent.llm.key_pool import KeyPool
from coding_agent.llm.streaming import StreamEvent, StreamEventType, StreamParser
from coding_agent.llm.tokens import TokenUsage
from coding_agent.logging import logger

# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _is_rate_limit(exc: Exception) -> bool:
    """Best-effort detection of 429 / rate-limit errors across SDK versions."""
    msg = str(exc).lower()
    return "429" in msg or "rate" in msg or "quota" in msg or "too many" in msg


def _is_key_specific_error(exc: Exception) -> bool:
    """Detect errors that can be resolved by rotating to a different API key.

    Includes rate limits (429) and model-not-found (404) which is often
    key-specific (e.g. newer Google accounts without access to certain models).
    """
    if _is_rate_limit(exc):
        return True
    msg = str(exc).lower()
    return "404" in msg or "not found" in msg


# ---------------------------------------------------------------------------
# Response type
# ---------------------------------------------------------------------------


@dataclass
class LLMResponse:
    """Parsed response from an LLM completion."""

    content: str
    tool_calls: list[dict[str, Any]]
    usage: TokenUsage
    model: str
    finish_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


class LLMClient:
    """Async LLM client with key-pool rotation and streaming support.

    Supports two providers:
    - ``gemini``: Google GenAI SDK (default)
    - ``openrouter``: OpenRouter HTTP API (OpenAI-compatible)

    When multiple API keys are provided, the client rotates to the next key
    on 429 / 404 errors and retries immediately.  After all keys are exhausted
    it backs off exponentially, resets the pool, and tries again.
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
        api_keys: list[str] | None = None,
        provider: str = "gemini",
        max_retries: int = 3,
        max_output_tokens: int = 8192,
    ) -> None:
        self.model = model
        self.provider = provider
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        self.total_usage = TokenUsage(prompt_tokens=0, completion_tokens=0, model=model)

        keys = api_keys or ([api_key] if api_key else [])
        self._key_pool: KeyPool | None = KeyPool(keys) if keys else None
        self._current_api_key = self._key_pool.get_key() if self._key_pool else api_key

        # Gemini-specific state (lazy init)
        self.genai_client: Any = None
        self.genai_aclient: Any = None
        self._old_clients: list[Any] = []

        # OpenRouter uses httpx
        self._http_client: httpx.AsyncClient | None = None

        if provider == "gemini":
            self._init_gemini()
        elif provider == "openrouter":
            self._init_openrouter()
        else:
            raise ValueError(
                f"Unknown provider: {provider!r}. Use 'gemini' or 'openrouter'."
            )

    # ------------------------------------------------------------------
    # Provider init
    # ------------------------------------------------------------------

    def _init_gemini(self) -> None:
        self.genai_client = genai.Client(api_key=self._current_api_key)  # pyright: ignore[reportUnknownMemberType]
        self.genai_aclient = self.genai_client.aio

    def _init_openrouter(self) -> None:
        self._http_client = httpx.AsyncClient(
            base_url=_OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {self._current_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/coding-agent",
                "X-Title": "coding-agent",
            },
            timeout=httpx.Timeout(120.0),
        )

    # ------------------------------------------------------------------
    # Client swap helpers
    # ------------------------------------------------------------------

    def _swap_client(self, api_key: str) -> None:
        """Replace the internal client with one using *api_key*."""
        self._current_api_key = api_key
        if self.provider == "gemini":
            self._old_clients.append(self.genai_client)
            self.genai_client = genai.Client(api_key=api_key)  # pyright: ignore[reportUnknownMemberType]
            self.genai_aclient = self.genai_client.aio
        elif self.provider == "openrouter" and self._http_client is not None:
            old = self._http_client
            self._http_client = httpx.AsyncClient(
                base_url=_OPENROUTER_BASE_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/coding-agent",
                    "X-Title": "coding-agent",
                },
                timeout=httpx.Timeout(120.0),
            )
            self._old_clients.append(old)
        logger.debug(
            "llm_client_swapped",
            key_suffix=api_key[-6:] if len(api_key) > 6 else api_key,
        )

    # ------------------------------------------------------------------
    # Gemini message / tool conversion (OpenAI → Google)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_system_prompt(messages: list[dict[str, Any]]) -> str | None:
        """Extract and combine all system messages into a single prompt."""
        parts: list[str] = []
        for msg in messages:
            if msg.get("role") == "system" and msg.get("content"):
                parts.append(msg["content"])
        return "\n\n".join(parts) if parts else None

    def _convert_messages(self, messages: list[dict[str, Any]]) -> list[Any]:
        """Convert OpenAI-format messages to Google GenAI Content objects.

        System messages are excluded from the contents list — they are
        passed separately via ``system_instruction`` in the request config.
        """
        contents: list[Any] = []
        for msg in messages:
            role: str = msg.get("role", "user")
            content: str | None = msg.get("content")

            if role == "system":
                continue

            google_role = "model" if role == "assistant" else "user"

            if content:
                contents.append(
                    types.Content(
                        role=google_role,
                        parts=[types.Part.from_text(text=content)],
                    )
                )
            elif msg.get("tool_calls"):
                parts: list[Any] = []
                for tc in msg["tool_calls"]:
                    fn: dict[str, Any] = tc.get("function", {})
                    args_str: str = fn.get("arguments", "{}")
                    try:
                        args: dict[str, Any] = json.loads(args_str)
                    except json.JSONDecodeError:
                        args = {}
                    parts.append(
                        types.Part.from_function_call(
                            name=fn.get("name", ""),
                            args=args,
                        )
                    )
                contents.append(types.Content(role="model", parts=parts))
            elif msg.get("tool_call_id"):
                result: dict[str, Any] = {}
                if content:
                    try:
                        result = json.loads(content)
                    except json.JSONDecodeError:
                        result = {"result": content}
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=msg.get("name", ""),
                                response=result,
                            )
                        ],
                    )
                )
        return contents

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[Any]:
        """Convert OpenAI-format tool schemas to Google GenAI Tool objects."""
        declarations: list[Any] = []
        for tool in tools:
            fn: dict[str, Any] = tool.get("function", {})
            declarations.append(
                types.FunctionDeclaration(
                    name=fn.get("name", ""),
                    description=fn.get("description", ""),
                    parameters_json_schema=fn.get("parameters", {}),
                )
            )
        return [types.Tool(function_declarations=declarations)]

    # ------------------------------------------------------------------
    # Raw LLM call — Gemini
    # ------------------------------------------------------------------

    async def _raw_call_gemini(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> Any:
        """Single raw call to Google GenAI — no retries, no rotation."""
        contents = self._convert_messages(messages)
        config = types.GenerateContentConfig(
            max_output_tokens=self._max_output_tokens,
        )
        system_prompt = self._extract_system_prompt(messages)
        if system_prompt:
            config.system_instruction = system_prompt
        if tools:
            config.tools = self._convert_tools(tools)

        if stream:
            return await self.genai_aclient.models.generate_content_stream(  # pyright: ignore[reportUnknownMemberType]
                model=self.model,
                contents=contents,
                config=config,
            )
        return await self.genai_aclient.models.generate_content(  # pyright: ignore[reportUnknownMemberType]
            model=self.model,
            contents=contents,
            config=config,
        )

    # ------------------------------------------------------------------
    # Raw LLM call — OpenRouter
    # ------------------------------------------------------------------

    async def _raw_call_openrouter(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> Any:
        """Single raw call to OpenRouter via httpx — no retries, no rotation."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self._max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True

        assert self._http_client is not None
        response = await self._http_client.post("/chat/completions", json=payload)
        response.raise_for_status()

        if stream:
            return response
        return response.json()

    # ------------------------------------------------------------------
    # Raw LLM call — provider dispatch
    # ------------------------------------------------------------------

    async def _raw_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> Any:
        """Single raw call — dispatches to the active provider."""
        logger.debug(
            "llm_request",
            model=self.model,
            provider=self.provider,
            stream=stream,
            tool_count=len(tools or []),
            message_count=len(messages),
        )
        if self.provider == "gemini":
            return await self._raw_call_gemini(messages, tools=tools, stream=stream)
        return await self._raw_call_openrouter(messages, tools=tools, stream=stream)

    # ------------------------------------------------------------------
    # Call with key-pool rotation + retry
    # ------------------------------------------------------------------

    async def _call_with_rotation(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> Any:
        """Call LLM with automatic key rotation on key-specific errors.

        Strategy:
        1. On 429 / 404 → rotate to next key, retry immediately.
        2. When all keys exhausted → exponential backoff, reset pool, retry.
        3. On other errors → raise immediately (caller decides).
        """
        pool = self._key_pool
        max_total_attempts: int = ((pool.size * 2) if pool else 1) + self._max_retries

        last_exc: Exception | None = None
        for attempt in range(max_total_attempts):
            try:
                return await self._raw_call(messages, tools=tools, stream=stream)
            except Exception as exc:
                last_exc = exc
                if not _is_key_specific_error(exc):
                    raise

                # --- key-specific error: rotate and retry ---
                if pool and not pool.is_exhausted:
                    new_key = pool.rotate()
                    self._swap_client(new_key)
                    logger.warning(
                        "llm_key_rotate",
                        attempt=attempt + 1,
                        key_index=pool.current_index,
                        pool_size=pool.size,
                        error=str(exc)[:80],
                    )
                    continue

                if pool and pool.is_exhausted:
                    backoff = min(2**attempt, 60)
                    logger.warning(
                        "llm_all_keys_exhausted",
                        attempt=attempt + 1,
                        backoff_s=backoff,
                    )
                    await asyncio.sleep(backoff)
                    pool.reset()
                    continue

                # No pool — simple exponential backoff on single key
                backoff = min(2**attempt, 30)
                logger.warning(
                    "llm_key_backoff", attempt=attempt + 1, backoff_s=backoff
                )
                await asyncio.sleep(backoff)

        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Response parsing — Gemini (Google → OpenAI format)
    # ------------------------------------------------------------------

    def _parse_gemini_response(self, response: Any) -> dict[str, Any]:
        """Convert a Google GenAI response to OpenAI-format dict."""
        tool_calls_raw: list[dict[str, Any]] = []

        if response.function_calls:
            for i, fc in enumerate(response.function_calls):
                tool_calls_raw.append(
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(fc.args) if fc.args else "{}",
                        },
                    }
                )
            content_text = ""
        else:
            content_text = response.text or ""

        finish = "stop"
        if tool_calls_raw:
            finish = "tool_calls"
        elif response.candidates and response.candidates[0].finish_reason:
            reason = str(response.candidates[0].finish_reason)
            if "STOP" in reason:
                finish = "stop"
            elif "MAX_TOKENS" in reason:
                finish = "length"
            elif "SAFETY" in reason:
                finish = "content_filter"
            else:
                finish = "stop"

        usage_data: dict[str, Any] = {}
        if response.usage_metadata:
            usage_data = {
                "prompt_tokens": getattr(
                    response.usage_metadata, "prompt_token_count", 0
                )
                or 0,
                "completion_tokens": getattr(
                    response.usage_metadata, "candidates_token_count", 0
                )
                or 0,
                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0)
                or 0,
            }

        return {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content_text,
                        "tool_calls": tool_calls_raw if tool_calls_raw else None,
                    },
                    "finish_reason": finish,
                }
            ],
            "usage": usage_data,
            "model": self.model,
        }

    def _parse_gemini_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        """Convert a Google GenAI stream chunk to OpenAI-format dict."""
        content_text: str = chunk.text or ""

        tool_calls: list[dict[str, Any]] = []
        if chunk.function_calls:
            for i, fc in enumerate(chunk.function_calls):
                tool_calls.append(
                    {
                        "index": i,
                        "id": f"call_{i}",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(fc.args) if fc.args else "{}",
                        },
                    }
                )

        finish_reason: str | None = None
        if chunk.candidates and chunk.candidates[0].finish_reason:
            reason = str(chunk.candidates[0].finish_reason)
            if "STOP" in reason:
                finish_reason = "stop"
            elif "MAX_TOKENS" in reason:
                finish_reason = "length"

        delta: dict[str, Any] = {}
        if content_text:
            delta["content"] = content_text
        if tool_calls:
            delta["tool_calls"] = tool_calls

        result: dict[str, Any] = {
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }

        if chunk.usage_metadata:
            result["usage"] = {
                "prompt_tokens": getattr(chunk.usage_metadata, "prompt_token_count", 0)
                or 0,
                "completion_tokens": getattr(
                    chunk.usage_metadata, "candidates_token_count", 0
                )
                or 0,
            }

        return result

    # ------------------------------------------------------------------
    # Response parsing — OpenRouter (already OpenAI format, passthrough)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_openrouter_response(data: dict[str, Any]) -> dict[str, Any]:
        """OpenRouter returns OpenAI format — return as-is with model set."""
        data["model"] = data.get("model", "")
        return data

    @staticmethod
    def _parse_openrouter_stream_line(line: str) -> dict[str, Any] | None:
        """Parse a single SSE ``data:`` line from OpenRouter streaming."""
        if not line.startswith("data: "):
            return None
        payload = line[6:]
        if payload.strip() == "[DONE]":
            return {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # Unified response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, response: Any) -> dict[str, Any]:
        """Parse a provider response into OpenAI-format dict."""
        if self.provider == "gemini":
            return self._parse_gemini_response(response)
        # OpenRouter — response is already a dict
        data: dict[str, Any] = dict(response) if response else {}
        return self._parse_openrouter_response(data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send a completion request and return the full response."""
        response: Any = await self._call_with_rotation(
            messages, tools=tools, stream=False
        )
        response_dict = self._parse_response(response)

        choice: dict[str, Any] = response_dict["choices"][0]
        message: dict[str, Any] = choice.get("message", {})
        content: str = message.get("content") or ""
        raw_tool_calls: list[dict[str, Any]] = message.get("tool_calls") or []

        tool_calls: list[dict[str, Any]] = []
        for tc in raw_tool_calls:
            fn: dict[str, Any] = tc.get("function", {})
            args_str: str = fn.get("arguments", "{}")
            try:
                args: dict[str, Any] = json.loads(args_str)
            except json.JSONDecodeError:
                args = {"_raw": args_str}
            tool_calls.append(
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": json.dumps(args),
                    },
                }
            )

        usage_data: dict[str, Any] = response_dict.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
            completion_tokens=int(usage_data.get("completion_tokens", 0)),
            model=self.model,
        )
        self.total_usage = TokenUsage(
            prompt_tokens=self.total_usage.prompt_tokens + usage.prompt_tokens,
            completion_tokens=self.total_usage.completion_tokens
            + usage.completion_tokens,
            model=self.model,
        )

        logger.info(
            "llm_response",
            model=self.model,
            provider=self.provider,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            tool_call_count=len(tool_calls),
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self.model,
            finish_reason=choice.get("finish_reason", ""),
            raw=response_dict,
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion response, yielding events as they arrive."""
        response_stream: Any = await self._call_with_rotation(
            messages, tools=tools, stream=True
        )

        parser = StreamParser()

        if self.provider == "gemini":
            async for chunk in response_stream:
                chunk_dict = self._parse_gemini_stream_chunk(chunk)
                for event in parser.feed(chunk_dict):
                    yield event
        else:
            # OpenRouter — httpx Response with SSE stream
            async for line in response_stream.aiter_lines():
                chunk_dict = self._parse_openrouter_stream_line(line)
                if chunk_dict is not None:
                    for event in parser.feed(chunk_dict):
                        yield event

        if not parser.is_finished:
            yield StreamEvent(type=StreamEventType.DONE)
