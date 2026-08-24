# CoreCode - AI Coding Agent

AI-powered coding agent with multi-model LLM support, Docker sandboxing, and terminal UI.

## Features

- **Multi-provider LLM**: Gemini, OpenRouter, Cerebras, ZenMux, OmniRoute
- **Docker Sandbox**: Isolated command execution with resource limits
- **File Operations**: Read, write, edit with diff preview
- **Code Search**: Ripgrep-based content search, glob file search
- **Git Operations**: Status, diff, log, commit
- **Session Persistence**: SQLite-backed conversation history
- **Undo/Redo**: File-snapshot-based undo with disk persistence
- **Subagents**: Spawn child agents for parallel tasks
- **Plan Mode**: Read-only planning phase vs execution
- **Context Management**: Summarization, micro-compact, sliding window
- **Budget Controls**: Cost and time limits per session
- **Permission System**: Auto-approve, confirm, or deny modes

## Quick Start

```bash
# Install
uv sync

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run with a prompt
uv run coding-agent run --prompt "Read the README and summarize it"

# Interactive REPL
uv run coding-agent repl

# Full TUI with session browser
uv run coding-agent tui
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `run` | Execute a single prompt and exit |
| `repl` | Start an interactive REPL session |
| `tui` | Launch the unified TUI with session browser |
| `resume [ID]` | Resume a previous session |
| `browse` | Browse and resume sessions via visual TUI |
| `history` | List past session history |
| `checkpoints` | List undo history |
| `undo` | Undo the last file mutation |
| `redo` | Redo the last undone mutation |
| `config` | Show current configuration |
| `version` | Show version information |
| `reset` | Reset session state |

## License

MIT
