# Coding Agent

AI-powered coding agent with multi-model LLM support, Docker sandboxing, and Textual TUI.

## Features

- Multi-model support via LiteLLM (Anthropic, OpenAI, Google)
- Docker sandboxed command execution
- File read/write/edit with diff preview
- Code search via ripgrep
- Git operations (status, diff, log, commit)
- Streaming responses in real-time
- Permission system for safe execution
- Session persistence and undo

## Quick Start

```bash
# Clone
git clone https://github.com/yourusername/coding-agent.git
cd coding-agent

# Install
uv sync

# Configure
cp .env.example .env
# Edit .env with your API key

# Run
uv run coding-agent run --prompt "Read the README"
```

## Development

```bash
# Install dev dependencies
uv sync --all-extras

# Lint
uv run ruff check src/
uv run ruff format --check src/

# Type check
uv run pyright src/

# Test
uv run pytest -v
```

## Architecture

```
User Input → TUI → Agent Loop → LLM → Tool Registry → Sandbox → Response
```

See [docs/architecture.md](docs/architecture.md) for details.

## Tech Stack

- Python 3.12+
- uv (package manager)
- Textual (TUI)
- LiteLLM (multi-model LLM)
- Docker (sandboxing)
- ripgrep (search)
- SQLite (sessions)

See [docs/techstack.md](docs/techstack.md) for details.

## License

MIT
