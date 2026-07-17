"""Dynamic model registry — loads from ~/.coding-agent/models.json.

Users can add custom providers and models without code changes.
Falls back to built-in defaults when the config file doesn't exist.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coding_agent.logging import logger


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ModelEntry:
    """A single model available for use."""

    name: str
    provider: str
    tier: str  # "fast" | "smart" | "balanced"
    base_url: str | None = None
    api_key: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    sdk: str = "openai"  # "gemini" | "openai"
    is_default: bool = False


@dataclass
class ProviderEntry:
    """A provider with its models and config."""

    name: str
    base_url: str | None = None
    sdk: str = "openai"
    api_key_env: str = ""
    default_model: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    models: dict[str, ModelEntry] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Built-in provider defaults (used when models.json is missing)
# ---------------------------------------------------------------------------

_BUILTIN_PROVIDERS: dict[str, dict[str, Any]] = {
    "omniroute": {
        "base_url": "http://localhost:20128/v1",
        "api_key_env": "CODING_AGENT_OMNIROUTE_API_KEY",
        "default_model": "auto",
        "models": {
            "auto": {"tier": "balanced"},
        },
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "CODING_AGENT_OPENROUTER_API_KEY",
        "default_model": "openai/gpt-4o-mini",
        "extra_headers": {
            "HTTP-Referer": "https://github.com/coding-agent",
            "X-Title": "coding-agent",
        },
        "models": {
            "openai/gpt-4o-mini": {"tier": "fast"},
            "openai/gpt-4o": {"tier": "smart"},
            "anthropic/claude-3.5-sonnet": {"tier": "smart"},
            "anthropic/claude-3.5-haiku": {"tier": "fast"},
            "google/gemini-2.5-flash": {"tier": "fast"},
            "meta-llama/llama-3.3-70b-instruct": {"tier": "balanced"},
        },
    },
    "gemini": {
        "api_key_env": "CODING_AGENT_LLM_API_KEY",
        "default_model": "gemini-2.5-flash",
        "sdk": "gemini",
        "models": {
            "gemini-2.5-flash": {"tier": "fast"},
            "gemini-2.5-pro": {"tier": "smart"},
            "gemini-2.0-flash": {"tier": "fast"},
        },
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai",
        "api_key_env": "CODING_AGENT_CEREBRAS_API_KEY",
        "default_model": "llama-3.3-70b",
        "models": {
            "llama-3.3-70b": {"tier": "balanced"},
        },
    },
    "zenmux": {
        "base_url": "https://zenmux.ai/api/v1",
        "api_key_env": "CODING_AGENT_ZENMUX_API_KEY",
        "default_model": "stepfun/step-3.7-flash-free",
        "models": {
            "stepfun/step-3.7-flash-free": {"tier": "fast"},
        },
    },
}


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------


class ModelRegistry:
    """Dynamic model registry backed by ~/.coding-agent/models.json.

    Merges built-in provider defaults with user-defined providers from the
    JSON config file.  Users can add custom OpenAI-compatible providers
    without code changes.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is None:
            config_path = Path.home() / ".coding-agent" / "models.json"
        self._config_path = config_path
        self._providers: dict[str, ProviderEntry] = {}
        self._default_provider: str = "omniroute"

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Load models from JSON, falling back to built-in defaults."""
        # Start with built-in providers
        for name, cfg in _BUILTIN_PROVIDERS.items():
            self._add_provider_from_dict(name, cfg)

        # Overlay user config if it exists
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
                self._load_from_dict(data)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("models_config_load_error", error=str(exc))
        else:
            # Create default config file
            await self.save()

        logger.debug(
            "models_loaded",
            providers=len(self._providers),
            total_models=sum(len(p.models) for p in self._providers.values()),
        )

    async def save(self) -> None:
        """Persist current registry to JSON."""
        data: dict[str, Any] = {
            "default_provider": self._default_provider,
            "providers": {},
        }
        for pname, prov in self._providers.items():
            prov_data: dict[str, Any] = {
                "default_model": prov.default_model,
                "models": {},
            }
            if prov.base_url:
                prov_data["base_url"] = prov.base_url
            if prov.api_key_env:
                prov_data["api_key_env"] = prov.api_key_env
            if prov.sdk != "openai":
                prov_data["sdk"] = prov.sdk
            if prov.extra_headers:
                prov_data["extra_headers"] = prov.extra_headers
            for mname, mentry in prov.models.items():
                mdata: dict[str, str] = {"tier": mentry.tier}
                prov_data["models"][mname] = mdata
            data["providers"][pname] = prov_data

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_from_dict(self, data: dict[str, Any]) -> None:
        """Parse a JSON dict into the registry."""
        self._default_provider = data.get(
            "default_provider", self._default_provider,
        )
        for pname, pcfg in data.get("providers", {}).items():
            if not isinstance(pcfg, dict):
                continue
            self._add_provider_from_dict(pname, pcfg)

    def _add_provider_from_dict(self, name: str, cfg: dict[str, Any]) -> None:
        """Add or update a provider from a config dict."""
        base_url = cfg.get("base_url")
        api_key_env = cfg.get("api_key_env", "")
        sdk = cfg.get("sdk", "openai")
        default_model = cfg.get("default_model", "")
        extra_headers = cfg.get("extra_headers", {})

        # Resolve API key from env
        api_key = os.environ.get(api_key_env, "") if api_key_env else ""

        if name not in self._providers:
            self._providers[name] = ProviderEntry(
                name=name,
                base_url=base_url,
                sdk=sdk,
                api_key_env=api_key_env,
                default_model=default_model,
                extra_headers=extra_headers,
            )

        prov = self._providers[name]
        # Update fields from user config (user config overrides built-in)
        if base_url:
            prov.base_url = base_url
        if api_key_env:
            prov.api_key_env = api_key_env
        if sdk != "openai":
            prov.sdk = sdk
        if default_model:
            prov.default_model = default_model
        if extra_headers:
            prov.extra_headers = extra_headers

        # Add models
        for mname, mcfg in cfg.get("models", {}).items():
            tier = mcfg.get("tier", "balanced") if isinstance(mcfg, dict) else "balanced"
            prov.models[mname] = ModelEntry(
                name=mname,
                provider=name,
                tier=tier,
                base_url=base_url,
                api_key=api_key,
                extra_headers=extra_headers,
                sdk=sdk,
                is_default=(mname == prov.default_model),
            )

        # Ensure default model exists
        if default_model and default_model not in prov.models:
            prov.models[default_model] = ModelEntry(
                name=default_model,
                provider=name,
                tier="balanced",
                base_url=base_url,
                api_key=api_key,
                extra_headers=extra_headers,
                sdk=sdk,
                is_default=True,
            )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> ModelEntry | None:
        """Find a model by name across all providers.

        Prefers the default provider when the name exists in multiple.
        Returns None if not found.
        """
        matches: list[ModelEntry] = []
        for prov in self._providers.values():
            if name in prov.models:
                matches.append(prov.models[name])

        if not matches:
            return None

        if len(matches) == 1:
            return matches[0]

        # Prefer default provider
        for m in matches:
            if m.provider == self._default_provider:
                return m

        return matches[0]

    def resolve_or_raw(self, name: str) -> ModelEntry:
        """Resolve a model name. If not found, create a synthetic entry
        using the default provider — allows arbitrary model strings."""
        entry = self.resolve(name)
        if entry:
            return entry

        # Fall back to default provider with unknown model
        prov = self._providers.get(self._default_provider)
        if prov:
            return ModelEntry(
                name=name,
                provider=self._default_provider,
                tier="balanced",
                base_url=prov.base_url,
                api_key=prov.api_key_env and os.environ.get(prov.api_key_env, ""),
                extra_headers=prov.extra_headers,
                sdk=prov.sdk,
            )
        return ModelEntry(name=name, provider="gemini", tier="balanced")

    def list_models(self) -> list[ModelEntry]:
        """Return all available models, sorted by provider then tier."""
        tier_order = {"fast": 0, "smart": 1, "balanced": 2}
        models = []
        for prov in self._providers.values():
            for m in prov.models.values():
                models.append(m)
        models.sort(key=lambda m: (m.provider, tier_order.get(m.tier, 9)))
        return models

    def get_by_tier(self, tier: str) -> ModelEntry | None:
        """Get the best model for a given tier from the default provider."""
        prov = self._providers.get(self._default_provider)
        if prov:
            for m in prov.models.values():
                if m.tier == tier:
                    return m
        # Fall back to any provider
        for p in self._providers.values():
            for m in p.models.values():
                if m.tier == tier:
                    return m
        return None

    def get_provider(self, name: str) -> ProviderEntry | None:
        return self._providers.get(name)

    @property
    def default_provider(self) -> str:
        return self._default_provider

    @default_provider.setter
    def default_provider(self, value: str) -> None:
        if value in self._providers:
            self._default_provider = value

    # ------------------------------------------------------------------
    # Add / remove (for /model add, /model remove)
    # ------------------------------------------------------------------

    async def add_model(
        self,
        provider: str,
        name: str,
        tier: str = "balanced",
        base_url: str | None = None,
        api_key_env: str = "",
        sdk: str = "openai",
    ) -> bool:
        """Add a model to a provider. Creates the provider if needed."""
        if provider not in self._providers:
            if not base_url:
                return False  # base_url required for new providers
            self._providers[provider] = ProviderEntry(
                name=provider,
                base_url=base_url,
                sdk=sdk,
                api_key_env=api_key_env,
            )

        prov = self._providers[provider]
        api_key = os.environ.get(api_key_env, "") if api_key_env else ""
        prov.models[name] = ModelEntry(
            name=name,
            provider=provider,
            tier=tier,
            base_url=base_url or prov.base_url,
            api_key=api_key,
            extra_headers=prov.extra_headers,
            sdk=prov.sdk,
        )
        await self.save()
        return True

    async def remove_model(self, name: str) -> bool:
        """Remove a model from all providers."""
        removed = False
        for prov in self._providers.values():
            if name in prov.models:
                del prov.models[name]
                removed = True
        if removed:
            await self.save()
        return removed
