# Phase Checklist

## Week 1-2: Project Setup & LLM Client ✅

- [x] Project scaffolding (uv, pyproject.toml, src layout)
- [x] Config system (pydantic-settings, .env support)
- [x] Structured logging
- [x] LLM client — Gemini (google-genai) + OpenRouter (httpx)
- [x] Key pool with rotation on 429/404
- [x] Token tracking & usage reporting
- [x] Stream parser for real-time responses
- [x] CLI scaffold (main.py)

**Tests**: 54 passing (test_llm.py, test_key_pool.py)

---

## Week 3: Tool Registry & Base ✅

- [x] `ToolResult` dataclass (success, output, error, metadata)
- [x] `BaseTool` Protocol
- [x] JSON Schema inference from type hints (schema.py)
- [x] `ToolRegistry` class (register, unregister, execute, get_schemas)
- [x] `FunctionTool` adapter (wraps async functions)
- [x] `@tool` decorator (auto-register, auto-infer schema)
- [x] Default singleton `tool_registry`
- [x] OpenAI function-calling format output

**Tests**: 54 passing (test_schema.py, test_registry.py)

**Bug fixes**:
- Removed `additionalProperties: false` from schemas (broke OpenRouter)
- Fixed Gemini warning by guarding `response.text` access
- Added `get_active_model()` to Config for provider-aware model selection

---

## Week 4: File Tools — NEXT

- [ ] `read_file(path, offset?, limit?)` — read file contents
- [ ] `write_file(path, content)` — write/create files
- [ ] `edit_file(path, old_string, new_string)` — find/replace edits
- [ ] `list_files(path?, pattern?)` — list directory with glob filtering

**Tests**: TBD

---

## Week 5: Agent Loop

- [ ] Agent loop orchestrator (LLM ↔ tools ↔ response)
- [ ] Tool call execution pipeline
- [ ] Multi-turn conversation management
- [ ] Max iterations guard
- [ ] Error recovery & retry logic

---

## Week 6: Docker Sandbox

- [ ] Docker client integration
- [ ] Sandboxed command execution
- [ ] File operations within sandbox
- [ ] Timeout & memory limits
- [ ] Path validation & workspace boundaries

---

## Week 7: TUI (Textual)

- [ ] Main layout (input, output, status)
- [ ] Streaming response display
- [ ] Tool execution visualization
- [ ] Command history
- [ ] Keyboard shortcuts

---

## Week 8: Session & Polish

- [ ] Session persistence (SQLite)
- [ ] Conversation history
- [ ] Undo/redo for file operations
- [ ] Final testing & documentation
- [ ] Release prep
