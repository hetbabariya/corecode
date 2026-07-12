# Coding Agent — Overview

## What Is This?

An AI-powered coding agent that reads, edits, and executes code in your workspace — like Claude Code or Codex, but built from scratch as a portfolio project for an AI developer role.

**Core capability:** You give it a task, it figures out what files to read, what code to change, and what commands to run — all in a sandboxed environment with your permission.


---

## What It Does

| Capability | What Happens |
|---|---|
| **Read files** | Agent reads your source code to understand context |
| **Edit files** | Agent makes targeted edits with diff preview |
| **Run commands** | Agent executes shell commands in Docker containers |
| **Search code** | Agent finds patterns across your codebase (ripgrep) |
| **Git operations** | Agent checks status, diffs, commits changes |
| **Stream responses** | Agent's thinking appears token-by-token in real time |
| **Permission gates** | Agent asks before doing anything risky |
| **Session history** | Agent remembers what it did, supports undo |

---

## Tech Stack (Quick)

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| Package manager | uv |
| CLI | Typer |
| TUI | Textual |
| LLM | LiteLLM (Anthropic + OpenAI + Google) |
| Sandbox | Docker |
| Search | ripgrep |
| Database | SQLite |
| Async | asyncio throughout |

**Full details:** [techstack.md](techstack.md)

---

## Architecture (Quick)

```
User Input
    ↓
┌─────────────┐
│  TUI Layer  │ ← Textual (renders streaming, diffs, status)
└──────┬──────┘
       ↓
┌─────────────┐
│  Agent Loop │ ← observe → think → act → observe
└──────┬──────┘
       ↓
┌─────────────┐
│  LLM Client │ ← LiteLLM (multi-provider streaming)
└──────┬──────┘
       ↓
┌─────────────┐
│Tool Registry│ ← routes tool calls to handlers
└──────┬──────┘
       ↓
┌─────────────┐
│  Sandbox    │ ← Docker (isolated execution)
└─────────────┘
```

**Full details:** [architecture.md](architecture.md)

---

## Features (Quick)

| Feature | Status |
|---|---|
| File read/write/edit | Phase 1 |
| Shell execution (sandboxed) | Phase 1 |
| Search (ripgrep + glob) | Phase 1 |
| Git operations | Phase 1 |
| Multi-model support | Phase 1 |
| Permission system | Phase 1 |
| Session management | Phase 1 |
| Token/cost tracking | Phase 1 |
| Context window management | Phase 1 |
| Streaming responses | Phase 1 |
| Textual TUI | Phase 1 |
| Sub-agents | Phase 2 |
| Plan/Build mode | Phase 2 |
| MCP integration | Phase 2 |
| Hooks | Phase 2 |
| Undo system | Phase 2 |
| Background jobs | Phase 2 |

**Full details:** [features.md](features.md)

---

## Build Plan (Quick)

| Week | Focus | Done? |
|---|---|---|
| 1 | Project setup + config | ✅ |
| 2 | LLM client + streaming | ⬜ |
| 3 | Tool registry + base | ⬜ |
| 4 | File tools | ⬜ |
| 5 | Search + Shell + Git | ⬜ |
| 6 | Docker sandbox | ⬜ |
| 7 | Agent loop + permissions | ⬜ |
| 8 | TUI + polish | ⬜ |

**Full details:** [phase-checklist.md](phase-checklist.md)

---

## Project Structure

```
coding-agent/
├── src/coding_agent/
│   ├── main.py                 # CLI entry point
│   ├── config.py               # Pydantic settings
│   ├── agent/                  # Core loop, context, permissions
│   ├── llm/                    # LiteLLM client, streaming, tokens
│   ├── tools/                  # Registry, file_ops, search, shell, git
│   ├── sandbox/                # Docker container management
│   ├── session/                # Persistence, history, undo
│   └── tui/                    # Textual app, screens, widgets
├── tests/
├── Dockerfile.sandbox
├── pyproject.toml
└── docs/
    ├── features.md
    ├── techstack.md
    ├── architecture.md
    └── phase-checklist.md
```

---

## Quick Start

```bash
# Clone
git clone https://github.com/yourusername/coding-agent.git
cd coding-agent

# Install
uv sync

# Set API key
cp .env.example .env
# Edit .env with your Anthropic/OpenAI key

# Run
uv run coding-agent

# Or without TUI (REPL mode)
uv run coding-agent --repl
```

---

## Why This for a Portfolio?

| Skill Demonstrated | Where |
|---|---|
| LLM integration depth | LiteLLM client, tool-use, streaming |
| Async systems | asyncio throughout, non-blocking I/O |
| Container orchestration | Docker sandbox lifecycle |
| Systems architecture | Clean separation, extensible design |
| Security thinking | Permission system, sandboxing |
| Modern Python | Pydantic, type hints, async/await |
| TUI development | Textual with custom widgets |

---

## References

| Document | Purpose |
|---|---|
| [features.md](features.md) | What to build, acceptance criteria |
| [techstack.md](techstack.md) | Why each tool, code examples |
| [architecture.md](architecture.md) | How components connect, data flows |
| [phase-checklist.md](phase-checklist.md) | Week-by-week tasks, test commands |

---

## Status

**Phase:** Week 1 Complete (Project Setup)
**Next:** Week 2 — LLM Client + Streaming
