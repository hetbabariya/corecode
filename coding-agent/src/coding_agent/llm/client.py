"""LLM client with provider abstraction (Gemini / OpenRouter / Cerebras / ZenMux / OmniRoute), key-pool rotation, and streaming."""

from __future__ import annotations

import asyncio
import json
import time
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
_CEREBRAS_BASE_URL = "https://api.cerebras.ai"
_ZENMUX_BASE_URL = "https://zenmux.ai/api/v1"
_OMNIROUTE_BASE_URL = "http://localhost:20128/v1"


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


def _normalize_stop_reason(finish_reason: str) -> str:
    """Normalize finish_reason across providers to a standard stop_reason.

    - "length" (OpenAI) → "max_tokens"
    - "MAX_TOKENS" (Gemini) → "max_tokens"
    - "stop" → "stop"
    - "" → ""
    """
    if not finish_reason:
        return ""
    reason = finish_reason.lower()
    if reason in ("length", "max_tokens"):
        return "max_tokens"
    if reason == "stop":
        return "stop"
    return reason


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
    stop_reason: str = ""  # Normalized stop reason ("max_tokens", "stop", etc.)
    raw: dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


class LLMClient:
    """Async LLM client with key-pool rotation and streaming support.

    Supports five providers:
    - ``gemini``: Google GenAI SDK (default)
    - ``openrouter``: OpenRouter HTTP API (OpenAI-compatible)
    - ``cerebras``: Cerebras HTTP API (OpenAI-compatible)
    - ``zenmux``: ZenMux HTTP API (OpenAI-compatible)
    - ``omniroute``: OmniRoute gateway (OpenAI-compatible, SSE for all responses)

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

        # OpenRouter, Cerebras, ZenMux, and OmniRoute use httpx
        self._http_client: httpx.AsyncClient | None = None
        self._zenmux_base_url: str = _ZENMUX_BASE_URL
        self._omniroute_base_url: str = _OMNIROUTE_BASE_URL

        if provider == "gemini":
            self._init_gemini()
        elif provider == "openrouter":
            self._init_openrouter()
        elif provider == "cerebras":
            self._init_cerebras()
        elif provider == "zenmux":
            self._init_zenmux()
        elif provider == "omniroute":
            self._init_omniroute()
        else:
            raise ValueError(
                f"Unknown provider: {provider!r}. Use 'gemini', 'openrouter', 'cerebras', 'zenmux', or 'omniroute'."
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

    def _init_cerebras(self) -> None:
        self._http_client = httpx.AsyncClient(
            base_url=_CEREBRAS_BASE_URL,
            headers={
                "Authorization": f"Bearer {self._current_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(120.0),
        )

    def _init_zenmux(self) -> None:
        self._http_client = httpx.AsyncClient(
            base_url=self._zenmux_base_url,
            headers={
                "Authorization": f"Bearer {self._current_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(120.0),
        )

    def _init_omniroute(self) -> None:
        self._http_client = httpx.AsyncClient(
            base_url=self._omniroute_base_url,
            headers={
                "Authorization": f"Bearer {self._current_api_key}",
                "Content-Type": "application/json",
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
        elif self.provider == "cerebras" and self._http_client is not None:
            old = self._http_client
            self._http_client = httpx.AsyncClient(
                base_url=_CEREBRAS_BASE_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(120.0),
            )
            self._old_clients.append(old)
        elif self.provider == "zenmux" and self._http_client is not None:
            old = self._http_client
            self._http_client = httpx.AsyncClient(
                base_url=self._zenmux_base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(120.0),
            )
            self._old_clients.append(old)
        elif self.provider == "omniroute" and self._http_client is not None:
            old = self._http_client
            self._http_client = httpx.AsyncClient(
                base_url=self._omniroute_base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
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
            payload["stream_options"] = {"include_usage": True}

        assert self._http_client is not None
        response = await self._http_client.post("/chat/completions", json=payload)
        response.raise_for_status()

        if stream:
            return response
        return response.json()

    async def _raw_call_cerebras(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> Any:
        """Single raw call to Cerebras via httpx — no retries, no rotation."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self._max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}

        assert self._http_client is not None
        response = await self._http_client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()

        if stream:
            return response
        return response.json()

    async def _raw_call_zenmux(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> Any:
        """Single raw call to ZenMux via httpx — no retries, no rotation."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self._max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}

        assert self._http_client is not None
        response = await self._http_client.post("/chat/completions", json=payload)
        response.raise_for_status()

        if stream:
            return response
        return response.json()

    # ------------------------------------------------------------------
    # SSE helper — OmniRoute returns text/event-stream for all responses
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_sse_response(body: str) -> dict[str, Any]:
        """Parse OmniRoute SSE response into an OpenAI-format dict.

        OmniRoute returns text/event-stream for ALL chat completions (even
        non-streaming). This reassembles the chunks into a single response.
        """
        content_parts: list[str] = []
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        finish_reason: str = "stop"
        usage: dict[str, Any] = {}
        model: str = ""
        chunk: dict[str, Any] = {}

        for line in body.split("\n"):
            line = line.strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if not model and chunk.get("model"):
                model = chunk["model"]

            choices = chunk.get("choices", [])
            if not choices:
                if chunk.get("usage"):
                    usage = chunk["usage"]
                continue

            delta = choices[0].get("delta", {})
            fr = choices[0].get("finish_reason")
            if fr:
                finish_reason = fr

            if delta.get("content"):
                content_parts.append(delta["content"])

            if delta.get("tool_calls"):
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {
                            "id": tc.get("id", f"call_{idx}"),
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = tool_calls_by_index[idx]
                    fn_delta = tc.get("function", {})
                    if fn_delta.get("name"):
                        entry["function"]["name"] = fn_delta["name"]
                    if fn_delta.get("arguments"):
                        entry["function"]["arguments"] += fn_delta["arguments"]

        # Usage is at the top level of the final chunk
        if chunk.get("usage"):
            usage = chunk["usage"]

        content = "".join(content_parts) if content_parts else None
        tool_calls = list(tool_calls_by_index.values()) if tool_calls_by_index else None

        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": tool_calls,
                    },
                    "finish_reason": finish_reason,
                }
            ],
            "usage": usage,
            "model": model,
        }

    # ------------------------------------------------------------------
    # Raw LLM call — OmniRoute
    # ------------------------------------------------------------------

    async def _raw_call_omniroute(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> Any:
        """Single raw call to OmniRoute via httpx — no retries, no rotation.

        OmniRoute returns SSE for all responses. For non-streaming calls we
        parse the SSE body into a dict. If the configured model returns 400/404,
        we retry once with ``model="auto"``.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self._max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}

        assert self._http_client is not None
        try:
            if stream:
                # Use stream() context manager for proper SSE streaming
                response = await self._http_client.send(
                    self._http_client.build_request("POST", "/chat/completions", json=payload),
                    stream=True,
                )
                response.raise_for_status()
            else:
                response = await self._http_client.post("/chat/completions", json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Fallback: if model 400/404 and not already "auto", retry with "auto"
            if exc.response.status_code in (400, 404) and self.model != "auto":
                logger.warning(
                    "omniroute_model_fallback",
                    model=self.model,
                    status=exc.response.status_code,
                )
                fallback_payload = {**payload, "model": "auto"}
                response = await self._http_client.post("/chat/completions", json=fallback_payload)
                response.raise_for_status()
            else:
                raise

        if stream:
            return response

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse_response(response.text)
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
        call_start = time.monotonic()
        logger.debug(
            "llm_request",
            model=self.model,
            provider=self.provider,
            stream=stream,
            tool_count=len(tools or []),
            message_count=len(messages),
        )
        try:
            if self.provider == "gemini":
                result = await self._raw_call_gemini(messages, tools=tools, stream=stream)
            elif self.provider == "cerebras":
                result = await self._raw_call_cerebras(messages, tools=tools, stream=stream)
            elif self.provider == "zenmux":
                result = await self._raw_call_zenmux(messages, tools=tools, stream=stream)
            elif self.provider == "omniroute":
                result = await self._raw_call_omniroute(messages, tools=tools, stream=stream)
            else:
                result = await self._raw_call_openrouter(messages, tools=tools, stream=stream)
            latency_ms = (time.monotonic() - call_start) * 1000
            logger.debug("llm_request_success", latency_ms=round(latency_ms, 1), stream=stream)
            return result
        except Exception as exc:
            latency_ms = (time.monotonic() - call_start) * 1000
            logger.error(
                "llm_request_failed",
                model=self.model,
                provider=self.provider,
                error=str(exc)[:200],
                latency_ms=round(latency_ms, 1),
            )
            raise

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
        # OpenRouter, Cerebras, ZenMux, OmniRoute — response is already a dict
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
        complete_start = time.monotonic()
        response: Any = await self._call_with_rotation(
            messages, tools=tools, stream=False
        )
        complete_duration_ms = (time.monotonic() - complete_start) * 1000
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
            duration_ms=round(complete_duration_ms, 1),
            content_preview=content[:200] if content else "",
        )

        # Normalize finish_reason to stop_reason
        raw_finish_reason = choice.get("finish_reason", "")
        stop_reason = _normalize_stop_reason(raw_finish_reason)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self.model,
            finish_reason=raw_finish_reason,
            stop_reason=stop_reason,
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
        response_text_parts: list[str] = []

        if self.provider == "gemini":
            chunk_count = 0
            async for chunk in response_stream:
                chunk_dict = self._parse_gemini_stream_chunk(chunk)
                chunk_count += 1
                if chunk_count % 50 == 0 or "usage" in chunk_dict:
                    logger.debug(
                        "stream_chunk_gemini",
                        chunk_num=chunk_count,
                        has_usage="usage" in chunk_dict,
                        choices_count=len(chunk_dict.get("choices", [])),
                    )
                for event in parser.feed(chunk_dict):
                    # Accumulate usage from stream events
                    if event.type == StreamEventType.USAGE and isinstance(event.data, dict):
                        self.total_usage = TokenUsage(
                            prompt_tokens=self.total_usage.prompt_tokens
                            + int(event.data.get("prompt_tokens", 0)),
                            completion_tokens=self.total_usage.completion_tokens
                            + int(event.data.get("completion_tokens", 0)),
                            model=self.model,
                        )
                        logger.info(
                            "stream_usage_received_gemini",
                            prompt_tokens=event.data.get("prompt_tokens", 0),
                            completion_tokens=event.data.get("completion_tokens", 0),
                        )
                    if event.type == StreamEventType.TEXT and isinstance(event.data, str):
                        response_text_parts.append(event.data)
                    # Suppress DONE — we yield it at the very end after fallback
                    if event.type != StreamEventType.DONE:
                        yield event
            logger.debug(
                "stream_finished_gemini",
                chunk_count=chunk_count,
                total_prompt=self.total_usage.prompt_tokens,
                total_completion=self.total_usage.completion_tokens,
            )
        else:
            # OpenRouter / Cerebras / ZenMux / OmniRoute — httpx Response with SSE stream
            chunk_count = 0
            async for line in response_stream.aiter_lines():
                chunk_dict = self._parse_openrouter_stream_line(line)
                if chunk_dict is not None:
                    chunk_count += 1
                    # Debug: log every 50th chunk + any chunk with usage
                    if chunk_count % 50 == 0 or "usage" in chunk_dict:
                        logger.debug(
                            "stream_chunk",
                            chunk_num=chunk_count,
                            has_usage="usage" in chunk_dict,
                            choices_count=len(chunk_dict.get("choices", [])),
                        )
                    for event in parser.feed(chunk_dict):
                        # Accumulate usage from stream events
                        if event.type == StreamEventType.USAGE and isinstance(event.data, dict):
                            self.total_usage = TokenUsage(
                                prompt_tokens=self.total_usage.prompt_tokens
                                + int(event.data.get("prompt_tokens", 0)),
                                completion_tokens=self.total_usage.completion_tokens
                                + int(event.data.get("completion_tokens", 0)),
                                model=self.model,
                            )
                            logger.info(
                                "stream_usage_received",
                                prompt_tokens=event.data.get("prompt_tokens", 0),
                                completion_tokens=event.data.get("completion_tokens", 0),
                            )
                        if event.type == StreamEventType.TEXT and isinstance(event.data, str):
                            response_text_parts.append(event.data)
                        # Suppress DONE — we yield it at the very end after fallback
                        if event.type != StreamEventType.DONE:
                            yield event
            logger.debug(
                "stream_finished",
                chunk_count=chunk_count,
                total_prompt=self.total_usage.prompt_tokens,
                total_completion=self.total_usage.completion_tokens,
            )

        # --- Fallback: estimate tokens when provider didn't send usage ---
        if self.total_usage.prompt_tokens == 0 and self.total_usage.completion_tokens == 0:
            try:
                from coding_agent.llm.tokens import count_tokens

                prompt_estimate = 0
                for msg in messages:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        prompt_estimate += count_tokens(content, self.model)
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and "text" in part:
                                prompt_estimate += count_tokens(part["text"], self.model)
                    # Estimate ~4 tokens per tool schema
                if tools:
                    prompt_estimate += len(tools) * 4

                completion_text = "".join(response_text_parts)
                completion_estimate = count_tokens(completion_text, self.model) if completion_text else 0

                # Yield as USAGE event so agent loop accumulates correctly
                usage_data = {
                    "prompt_tokens": prompt_estimate,
                    "completion_tokens": completion_estimate,
                }
                self.total_usage = TokenUsage(
                    prompt_tokens=self.total_usage.prompt_tokens + prompt_estimate,
                    completion_tokens=self.total_usage.completion_tokens + completion_estimate,
                    model=self.model,
                )
                logger.info(
                    "stream_usage_estimated",
                    prompt_tokens=prompt_estimate,
                    completion_tokens=completion_estimate,
                    method="tiktoken_fallback",
                )
                yield StreamEvent(type=StreamEventType.USAGE, data=usage_data)
            except Exception as exc:
                logger.warning(
                    "stream_usage_estimate_failed",
                    error=str(exc),
                )

        # Always yield DONE at the very end (after fallback usage estimation)
        yield StreamEvent(type=StreamEventType.DONE)
