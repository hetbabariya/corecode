# Phase Checklist

## Overview

This document provides a week-by-week checklist for building the Coding Agent. Each task includes:
- **What to build**
- **How to test**
- **Definition of done**

---

## Phase 1: Foundation (Weeks 1-2)

### Week 1: Project Setup + Configuration

#### Tasks

- [x] Initialize project with `uv init coding-agent`
- [x] Create `pyproject.toml` with all dependencies
- [x] Set up project structure (directories, `__init__.py` files)
- [x] Create `config.py` with Pydantic settings
- [x] Set up `.env.example` with all config options
- [x] Create `.gitignore` (include `.env`, `__pycache__`, `.venv`)
- [x] Set up `structlog` logging
- [x] Create `Dockerfile.sandbox`
- [x] Create `docker-compose.yml` for local dev
- [x] Set up GitHub Actions CI (`ci.yml`)
- [x] Set up `ruff` formatting and linting
- [x] Set up `pyright` type checking
- [x] Set up `pytest` with async support
- [x] Create `README.md` with quick start

#### How to Test

```bash
# 1. Verify project structure
find src/coding_agent -name "*.py" | head -20

# 2. Verify dependencies install
uv sync

# 3. Verify config loads
uv run python -c "from coding_agent.config import Settings; print(Settings())"

# 4. Verify Docker builds
docker build -f Dockerfile.sandbox -t coding-agent-sandbox:latest .

# 5. Verify CI config is valid
cat .github/workflows/ci.yml

# 6. Run linting
uv run ruff check src/
uv run ruff format --check src/

# 7. Run type checking
uv run pyright src/

# 8. Run tests (should have 0 tests, just verify pytest works)
uv run pytest --co
```

#### Definition of Done

- [x] `uv sync` installs all dependencies without errors
- [x] `uv run python -c "from coding_agent.config import Settings; s = Settings(); print(s.llm_model)"` prints default model
- [x] `docker build -f Dockerfile.sandbox -t coding-agent-sandbox:latest .` succeeds
- [x] `uv run ruff check src/` passes with no errors
- [x] `uv run ruff format --check src/` passes
- [x] `uv run pyright src/` passes with no errors
- [x] `uv run pytest --co` shows 0 tests collected (no errors)

---

### Week 2: LLM Client + Streaming

#### Tasks

- [x] Create `llm/client.py` with LiteLLM wrapper
- [x] Implement `complete()` method (non-streaming)
- [x] Implement `stream()` method (streaming)
- [x] Create `llm/tokens.py` for token counting
- [x] Create `llm/streaming.py` for stream parsing
- [x] Add retry logic with `tenacity`
- [x] Add cost tracking
- [x] Write tests for LLM client (mock responses)

#### How to Test

```bash
# 1. Test non-streaming completion
export ANTHROPIC_API_KEY="your-key-here"
uv run python -c "
import asyncio
from coding_agent.llm.client import LLMClient

async def test():
    client = LLMClient(model='claude-3-5-sonnet-20241022')
    response = await client.complete(
        messages=[{'role': 'user', 'content': 'Say hello'}]
    )
    print(response)

asyncio.run(test())
"

# 2. Test streaming completion
uv run python -c "
import asyncio
from coding_agent.llm.client import LLMClient

async def test():
    client = LLMClient(model='claude-3-5-sonnet-20241022')
    async for chunk in client.stream(
        messages=[{'role': 'user', 'content': 'Say hello'}]
    ):
        print(chunk, end='', flush=True)
    print()

asyncio.run(test())
"

# 3. Test token counting
uv run python -c "
from coding_agent.llm.tokens import count_tokens
tokens = count_tokens('Hello, World!')
print(f'Tokens: {tokens}')
"

# 4. Test with tool use
uv run python -c "
import asyncio
from coding_agent.llm.client import LLMClient

async def test():
    client = LLMClient(model='claude-3-5-sonnet-20241022')
    tools = [{
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': 'Read a file',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'}
                },
                'required': ['path']
            }
        }
    }]
    response = await client.complete(
        messages=[{'role': 'user', 'content': 'Read src/main.py'}],
        tools=tools
    )
    print(response)

asyncio.run(test())
"

# 5. Run unit tests
uv run pytest tests/test_llm.py -v
```

#### Definition of Done

- [x] `LLMClient.complete()` returns response from Claude
- [x] `LLMClient.stream()` yields tokens one by one
- [x] Token counting works (returns integer)
- [x] Retry logic works (simulate rate limit error)
- [x] Cost tracking accumulates correctly
- [x] All unit tests pass: `uv run pytest tests/test_llm.py -v`

---

## Phase 2: Tools (Weeks 3-5)

### Week 3: Tool Registry + Base

#### Tasks

- [x] Create `tools/base.py` with base tool class
- [x] Create `tools/registry.py` with tool registration
- [x] Implement `@tool` decorator
- [x] Implement schema generation for LLM
- [x] Implement tool dispatch
- [x] Write tests for registry

#### How to Test

```bash
# 1. Test tool registration
uv run python -c "
from coding_agent.tools.registry import tool_registry, tool

@tool(name='test_tool', description='A test tool', parameters={'x': {'type': 'string'}})
def test_tool(x: str) -> str:
    return f'Got: {x}'

print(tool_registry.get_schemas())
"

# 2. Test tool dispatch
uv run python -c "
import asyncio
from coding_agent.tools.registry import tool_registry, tool

@tool(name='add', description='Add two numbers', parameters={'a': {'type': 'integer'}, 'b': {'type': 'integer'}})
def add(a: int, b: int) -> int:
    return a + b

async def test():
    result = await tool_registry.execute('add', {'a': 2, 'b': 3})
    print(f'Result: {result}')

asyncio.run(test())
"

# 3. Run unit tests
uv run pytest tests/test_tools/test_registry.py -v
```

#### Definition of Done

- [x] `@tool` decorator registers tools
- [x] `tool_registry.get_schemas()` returns valid JSON schema
- [x] `tool_registry.execute()` routes to correct tool
- [x] Invalid tool names raise clear error
- [x] All unit tests pass

#### Bug Fixes (Week 3)

- Removed `additionalProperties: false` from schema output (broke OpenRouter tool calling)
- Guarded `response.text` access in Gemini parser (fixed SDK warning on function_call responses)
- Added `get_active_model()` to Settings for provider-aware model selection
- Fixed model mismatch: test was using `llm_model` instead of `openrouter_model` when provider=openrouter

---

### Week 4: File Tools

#### Tasks

- [x] Create `tools/file_ops.py`
- [x] Implement `read_file` tool
- [x] Implement `write_file` tool
- [x] Implement `edit_file` tool
- [x] Implement `list_files` tool
- [x] Add `.gitignore` respect
- [x] Write tests for all file operations

#### How to Test

```bash
# 1. Test read_file
uv run python -c "
import asyncio
from coding_agent.tools.file_ops import read_file

async def test():
    content = await read_file(path='pyproject.toml')
    print(content[:100])

asyncio.run(test())
"

# 2. Test write_file
uv run python -c "
import asyncio
from coding_agent.tools.file_ops import write_file

async def test():
    await write_file(path='test_output.txt', content='Hello from agent!')
    print('File written successfully')

asyncio.run(test())
"

# 3. Test edit_file
uv run python -c "
import asyncio
from coding_agent.tools.file_ops import edit_file, read_file

async def test():
    # Create test file
    with open('test_edit.py', 'w') as f:
        f.write('def old_name():\n    pass\n')

    # Edit it
    await edit_file(
        path='test_edit.py',
        old_text='def old_name():',
        new_text='def new_name():'
    )

    # Verify
    content = await read_file(path='test_edit.py')
    print(content)

asyncio.run(test())
"

# 4. Test list_files
uv run python -c "
import asyncio
from coding_agent.tools.file_ops import list_files

async def test():
    files = await list_files(path='.', pattern='**/*.py')
    for f in files[:5]:
        print(f)

asyncio.run(test())
"

# 5. Run unit tests
uv run pytest tests/test_tools/test_file_ops.py -v
```

#### Definition of Done

- [x] `read_file` returns file contents with line numbers
- [x] `write_file` creates files and directories
- [x] `edit_file` makes targeted replacements
- [x] `list_files` respects glob patterns
- [x] All tools respect `.gitignore`
- [x] All unit tests pass

---

### Week 5: Search + Shell + Git Tools

#### Tasks

- [x] Create `tools/search.py`
- [x] Implement `search_content` (ripgrep)
- [x] Implement `search_files` (glob)
- [x] Create `tools/shell.py`
- [x] Implement `execute_command`
- [x] Create `tools/git.py`
- [x] Implement git status, diff, log, commit
- [x] Write tests for all tools

#### How to Test

```bash
# 1. Test search_content
uv run python -c "
import asyncio
from coding_agent.tools.search import search_content

async def test():
    results = await search_content(pattern='def.*async', file_type='py')
    for r in results[:3]:
        print(f'{r.path}:{r.line}: {r.text}')

asyncio.run(test())
"

# 2. Test search_files
uv run python -c "
import asyncio
from coding_agent.tools.search import search_files

async def test():
    files = await search_files(pattern='**/*.md')
    for f in files[:5]:
        print(f)

asyncio.run(test())
"

# 3. Test execute_command (direct, not sandboxed yet)
uv run python -c "
import asyncio
from coding_agent.tools.shell import execute_command

async def test():
    result = await execute_command(command='echo Hello from shell!')
    print(result)

asyncio.run(test())
"

# 4. Test git status
uv run python -c "
import asyncio
from coding_agent.tools.git import git_status

async def test():
    status = await git_status()
    print(status)

asyncio.run(test())
"

# 5. Test git log
uv run python -c "
import asyncio
from coding_agent.tools.git import git_log

async def test():
    log = await git_log(n=5)
    print(log)

asyncio.run(test())
"

# 6. Run unit tests
uv run pytest tests/test_tools/ -v
```

#### Definition of Done

- [x] `search_content` returns file matches with line numbers
- [x] `search_files` returns matching file paths
- [x] `execute_command` runs shell commands and returns output
- [x] `git_status` shows working tree status
- [x] `git_log` shows recent commits
- [x] All unit tests pass

---

## Phase 3: Sandboxing (Week 6)

### Week 6: Docker Sandbox ✅

#### Tasks

- [x] Create `sandbox/docker.py` with Docker management
- [x] Implement persistent container with `docker exec`
- [x] Implement volume mounting (workspace → /workspace)
- [x] Implement resource limits (memory, CPU)
- [x] Implement command execution with timeout
- [x] Implement cleanup (start, stop, context manager)
- [x] Create `sandbox/executor.py` — routes sandbox vs host
- [x] Integrate sandbox with shell tool (lazy singleton)
- [x] `exec_mode` config (sandbox | host) replaces `sandbox_enabled` bool
- [x] Legacy env var migration via `model_post_init`
- [x] Absolute path support in sandbox `cwd`
- [x] Write tests (40 mocked + 6 real host + 6 real Docker)

#### How to Test

```bash
# 1. Test Docker container creation
uv run python -c "
import asyncio
from coding_agent.sandbox.docker import DockerSandbox

async def test():
    sandbox = DockerSandbox()
    result = await sandbox.execute(
        command='echo Hello from Docker!',
        workspace='.'
    )
    print(f'Exit code: {result.exit_code}')
    print(f'Output: {result.output}')

asyncio.run(test())
"

# 2. Test resource limits
uv run python -c "
import asyncio
from coding_agent.sandbox.docker import DockerSandbox

async def test():
    sandbox = DockerSandbox()
    # This should work
    result = await sandbox.execute(command='echo test', workspace='.')
    print(f'Normal: {result.exit_code}')

asyncio.run(test())
"

# 3. Test timeout handling
uv run python -c "
import asyncio
from coding_agent.sandbox.docker import DockerSandbox

async def test():
    sandbox = DockerSandbox()
    # This should timeout
    result = await sandbox.execute(
        command='sleep 60',
        workspace='.',
        timeout=5
    )
    print(f'Timeout result: {result.exit_code}')
    print(f'Output: {result.output}')

asyncio.run(test())
"

# 4. Test workspace mount
uv run python -c "
import asyncio
from coding_agent.sandbox.docker import DockerSandbox

async def test():
    sandbox = DockerSandbox()
    # Create test file
    with open('test_mount.txt', 'w') as f:
        f.write('Hello from host!')

    # Read from container
    result = await sandbox.execute(
        command='cat test_mount.txt',
        workspace='.'
    )
    print(f'Output: {result.output}')

asyncio.run(test())
"

# 5. Run unit tests
uv run pytest tests/test_sandbox.py -v
```

#### Definition of Done

- [x] `DockerSandbox.execute()` runs commands in container
- [x] Workspace is mounted correctly
- [x] Resource limits are enforced (memory, CPU)
- [x] Timeouts work (container killed after timeout)
- [x] Containers are cleaned up after execution
- [x] Host fallback when Docker unavailable
- [x] All unit tests pass (286 total)

---

## Phase 4: Agent Core (Week 7)

### Week 7: Agent Loop + Permissions

#### Tasks

- [ ] Create `agent/loop.py` with core agent loop
- [ ] Create `agent/context.py` for context management
- [ ] Create `agent/permissions.py` for permission system
- [ ] Implement observe-think-act cycle
- [ ] Implement tool call parsing
- [ ] Implement permission checks
- [ ] Implement iteration limits
- [ ] Implement context summarization
- [ ] Write tests for agent loop

#### How to Test

```bash
# 1. Test agent loop (simple request)
uv run python -c "
import asyncio
from coding_agent.agent.loop import AgentLoop

async def test():
    agent = AgentLoop(model='claude-3-5-sonnet-20241022')
    response = await agent.process_input('What files are in the current directory?')
    print(response)

asyncio.run(test())
"

# 2. Test agent with tool use
uv run python -c "
import asyncio
from coding_agent.agent.loop import AgentLoop

async def test():
    agent = AgentLoop(model='claude-3-5-sonnet-20241022')
    response = await agent.process_input('Read the pyproject.toml file')
    print(response)

asyncio.run(test())
"

# 3. Test agent with multiple tools
uv run python -c "
import asyncio
from coding_agent.agent.loop import AgentLoop

async def test():
    agent = AgentLoop(model='claude-3-5-sonnet-20241022')
    response = await agent.process_input(
        'Search for all Python files that contain the word \"async\"'
    )
    print(response)

asyncio.run(test())
"

# 4. Test permission system
uv run python -c "
import asyncio
from coding_agent.agent.permissions import PermissionManager, Permission

async def test():
    pm = PermissionManager(level=Permission.READ)
    print(f'Can read: {pm.can_execute(Permission.READ)}')
    print(f'Can write: {pm.can_execute(Permission.WRITE)}')
    print(f'Can execute: {pm.can_execute(Permission.EXECUTE)}')

asyncio.run(test())
"

# 5. Test context management
uv run python -c "
import asyncio
from coding_agent.agent.context import ContextManager

async def test():
    cm = ContextManager(max_tokens=100000)
    cm.add_message({'role': 'user', 'content': 'Hello'})
    cm.add_message({'role': 'assistant', 'content': 'Hi there!'})
    print(f'Messages: {len(cm.messages)}')
    print(f'Tokens: {cm.count_tokens()}')

asyncio.run(test())
"

# 6. Run unit tests
uv run pytest tests/test_agent_loop.py -v
```

#### Definition of Done

- [ ] Agent loop processes user input
- [ ] Agent calls tools when needed
- [ ] Agent feeds results back to LLM
- [ ] Agent stops after max iterations
- [ ] Permission system blocks unauthorized operations
- [ ] Context window manages token limits
- [ ] All unit tests pass

---

## Phase 5: TUI + Polish (Week 8)

### Week 8: Textual Interface + Final Polish

#### Tasks

- [ ] Create `tui/app.py` with Textual app
- [ ] Create `tui/screens.py` for different views
- [ ] Create `tui/widgets.py` for custom widgets
- [ ] Implement streaming display
- [ ] Implement diff view
- [ ] Implement status panel
- [ ] Add error handling throughout
- [ ] Add logging to all components
- [ ] Write integration tests
- [ ] Create demo GIF
- [ ] Finalize README.md

#### How to Test

```bash
# 1. Launch TUI
uv run coding-agent

# 2. Test basic interaction
# In TUI:
# > Read the README.md
# (Should display file contents)

# 3. Test file edit
# In TUI:
# > Edit pyproject.toml to change the description
# (Should show diff, ask for confirmation)

# 4. Test shell execution
# In TUI:
# > Run the tests with pytest
# (Should show command output)

# 5. Test git operations
# In TUI:
# > Show git status
# (Should display working tree status)

# 6. Test streaming
# In TUI:
# > Explain what this project does
# (Should stream response token by token)

# 7. Test error handling
# In TUI:
# > Read a file that doesn't exist
# (Should show clear error message)

# 8. Run integration tests
uv run pytest tests/integration/ -v

# 9. Run all tests
uv run pytest -v

# 10. Verify linting passes
uv run ruff check src/
uv run ruff format --check src/
uv run pyright src/
```

#### Definition of Done

- [ ] TUI launches without errors
- [ ] User can type input and see responses
- [ ] Responses stream token by token
- [ ] Tool calls show in TUI
- [ ] File diffs display correctly
- [ ] Status panel shows token usage
- [ ] All error messages are clear
- [ ] All tests pass
- [ ] Linting passes
- [ ] Demo GIF recorded
- [ ] README.md finalized

---

## Verification Checklist

### Before Each Week

- [ ] Run `uv sync` to ensure dependencies are up to date
- [ ] Run `uv run ruff check src/` to ensure no lint errors
- [ ] Run `uv run pyright src/` to ensure no type errors
- [ ] Run `uv run pytest -v` to ensure all tests pass

### After Each Week

- [ ] Commit all changes
- [ ] Push to GitHub
- [ ] Verify CI passes
- [ ] Update README.md if needed
- [ ] Update docs if needed

### Final Verification (Week 8)

- [ ] All features work as expected
- [ ] All tests pass
- [ ] All linting passes
- [ ] All type checking passes
- [ ] README.md is complete
- [ ] Demo GIF is recorded
- [ ] Code is clean and well-documented
- [ ] No secrets in code (API keys, passwords)
- [ ] `.env` is in `.gitignore`
- [ ] All error messages are helpful
- [ ] Performance is acceptable (responses < 1s for simple queries)

---

## Test Commands Summary

```bash
# Project setup
uv sync

# Linting
uv run ruff check src/
uv run ruff format --check src/

# Type checking
uv run pyright src/

# Unit tests
uv run pytest tests/ -v

# Specific test file
uv run pytest tests/test_llm.py -v

# Specific test
uv run pytest tests/test_llm.py::test_streaming -v

# Coverage
uv run pytest tests/ --cov=coding_agent --cov-report=html

# Integration tests (after Week 8)
uv run pytest tests/integration/ -v

# Manual testing
uv run coding-agent
```

---

## Troubleshooting

### Common Issues

#### 1. Docker not running
```bash
# Error: DockerException: Error while fetching server API version
# Solution: Start Docker Desktop or Docker daemon
```

#### 2. API key not set
```bash
# Error: AuthenticationError: No API key provided
# Solution: Set environment variable
export ANTHROPIC_API_KEY="your-key-here"
# Or add to .env file
```

#### 3. Port already in use
```bash
# Error: [Errno 98] Address already in use
# Solution: Kill process using the port
lsof -i :8000
kill <PID>
```

#### 4. Module not found
```bash
# Error: ModuleNotFoundError: No module named 'coding_agent'
# Solution: Ensure you're in the project directory and run
uv sync
```

#### 5. Type errors
```bash
# Error: pyright reports type errors
# Solution: Fix the type errors or add type: ignore comments
```

---

## Progress Tracking

### Weekly Progress

| Week | Status | Notes |
|------|--------|-------|
| Week 1 | ✅ | Project setup |
| Week 2 | ✅ | LLM client |
| Week 3 | ✅ | Tool registry + schema inference + @tool decorator |
| Week 4 | ✅ | File tools (read, write, edit, list) + gitignore filter |
| Week 5 | ✅ | Search + Shell + Git tools (8 tools total) |
| Week 6 | ✅ | Docker sandbox + exec_mode toggle (52 sandbox tests) |
| Week 7 | ⬜ | Agent loop |
| Week 8 | ⬜ | TUI + Polish |

### Feature Progress

| Feature | Status | Tests |
|---------|--------|-------|
| File read/write/edit | ✅ | ✅ (31 tests) |
| Search (ripgrep) | ✅ | ✅ (16 tests) |
| Shell execution | ✅ | ✅ (11 tests) |
| Git operations | ✅ | ✅ (15 tests) |
| Docker sandbox | ✅ | ✅ (52 tests: 40 mocked + 6 host + 6 Docker) |
| Agent loop | ⬜ | ⬜ |
| Permission system | ⬜ | ⬜ |
| Context management | ⬜ | ⬜ |
| TUI | ⬜ | ⬜ |
| Streaming | ✅ | ✅ |

### Quality Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Test coverage | >80% | 286 tests passing ✅ |
| Lint errors | 0 | 0 ✅ |
| Type errors | 0 | 0 ✅ |
| Documentation | Complete | ⬜ |
