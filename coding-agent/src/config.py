from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # LLM
    llm_provider: str = Field(
        default="gemini", description="LLM provider: gemini | openrouter"
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

    # Agent
    max_iterations: int = Field(default=20, description="Max agent loop iterations")
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

    def get_db_path(self) -> Path:
        return Path(self.db_path).expanduser()

    def get_active_model(self) -> str:
        """Return the model name for the active provider."""
        if self.llm_provider == "openrouter":
            return self.openrouter_model
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
            else:
                model = self.llm_model
        return provider, model

    def is_sandbox_mode(self) -> bool:
        """Return True if exec_mode is set to 'sandbox'."""
        return self.exec_mode.lower() == "sandbox"
