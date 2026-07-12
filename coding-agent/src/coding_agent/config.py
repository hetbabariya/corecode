from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # LLM
    llm_model: str = Field(
        default="claude-3-5-sonnet-20241022", description="LLM model name"
    )
    llm_api_key: str = Field(default="", description="LLM API key")

    # Agent
    max_iterations: int = Field(default=20, description="Max agent loop iterations")
    max_tokens: int = Field(default=100_000, description="Max context window tokens")
    permission_level: str = Field(
        default="write", description="Default permission level"
    )

    # Sandbox
    sandbox_enabled: bool = Field(default=True, description="Enable Docker sandbox")
    sandbox_timeout: int = Field(
        default=30, description="Sandbox command timeout in seconds"
    )
    sandbox_memory_limit: str = Field(
        default="512m", description="Sandbox memory limit"
    )
    sandbox_image: str = Field(
        default="coding-agent-sandbox:latest", description="Sandbox Docker image"
    )

    # Logging
    log_level: str = Field(default="INFO", description="Log level")
    log_file: str = Field(default="agent.log", description="Log file path")

    # Database
    db_path: str = Field(
        default="~/.coding-agent/sessions.db", description="SQLite database path"
    )

    # Workspace
    workspace: Path = Field(default=Path("."), description="Workspace directory")

    model_config = {
        "env_prefix": "CODING_AGENT_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    def get_db_path(self) -> Path:
        return Path(self.db_path).expanduser()
