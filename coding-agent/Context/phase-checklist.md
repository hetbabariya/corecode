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

## Week 4: File Tools ✅

- [x] `read_file(path, offset?, limit?)` — read file contents with line numbers
- [x] `write_file(path, content)` — write/create files with parent dir creation
- [x] `edit_file(path, old_string, new_string)` — find/replace with uniqueness check
- [x] `list_files(path?, pattern?)` — list directory with glob filtering
- [x] Binary file detection
- [x] `.gitignore` respect via `GitignoreFilter`

**Tests**: 54 passing (test_file_ops.py)

---

## Week 5: Search + Shell + Git Tools ✅

- [x] `search_content(pattern, path?, file_type?)` — ripgrep-based content search
- [x] `search_files(pattern, path?)` — glob-based file search
- [x] `execute_command(command, timeout?, cwd?)` — shell execution with timeout
- [x] `git_status()` — working tree status
- [x] `git_diff(file?)` — show changes
- [x] `git_log(n?)` — recent commits
- [x] `git_commit(message, files?)` — stage and commit

**Tests**: 100 passing (test_search.py, test_shell.py, test_git.py)

---

## Week 6: Docker Sandbox + Exec Mode Toggle ✅

- [x] `DockerSandbox` — persistent container with `docker exec`
- [x] Volume mounting (workspace → /workspace)
- [x] Resource limits (memory, CPU)
- [x] Container lifecycle (start, stop, context manager)
- [x] `SandboxExecutor` — routes sandbox vs host execution
- [x] Host fallback when Docker unavailable
- [x] Dead container auto-restart
- [x] Shell tool integration via lazy singleton executor
- [x] `exec_mode` config (sandbox | host) replaces `sandbox_enabled` bool
- [x] Legacy `sandbox_enabled` → `exec_mode` migration via `model_post_init`
- [x] Absolute path support in sandbox `cwd` parameter

**Tests**: 286 passing (40 mocked + 6 real host + 6 real Docker)

**Bug fixes**:
- Fixed sandbox `cwd` joining: absolute paths now work inside container
- Fixed pydantic `extra="allow"` not needed — `sandbox_enabled` declared as hidden field
- Fixed test mocking: patched at source modules, not lazy-import locations

---

## Week 7: Agent Loop — NEXT

- [ ] Agent loop orchestrator (LLM ↔ tools ↔ response)
- [ ] Tool call execution pipeline
- [ ] Multi-turn conversation management
- [ ] Max iterations guard
- [ ] Error recovery & retry logic

---

## Week 8: TUI (Textual)

- [ ] Main layout (input, output, status)
- [ ] Streaming response display
- [ ] Tool execution visualization
- [ ] Command history
- [ ] Keyboard shortcuts

---

## Week 9: Session & Polish

- [ ] Session persistence (SQLite)
- [ ] Conversation history
- [ ] Undo/redo for file operations
- [ ] Final testing & documentation
- [ ] Release prep

---

## Progress Tracking

| Week | Status | Tests |
|------|--------|-------|
| Week 1-2 | ✅ | 54 |
| Week 3 | ✅ | 54 |
| Week 4 | ✅ | 54 |
| Week 5 | ✅ | 100 |
| Week 6 | ✅ | 286 |
| Week 7 | ⬜ | — |
| Week 8 | ⬜ | — |
| Week 9 | ⬜ | — |

## Quality Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Tests passing | All | 286 ✅ |
| Lint errors | 0 | 0 ✅ |
| Type errors | 0 | 0 ✅ |
