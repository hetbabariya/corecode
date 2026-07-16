from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings

from coding_agent.logging import logger


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # LLM
    llm_provider: str = Field(
        default="gemini", description="LLM provider: gemini | openrouter | cerebras | zenmux | omniroute"
    )
    llm_model: str = Field(default="gemini-2.5-flash", description="LLM model name")
    llm_api_key: str = Field(default="", description="LLM API key (single)")
    llm_api_keys: str = Field(
        default="", description="Comma-separated API keys for pool rotation"
    )

    # OpenRouter
    openrouter_api_key: str = Field(default="", description="OpenRouter API key")
    openrouter_api_keys: str = Field(
        default="", description="Comma-separated OpenRouter keys for pool rotation"
    )
    openrouter_model: str = Field(
        default="openai/gpt-4o-mini", description="OpenRouter model name"
    )

    # Cerebras
    cerebras_api_key: str = Field(default="", description="Cerebras API key")
    cerebras_api_keys: str = Field(
        default="", description="Comma-separated Cerebras keys for pool rotation"
    )
    cerebras_model: str = Field(
        default="llama-3.3-70b", description="Cerebras model name"
    )

    # ZenMux
    zenmux_api_key: str = Field(default="", description="ZenMux API key")
    zenmux_api_keys: str = Field(
        default="", description="Comma-separated ZenMux keys for pool rotation"
    )
    zenmux_model: str = Field(
        default="stepfun/step-3.7-flash-free", description="ZenMux model name"
    )
    zenmux_base_url: str = Field(
        default="https://zenmux.ai/api/v1", description="ZenMux API base URL"
    )

    # OmniRoute
    omniroute_api_key: str = Field(default="", description="OmniRoute API key")
    omniroute_api_keys: str = Field(
        default="", description="Comma-separated OmniRoute keys for pool rotation"
    )
    omniroute_model: str = Field(
        default="auto", description="OmniRoute model (auto = gateway picks best)"
    )
    omniroute_base_url: str = Field(
        default="http://localhost:20128/v1", description="OmniRoute API base URL"
    )

    # Agent
    max_iterations: int = Field(
        default=0,
        description="Max agent loop iterations (0 = unlimited, budget is primary limit)",
    )
    max_iterations_safety: int = Field(
        default=500,
        description="Hard safety net for agent loop iterations (should never be hit)",
    )
    max_tokens: int = Field(default=100_000, description="Max context window tokens")
    permission_level: str = Field(
        default="write", description="Default permission level"
    )

    # Summarization
    summary_model: str = Field(
        default="",
        description="Model for context summarization (empty = use main model)",
    )
    summary_provider: str = Field(
        default="",
        description="Provider for summarization (empty = use main provider)",
    )

    # Sandbox
    exec_mode: str = Field(
        default="sandbox",
        description="Command execution mode: sandbox (Docker) | host (direct)",
    )
    sandbox_timeout: int = Field(
        default=30, description="Sandbox command timeout in seconds"
    )
    sandbox_memory_limit: str = Field(
        default="512m", description="Sandbox memory limit"
    )
    sandbox_image: str = Field(
        default="coding-agent-sandbox:latest", description="Sandbox Docker image"
    )

    # Legacy field — migrated to exec_mode in model_post_init
    sandbox_enabled: bool | None = Field(default=None, exclude=True)

    # Logging
    log_level: str = Field(default="INFO", description="Log level")
    log_file: str = Field(default="agent.log", description="Log file path")

    # Database
    db_path: str = Field(
        default="~/.coding-agent/sessions.db", description="SQLite database path"
    )

    # Budgets
    max_cost_per_session: float = Field(
        default=5.0, description="Max cost per session in USD"
    )
    max_time_per_task: int = Field(
        default=300, description="Max time per task in seconds"
    )

    # Memory
    max_memories: int = Field(
        default=200, description="Max semantic memories per workspace"
    )
    memory_prune_threshold: float = Field(
        default=0.1, description="Min importance score to keep during pruning"
    )

    # Verification
    verify_after_edit: bool = Field(
        default=True, description="Run syntax/lint checks after file edits"
    )

    # Safety
    block_dangerous_commands: bool = Field(
        default=True, description="Block dangerous shell commands (rm -rf, git push --force, etc.)"
    )
    protect_critical_paths: bool = Field(
        default=True, description="Protect critical files (.gitconfig, .ssh, .env, etc.)"
    )

    # Workspace
    workspace: Any = Field(default=".", description="Workspace directory")

    model_config = {
        "env_prefix": "CODING_AGENT_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    def model_post_init(self, context: Any) -> None:
        """Migrate legacy CODING_AGENT_SANDBOX_ENABLED → exec_mode."""
        if (
            self.sandbox_enabled is not None
            and "exec_mode" not in self.model_fields_set
        ):
            self.exec_mode = "sandbox" if self.sandbox_enabled else "host"

        logger.debug(
            "config_loaded",
            provider=self.llm_provider,
            model=self.get_active_model(),
            exec_mode=self.exec_mode,
            max_iterations=self.max_iterations,
            max_tokens=self.max_tokens,
            log_level=self.log_level,
        )

    def get_api_keys(self) -> list[str]:
        """Return parsed list of API keys for the active provider.

        Prefers comma-separated ``llm_api_keys`` when set, otherwise falls
        back to the single ``llm_api_key`` value.  Empty strings are stripped.
        """
        if self.llm_api_keys:
            keys = [k.strip() for k in self.llm_api_keys.split(",") if k.strip()]
            if keys:
                return keys
        if self.llm_api_key and self.llm_api_key.strip():
            return [self.llm_api_key.strip()]
        return []

    def get_openrouter_api_keys(self) -> list[str]:
        """Return parsed list of OpenRouter API keys."""
        if self.openrouter_api_keys:
            keys = [k.strip() for k in self.openrouter_api_keys.split(",") if k.strip()]
            if keys:
                return keys
        if self.openrouter_api_key and self.openrouter_api_key.strip():
            return [self.openrouter_api_key.strip()]
        return []

    def get_cerebras_api_keys(self) -> list[str]:
        """Return parsed list of Cerebras API keys."""
        if self.cerebras_api_keys:
            keys = [k.strip() for k in self.cerebras_api_keys.split(",") if k.strip()]
            if keys:
                return keys
        if self.cerebras_api_key and self.cerebras_api_key.strip():
            return [self.cerebras_api_key.strip()]
        return []

    def get_zenmux_api_keys(self) -> list[str]:
        """Return parsed list of ZenMux API keys."""
        if self.zenmux_api_keys:
            keys = [k.strip() for k in self.zenmux_api_keys.split(",") if k.strip()]
            if keys:
                return keys
        if self.zenmux_api_key and self.zenmux_api_key.strip():
            return [self.zenmux_api_key.strip()]
        return []

    def get_omniroute_api_keys(self) -> list[str]:
        """Return parsed list of OmniRoute API keys."""
        if self.omniroute_api_keys:
            keys = [k.strip() for k in self.omniroute_api_keys.split(",") if k.strip()]
            if keys:
                return keys
        if self.omniroute_api_key and self.omniroute_api_key.strip():
            return [self.omniroute_api_key.strip()]
        return []

    def get_db_path(self) -> Path:
        return Path(self.db_path).expanduser()

    def get_active_model(self) -> str:
        """Return the model name for the active provider."""
        if self.llm_provider == "openrouter":
            return self.openrouter_model
        if self.llm_provider == "cerebras":
            return self.cerebras_model
        if self.llm_provider == "zenmux":
            return self.zenmux_model
        if self.llm_provider == "omniroute":
            return self.omniroute_model
        return self.llm_model

    def get_summary_model(self) -> tuple[str, str]:
        """Return (provider, model) for summarization.

        Falls back to the main provider/model when summary_model is empty.
        """
        provider = self.summary_provider or self.llm_provider
        model = self.summary_model
        if not model:
            if provider == "openrouter":
                model = self.openrouter_model
            elif provider == "cerebras":
                model = self.cerebras_model
            elif provider == "zenmux":
                model = self.zenmux_model
            elif provider == "omniroute":
                model = self.omniroute_model
            else:
                model = self.llm_model
        return provider, model

    def is_sandbox_mode(self) -> bool:
        """Return True if exec_mode is set to 'sandbox'."""
        return self.exec_mode.lower() == "sandbox"
