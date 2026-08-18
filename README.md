# CoreCode

AI-powered coding agent built from scratch — reads, edits, and executes code in your workspace with multi-provider LLM support, Docker sandboxing, and a terminal UI.

## Project Structure

```
CoreCode/
├── coding-agent/    # Main agent application (Python)
└── Context/         # Architecture docs, audits, and implementation plans
```

## What It Does

You give it a task, it figures out what files to read, what code to change, and what commands to run — all in a sandboxed environment with your permission.

| Capability | Description |
|---|---|
| **File operations** | Read, write, edit with diff preview and syntax verification |
| **Code search** | Content search (ripgrep) and file search (glob) |
| **Shell execution** | Sandboxed commands in Docker containers |
| **Git operations** | Status, diff, log, commit |
| **Multi-provider LLM** | Gemini, OpenRouter, Cerebras, ZenMux, OmniRoute |
| **Session management** | Persistent history, resume anytime, undo/redo |
| **Subagents** | Spawn child agents for parallel or isolated tasks |
| **Plan/Build mode** | Read-only planning vs. execution phases |
| **Context management** | Summarization, compaction, sliding window |
| **Budget controls** | Cost and time limits with graceful cutoff |

## Quick Start

```bash
cd coding-agent
uv sync
cp .env.example .env
# Edit .env with your API key

# Run
uv run coding-agent run --prompt "Read the README and summarize it"

# Interactive REPL
uv run coding-agent repl

# Full TUI
uv run coding-agent tui
```

See [`coding-agent/README.md`](coding-agent/README.md) for full documentation, CLI commands, configuration, and architecture details.

## Tech Stack

Python 3.12+ · uv · Typer · Textual · google-genai · openai · cerebras-cloud-sdk · Docker · ripgrep · SQLite · structlog · Pydantic · pytest · Ruff · Pyright

## License

MIT
