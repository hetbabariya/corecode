# Tech Stack

## Finalized Choices

| Category | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | Modern async, type hints, performance improvements |
| Dependency manager | uv | Fast, Rust-based, modern Python packaging |
| Packaging | pyproject.toml + uv | Standard, reproducible builds |
| CLI framework | Typer | Clean CLI with auto-help, type-safe |
| Terminal UI | Textual | Full TUI framework, rich widgets, CSS layout |
| LLM SDK | LiteLLM | Multi-provider (Anthropic/OpenAI/Google), unified API |
| Async | asyncio | Native async/await, ecosystem support |
| File system | pathlib + aiofiles | Async file operations, cross-platform |
| Shell execution | asyncio.subprocess | Async, non-blocking, timeout support |
| Sandboxing | Docker | Cross-platform, resource limits, isolation |
| Git | subprocess (git CLI) | Simple, always current, async-friendly |
| Search | ripgrep (rg) | Fast, respects .gitignore, regex support |
| Code parsing | tree-sitter | Fast, multi-language, incremental |
| Config | pydantic-settings | Type-safe, env vars, validation |
| Validation | Pydantic v2 | Fast, type-safe, JSON schema |
| Database | SQLite + aiosqlite | Lightweight, no server, async |
| Retry/backoff | tenacity | Flexible, decorators, async support |
| Token counting | LiteLLM built-in | Unified across providers |
| Logging | structlog | Structured, fast, async-friendly |
| Testing | pytest | Standard, plugin ecosystem |
| Formatting | Ruff | Fast, Rust-based, comprehensive |
| Type checking | Pyright | Fast, strict, VS Code integration |
| CI | GitHub Actions | Standard, free for public repos |
| Secrets | .env + .gitignore | Simple, no key leaks |

---

## Detailed Choices

### Language: Python 3.12+

```python
# Why Python 3.12+:
# - Type parameter syntax: list[int] instead of List[int]
# - Exception groups and except* for async error handling
# - Performance improvements (faster startup, PEP 700)
# - Better error messages
# - Native async support without uvloop dependency
```

**Version constraint:** `>=3.12`

---

### Dependency Manager: uv

```toml
# pyproject.toml
[project]
requires-python = ">=3.12"
```

```bash
# Install
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create project
uv init coding-agent
cd coding-agent

# Add dependencies
uv add textual typer litellm aiosqlite tenacity structlog tree-sitter

# Run
uv run coding-agent
```

**Why uv over pip/poetry:**
- 10-100x faster than pip
- Rust-based, no Python dependency
- Handles Python versions automatically
- Lockfile support
- Workspace support for monorepos

---

### CLI Framework: Typer

```python
# src/coding_agent/main.py
import typer
from coding_agent.tui.app import AgentApp

app = typer.Typer()

@app.command()
def run(
    prompt: str = typer.Option(..., help="Initial prompt"),
    model: str = typer.Option("claude-3-5-sonnet-20241022", help="LLM model"),
    workspace: Path = typer.Option(".", help="Workspace directory"),
):
    """Coding Agent - AI-powered development assistant"""
    agent = AgentApp(model=model, workspace=workspace)
    agent.run(prompt)

if __name__ == "__main__":
    app()
```

**Why Typer:**
- Auto-generates help text
- Type-safe arguments
- Shell completion support
- Integrates with Rich for output

---

### Terminal UI: Textual

```python
# src/coding_agent/tui/app.py
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, RichLog
from textual.containers import Horizontal, Vertical

class AgentApp(App):
    CSS = """
    Screen { layout: vertical; }
    #sidebar { width: 30%; border-right: solid $accent; }
    #main { width: 70%; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(RichLog(id="sidebar"), id="sidebar"),
            Vertical(RichLog(id="main"), id="main"),
        )
        yield Footer()
```

**Why Textual:**
- CSS-like styling
- Widget system (RichLog, Input, DataTable)
- Live updates without redraw
- Mouse + keyboard support
- Built-in dev tools

---

### LLM SDK: LiteLLM

```python
# src/coding_agent/llm/client.py
import litellm
from litellm import acompletion

class LLMClient:
    def __init__(self, model: str = "claude-3-5-sonnet-20241022"):
        self.model = model

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> AsyncIterator[str]:
        response = await acompletion(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=stream,
        )
        if stream:
            async for chunk in response:
                yield chunk
        else:
            yield response
```

**Why LiteLLM:**
- One API for 100+ models
- Built-in token counting
- Automatic retries
- Cost tracking
- Fallback support

**Supported Models:**
```python
# Anthropic
"claude-3-5-sonnet-20241022"
"claude-3-5-haiku-20241022"

# OpenAI
"gpt-4o"
"gpt-4o-mini"

# Google
"gemini-2.0-flash"
"gemini-1.5-pro"
```

---

### Async: asyncio

```python
# All I/O operations are async
async def read_file(path: Path) -> str:
    async with aiofiles.open(path, "r") as f:
        return await f.read()

async def execute_command(cmd: str) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return stdout.decode()
```

**Why asyncio:**
- Non-blocking I/O
- Concurrent tool execution
- Streaming support
- Ecosystem support (aiofiles, aiosqlite)

---

### Sandboxing: Docker

```python
# src/coding_agent/sandbox/docker.py
import docker
from docker.models.containers import Container

class DockerSandbox:
    def __init__(self):
        self.client = docker.from_env()
        self.image = "coding-agent-sandbox:latest"

    async def execute(
        self,
        command: str,
        workspace: Path,
        timeout: int = 30,
    ) -> SandboxResult:
        container = self.client.containers.run(
            self.image,
            command=f"sh -c '{command}'",
            volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
            working_dir="/workspace",
            mem_limit="512m",
            cpu_quota=100000,  # 1 core
            detach=True,
            remove=True,
        )
        try:
            result = container.wait(timeout=timeout)
            logs = container.logs().decode()
            return SandboxResult(
                exit_code=result["StatusCode"],
                output=logs,
            )
        finally:
            container.remove(force=True)
```

**Why Docker:**
- Cross-platform (Linux, macOS, Windows)
- Resource limits (CPU, memory)
- Network isolation
- Volume mounts for workspace
- Easy cleanup

**Docker Image:**
```dockerfile
# Dockerfile.sandbox
FROM python:3.12-slim

# Install common dev tools
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m agent
USER agent
WORKDIR /workspace
```

---

### Search: ripgrep

```python
# src/coding_agent/tools/search.py
import asyncio
from pathlib import Path

class SearchTool:
    async def search_content(
        self,
        pattern: str,
        path: Path = Path("."),
        file_type: str | None = None,
    ) -> list[SearchResult]:
        cmd = ["rg", "--json", pattern, str(path)]
        if file_type:
            cmd.extend(["--type", file_type])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return self._parse_results(stdout.decode())
```

**Why ripgrep:**
- 10x faster than grep
- Respects .gitignore by default
- JSON output for parsing
- Regex support
- Cross-platform

---

### Config: pydantic-settings

```python
# src/coding_agent/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-3-5-sonnet-20241022"
    llm_api_key: str = ""

    # Agent
    max_iterations: int = 20
    max_tokens: int = 100000
    permission_level: str = "write"

    # Sandbox
    sandbox_enabled: bool = True
    sandbox_timeout: int = 30
    sandbox_memory_limit: str = "512m"

    # Logging
    log_level: str = "INFO"
    log_file: str = "agent.log"

    # Database
    db_path: str = "~/.coding-agent/sessions.db"

    model_config = {"env_prefix": "CODING_AGENT_"}
```

---

### Database: SQLite + aiosqlite

```python
# src/coding_agent/session/manager.py
import aiosqlite
from pathlib import Path

class SessionManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    model TEXT,
                    tokens_used INTEGER,
                    cost_estimate REAL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    tool_calls TEXT,
                    created_at TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)
            await db.commit()
```

**Why SQLite:**
- No server setup
- Single file database
- ACID compliant
- Full-text search (FTS5)
- Cross-platform

---

### Retry: tenacity

```python
# src/coding_agent/llm/client.py
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((RateLimitError, TimeoutError)),
)
async def complete_with_retry(self, messages, tools):
    return await self.complete(messages, tools)
```

---

### Logging: structlog

```python
# src/coding_agent/logging.py
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger()

# Usage
logger.info("tool_executed", tool="read_file", path="/src/main.py")
logger.error("tool_failed", tool="shell", error="Permission denied")
```

**Why structlog:**
- Structured output (JSON)
- Context binding
- Performance optimized
- Integrates with stdlib logging

---

### Type Checking: Pyright

```json
// pyrightconfig.json
{
    "typeCheckingMode": "strict",
    "pythonVersion": "3.12",
    "include": ["src"],
    "exclude": ["tests", ".venv"],
    "reportMissingTypeStubs": false,
    "reportUnknownMemberType": true,
    "reportUnknownParameterType": true,
    "reportUnknownVariableType": true,
    "reportUnknownArgumentType": true
}
```

---

### Formatting: Ruff

```toml
# pyproject.toml
[tool.ruff]
target-version = "py312"
line-length = 88

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "UP",  # pyupgrade
]
ignore = ["E501"]  # line length handled by formatter

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

---

### Testing: pytest

```python
# tests/test_tools.py
import pytest
from coding_agent.tools.file_ops import read_file

@pytest.mark.asyncio
async def test_read_file(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")

    result = await read_file(test_file)
    assert result == "Hello, World!"

@pytest.mark.asyncio
async def test_read_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        await read_file(tmp_path / "nonexistent.txt")
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## Development Tools

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/RobertCraiwordie/pyright-python
    rev: v1.1.367
    hooks:
      - id: pyright
```

### GitHub Actions

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check src/
      - run: uv run ruff format --check src/
      - run: uv run pyright src/
      - run: uv run pytest
```

---

## Dependency List

```toml
# pyproject.toml
[project]
name = "coding-agent"
version = "0.1.0"
description = "AI-powered coding agent"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.12.0",
    "textual>=0.70.0",
    "litellm>=1.40.0",
    "aiosqlite>=0.20.0",
    "aiofiles>=24.1.0",
    "tenacity>=8.4.0",
    "structlog>=24.1.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.3.0",
    "tree-sitter>=0.22.0",
    "docker>=7.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.4",
    "pyright>=1.1.367",
    "pre-commit>=3.7.0",
]

[project.scripts]
coding-agent = "coding_agent.main:app"
```
