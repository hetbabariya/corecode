"""Token counting and cost tracking for LLM operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import tiktoken


@dataclass(frozen=True)
class TokenUsage:
    """Tracks token counts and estimated cost for an LLM request."""

    prompt_tokens: int
    completion_tokens: int
    model: str = ""
    total_tokens: int = field(init=False)
    estimated_cost: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "total_tokens", self.prompt_tokens + self.completion_tokens
        )
        object.__setattr__(
            self,
            "estimated_cost",
            _estimate_cost(self.prompt_tokens, self.completion_tokens, self.model),
        )


# Pricing per 1M tokens (USD) — as of 2024-10
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


def _estimate_cost(prompt_tokens: int, completion_tokens: int, model: str) -> float:
    """Estimate cost in USD based on token counts and model."""
    if not model:
        return 0.0
    pricing = _MODEL_PRICING.get(model)
    if not pricing:
        return 0.0
    prompt_rate, completion_rate = pricing
    return (
        prompt_tokens * prompt_rate + completion_tokens * completion_rate
    ) / 1_000_000


_ENCODING_CACHE: dict[str, tiktoken.Encoding] = {}

_MODEL_TO_ENCODING: dict[str, str] = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "claude": "cl100k_base",
    "gemini": "cl100k_base",
}


def _get_encoding(model: str = "gpt-4o") -> tiktoken.Encoding:
    """Get (and cache) a tiktoken encoding for the given model.

    Falls back to ``o200k_base`` for unknown models, which is the most
    accurate general-purpose encoding available.
    """
    encoding_name = _MODEL_TO_ENCODING.get(model, "o200k_base")
    if encoding_name not in _ENCODING_CACHE:
        _ENCODING_CACHE[encoding_name] = tiktoken.get_encoding(encoding_name)
    return _ENCODING_CACHE[encoding_name]


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count tokens in a text string using tiktoken.

    Uses the model's encoding for accurate counts. Falls back to a
    ``len(text) // 4`` heuristic if tiktoken is unavailable.
    """
    if not text:
        return 0
    try:
        enc = _get_encoding(model)
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


def format_usage(usage: TokenUsage) -> str:
    """Format token usage for display."""
    return (
        f"Tokens: {usage.prompt_tokens} prompt + {usage.completion_tokens} completion "
        f"= {usage.total_tokens} total | Cost: ${usage.estimated_cost:.6f}"
    )


def accumulate_usage(current: TokenUsage, next_usage: TokenUsage) -> TokenUsage:
    """Accumulate two TokenUsage instances."""
    return TokenUsage(
        prompt_tokens=current.prompt_tokens + next_usage.prompt_tokens,
        completion_tokens=current.completion_tokens + next_usage.completion_tokens,
        model=current.model or next_usage.model,
    )


def usage_from_response(response: dict[str, Any], model: str = "") -> TokenUsage:
    """Extract TokenUsage from a LiteLLM response dict."""
    usage_data: dict[str, Any] = response.get("usage", {})  # type: ignore[assignment]
    return TokenUsage(
        prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
        completion_tokens=int(usage_data.get("completion_tokens", 0)),
        model=model or str(response.get("model", "")),
    )


def usage_from_chunk(chunk: dict[str, Any], model: str = "") -> TokenUsage | None:
    """Extract TokenUsage from a streaming chunk, if available (usually last chunk)."""
    usage_data: dict[str, Any] | None = chunk.get("usage")  # type: ignore[assignment]
    if usage_data is None:
        return None
    return TokenUsage(
        prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
        completion_tokens=int(usage_data.get("completion_tokens", 0)),
        model=model or str(chunk.get("model", "")),
    )
