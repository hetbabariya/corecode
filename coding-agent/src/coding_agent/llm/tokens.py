"""Token counting and cost tracking for LLM operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count tokens in a text string.

    Uses a simple heuristic (chars / 4) as a fast estimate. For exact counts
    the caller should use the response metadata from the LLM provider.
    """
    # Fallback: ~4 chars per token (rough English average)
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
