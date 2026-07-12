# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CODING AGENT ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   CLI Layer  │    │   TUI Layer  │    │  API Layer   │                  │
│  │   (Typer)    │    │  (Textual)   │    │  (Future)    │                  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                  │
│         │                   │                   │                           │
│         └───────────────────┼───────────────────┘                           │
│                             │                                               │
│                    ┌────────▼────────┐                                      │
│                    │   Agent Core    │                                      │
│                    │   (orchestrator)│                                      │
│                    └────────┬────────┘                                      │
│                             │                                               │
│         ┌───────────────────┼───────────────────┐                           │
│         │                   │                   │                           │
│  ┌──────▼───────┐    ┌──────▼───────┐    ┌─────▼────────┐                 │
│  │  LLM Client  │    │ Tool Registry │    │   Sandbox    │                 │
│  │  (LiteLLM)   │    │   (tools)     │    │  (Docker)    │                 │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        Support Services                               │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │   │
│  │  │ Context  │  │ Session  │  │ Permission│  │  Logger  │            │   │
│  │  │ Manager  │  │ Manager  │  │  System   │  │(structlog)│            │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Responsibilities

### 1. CLI Layer (`main.py`)

**Purpose:** Parse command-line arguments, initialize components, launch TUI

```python
# Responsibilities:
# - Parse CLI arguments (model, workspace, permissions)
# - Validate environment (API keys, Docker)
# - Initialize all components
# - Launch TUI or REPL mode
```

**Dependencies:** Typer, Config, TUI

---

### 2. TUI Layer (`tui/app.py`)

**Purpose:** Display interface, handle user input, render responses

```python
# Responsibilities:
# - Render conversation history
# - Stream LLM responses token-by-token
# - Display tool calls and results
# - Show diff previews
# - Handle keyboard/mouse input
# - Display status (tokens, time, permissions)
```

**Dependencies:** Textual, Agent Core

---

### 3. Agent Core (`agent/loop.py`)

**Purpose:** Orchestrate the observe-think-act cycle

```python
# Responsibilities:
# - Manage conversation state
# - Build context for LLM
# - Send requests to LLM client
# - Parse tool calls from response
# - Route tools to registry
# - Handle permissions
# - Feed results back to LLM
# - Manage iteration limits
```

**Dependencies:** LLM Client, Tool Registry, Permission System, Context Manager

---

### 4. LLM Client (`llm/client.py`)

**Purpose:** Abstract LLM provider interactions

```python
# Responsibilities:
# - Handle streaming responses
# - Parse tool call schemas
# - Manage token counting
# - Handle rate limits and retries
# - Support multiple providers
# - Track usage and costs
```

**Dependencies:** LiteLLM, Token Counter

---

### 5. Tool Registry (`tools/registry.py`)

**Purpose:** Register, validate, and dispatch tool calls

```python
# Responsibilities:
# - Register tools with schemas
# - Generate JSON schema for LLM
# - Validate tool parameters
# - Route calls to correct handler
# - Track tool execution history
# - Handle tool errors gracefully
```

**Dependencies:** All Tool Implementations

---

### 6. Sandbox (`sandbox/docker.py`)

**Purpose:** Execute commands in isolated containers

```python
# Responsibilities:
# - Create/manage Docker containers
# - Mount workspace volumes
# - Set resource limits
# - Capture stdout/stderr
# - Handle timeouts
# - Cleanup resources
```

**Dependencies:** Docker SDK

---

## Data Flow Diagrams

### Flow 1: User Input → Agent Response

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│  User   │────▶│   TUI   │────▶│  Agent  │────▶│   LLM   │
│ (input) │     │ (app.py)│     │ (loop)  │     │ (client)│
└─────────┘     └─────────┘     └─────────┘     └─────────┘
                     │               │               │
                     │               │               │
                     │               │               ▼
                     │               │         ┌─────────┐
                     │               │         │ Tool    │
                     │               │         │ Parser  │
                     │               │         └─────────┘
                     │               │               │
                     │               │               ▼
                     │               │         ┌─────────┐
                     │               │◀────────│Permission│
                     │               │         │ Check   │
                     │               │         └─────────┘
                     │               │               │
                     │               │               ▼
                     │               │         ┌─────────┐
                     │               │◀────────│  Tool   │
                     │               │         │Executor │
                     │               │         └─────────┘
                     │               │               │
                     │               │               ▼
                     │               │         ┌─────────┐
                     │               │◀────────│ Result  │
                     │               │         │Formattr │
                     │               │         └─────────┘
                     │               │
                     ▼               │
               ┌─────────┐          │
               │ Display │◀─────────┘
               │ Response│
               └─────────┘
```

**Detailed Steps:**

1. **User types input** → TUI captures text
2. **TUI sends to Agent** → `agent.process_input(user_text)`
3. **Agent builds context** → Adds user message, system prompt, tool schemas
4. **Agent calls LLM** → `llm_client.complete(messages, tools)`
5. **LLM streams response** → Tokens arrive one by one
6. **TUI displays tokens** → Real-time rendering
7. **LLM finishes** → Response complete
8. **Agent checks for tool calls** → Parse JSON from response
9. **If tool calls exist:**
   a. **Permission check** → Is this allowed?
   b. **If denied** → Send error back to LLM, loop
   c. **If allowed** → Execute tool
   d. **Tool executes** → File read, shell command, etc.
   e. **Result captured** → Output, error, or diff
   f. **Result added to messages** → `{"tool_result": "..."}`
   g. **Loop back to step 4** → LLM sees result
10. **If no tool calls** → Response complete, show to user
11. **Repeat until:** No more tool calls OR max iterations

---

### Flow 2: File Edit Operation

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│   LLM   │────▶│ Permission│───▶│   Tool  │────▶│  File   │
│ (wants  │     │  Check   │     │ Executor│     │ System  │
│ to edit)│     └─────────┘     └─────────┘     └─────────┘
└─────────┘          │                │               │
                     │                │               │
                     ▼                ▼               ▼
              ┌─────────────┐  ┌───────────┐  ┌───────────┐
              │ User Confirm│  │ Show Diff │  │ Apply     │
              │ (if needed) │  │ Preview   │  │ Changes   │
              └─────────────┘  └───────────┘  └───────────┘
                     │                │               │
                     │                │               ▼
                     │                │         ┌───────────┐
                     │                │         │ Record    │
                     │                │         │ for Undo  │
                     │                │         └───────────┘
                     │                │
                     ▼                ▼
              ┌─────────────────────────────┐
              │ Return Result to LLM        │
              │ "File edited successfully"  │
              └─────────────────────────────┘
```

**Detailed Steps:**

1. **LLM generates edit call:**
   ```json
   {
     "tool": "edit_file",
     "args": {
       "path": "src/main.py",
       "old_text": "def old_name():",
       "new_text": "def new_name():"
     }
   }
   ```

2. **Permission check:**
   - Tool requires `WRITE` permission
   - Check if user has granted `WRITE`
   - If not, ask user for confirmation

3. **Read current file:**
   - `read_file(path)` → Get current content
   - Store as `original_content`

4. **Generate diff:**
   - Compare `original_content` with edit
   - Show unified diff or side-by-side
   - Highlight changes

5. **User confirmation (if enabled):**
   - Display diff in TUI
   - Wait for user to approve/deny
   - If denied, return error to LLM

6. **Apply edit:**
   - Find `old_text` in file
   - Replace with `new_text`
   - Write to file

7. **Record for undo:**
   - Store in SQLite:
     - `operation: "edit_file"`
     - `path: "src/main.py"`
     - `before: original_content`
     - `after: new_content`
     - `timestamp: now`

8. **Return result to LLM:**
   - `"Successfully edited src/main.py"`
   - LLM continues or finishes

---

### Flow 3: Shell Command Execution

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│   LLM   │────▶│Permission│───▶│ Sandbox │────▶│ Docker  │
│ (wants  │     │  Check   │     │ Manager │     │Container│
│ to run) │     └─────────┘     └─────────┘     └─────────┘
└─────────┘          │                │               │
                     │                │               │
                     ▼                ▼               ▼
              ┌─────────────┐  ┌───────────┐  ┌───────────┐
              │ User Confirm│  │ Create    │  │ Execute   │
              │ (if needed) │  │ Container │  │ Command   │
              └─────────────┘  └───────────┘  └───────────┘
                     │                │               │
                     │                │               ▼
                     │                │         ┌───────────┐
                     │                │         │ Capture   │
                     │                │         │ Output    │
                     │                │         └───────────┘
                     │                │               │
                     │                │               ▼
                     │                │         ┌───────────┐
                     │                │         │ Cleanup   │
                     │                │         │ Container │
                     │                │         └───────────┘
                     │                │
                     ▼                ▼
              ┌─────────────────────────────┐
              │ Return Result to LLM        │
              │ stdout + stderr + exit code │
              └─────────────────────────────┘
```

**Detailed Steps:**

1. **LLM generates shell call:**
   ```json
   {
     "tool": "execute_command",
     "args": {
       "command": "python -m pytest tests/ -v"
     }
   }
   ```

2. **Permission check:**
   - Tool requires `EXECUTE` permission
   - Check if user has granted `EXECUTE`
   - If not, ask user for confirmation

3. **Create Docker container:**
   - Use pre-built image `coding-agent-sandbox:latest`
   - Mount workspace: `-v /path/to/workspace:/workspace`
   - Set limits: `--memory=512m --cpus=1`
   - Set working directory: `--workdir=/workspace`

4. **Execute command:**
   - `container.exec_run("sh -c 'python -m pytest tests/ -v'")`
   - Capture stdout and stderr
   - Wait for completion or timeout

5. **Handle timeout:**
   - If timeout (default 30s):
     - Kill container
     - Return timeout error
     - Suggest breaking command into smaller parts

6. **Capture output:**
   - stdout → Command output
   - stderr → Error messages
   - exit_code → Success (0) or failure

7. **Cleanup container:**
   - Remove container (even on error)
   - Free resources

8. **Return result to LLM:**
   ```json
   {
     "stdout": "tests/test_main.py::test_read PASSED...",
     "stderr": "",
     "exit_code": 0
   }
   ```

---

### Flow 4: Context Window Management

```
┌─────────────────────────────────────────────────────────────┐
│                   CONTEXT WINDOW MANAGEMENT                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐                                            │
│  │ New Message  │                                            │
│  │ Arrives      │                                            │
│  └──────┬───────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────┐     ┌──────────────┐                      │
│  │ Token Counter│────▶│ Check Limit  │                      │
│  │ (LiteLLM)   │     │              │                      │
│  └──────────────┘     └──────┬───────┘                      │
│                              │                              │
│              ┌───────────────┼───────────────┐              │
│              │               │               │              │
│              ▼               ▼               ▼              │
│     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│     │ Under Limit  │ │ At Limit     │ │ Over Limit   │    │
│     │ (normal)     │ │ (summarize)  │ │ (aggressive) │    │
│     └──────┬───────┘ └──────┬───────┘ └──────┬───────┘    │
│            │                │                │              │
│            │                ▼                │              │
│            │         ┌──────────────┐        │              │
│            │         │ Summarize    │        │              │
│            │         │ Old Messages │        │              │
│            │         │ (keep last 5)│        │              │
│            │         └──────┬───────┘        │              │
│            │                │                │              │
│            │                ▼                ▼              │
│            │         ┌──────────────┐                      │
│            │         │ Rebuild      │                      │
│            └────────▶│ Message List │◀─────────────────────┘
│                      └──────┬───────┘
│                             │
│                             ▼
│                      ┌──────────────┐
│                      │ Send to LLM  │
│                      └──────────────┘
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Message List Structure:**

```python
messages = [
    # System prompt (always first, ~500 tokens)
    {"role": "system", "content": system_prompt},

    # Project context (from AGENTS.md, README.md, ~1000 tokens)
    {"role": "system", "content": project_context},

    # Summarized old messages (if needed, ~2000 tokens)
    {"role": "system", "content": "Summary of previous conversation: ..."},

    # Recent messages (last 10-20, ~80000 tokens)
    {"role": "user", "content": "Fix the bug in main.py"},
    {"role": "assistant", "content": "I'll read the file first", "tool_calls": [...]},
    {"role": "tool", "content": "file contents..."},
    {"role": "assistant", "content": "Found the bug, editing..."},
    # ... more messages

    # New user message (just arrived)
    {"role": "user", "content": "Now run the tests"},
]
```

**Summarization Strategy:**

```python
async def summarize_messages(messages: list[Message]) -> str:
    # Take messages except last 5
    old_messages = messages[:-5]
    recent_messages = messages[-5:]

    # Build summary prompt
    summary_prompt = f"""
    Summarize this conversation concisely:
    {format_messages(old_messages)}

    Focus on:
    - What the user asked
    - What was done
    - Key decisions made
    - Any errors encountered
    """

    # Use LLM to summarize (cheap model)
    summary = await llm_client.complete(
        model="claude-3-5-haiku-20241022",  # Fast, cheap
        messages=[{"role": "user", "content": summary_prompt}],
    )

    return summary
```

---

### Flow 5: Permission System

```
┌─────────────────────────────────────────────────────────────┐
│                    PERMISSION FLOW                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐                                            │
│  │ Tool Call    │                                            │
│  │ Received     │                                            │
│  └──────┬───────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────┐     ┌──────────────┐                      │
│  │ Get Tool     │────▶│ Get Required │                      │
│  │ Metadata     │     │ Permission   │                      │
│  └──────────────┘     └──────┬───────┘                      │
│                              │                              │
│                              ▼                              │
│                    ┌──────────────┐                          │
│                    │ User Has     │                          │
│                    │ Permission?  │                          │
│                    └──────┬───────┘                          │
│                           │                                 │
│              ┌────────────┼────────────┐                    │
│              │            │            │                    │
│              ▼            ▼            ▼                    │
│     ┌──────────────┐ ┌──────────┐ ┌──────────────┐        │
│     │ YES (auto)   │ │ ASK      │ │ NO (deny)    │        │
│     │              │ │ (confirm)│ │              │        │
│     └──────┬───────┘ └────┬─────┘ └──────┬───────┘        │
│            │               │              │                 │
│            │               ▼              │                 │
│            │        ┌──────────────┐      │                 │
│            │        │ Show to User │      │                 │
│            │        │ "Allow? [y/n]"│     │                 │
│            │        └──────┬───────┘      │                 │
│            │               │              │                 │
│            │        ┌──────┼──────┐       │                 │
│            │        │      │      │       │                 │
│            │        ▼      ▼      ▼       │                 │
│            │   ┌──────┐ ┌──────┐ ┌──────┐│                 │
│            │   │ YES  │ │ NO   │ │AUTO  ││                 │
│            │   │      │ │      │ │(10s) ││                 │
│            │   └──┬───┘ └──┬───┘ └──┬───┘│                 │
│            │      │        │        │    │                 │
│            │      │        │        │    │                 │
│            ▼      ▼        ▼        ▼    ▼                 │
│     ┌─────────────────────────────────────────┐            │
│     │            EXECUTE TOOL                  │            │
│     │  (or return permission denied error)     │            │
│     └─────────────────────────────────────────┘            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Permission Levels:**

```python
class Permission(Enum):
    READ = 0      # Auto-allow: file read, search, git status
    WRITE = 1     # Ask once per session: file edit, git commit
    EXECUTE = 2   # Ask every time: shell commands
    DANGEROUS = 3 # Always ask + show warning: rm -rf, system commands
```

**Trust Levels:**

```python
# User can set trust level in config or CLI
trust_levels = {
    "readonly": Permission.READ,          # Only read operations
    "standard": Permission.WRITE,         # Read + write
    "full": Permission.EXECUTE,           # Read + write + execute
    "unsafe": Permission.DANGEROUS,       # Everything (not recommended)
}
```

**Auto-Approval Rules:**

```python
# Commands that are always safe (no confirmation needed)
auto_approve = [
    "ls", "pwd", "echo", "cat", "head", "tail",  # Read-only
    "git status", "git log", "git diff",          # Git read
    "python -m pytest",                           # Tests (read-only)
]

# Commands that always need confirmation
always_confirm = [
    "rm", "rm -rf", "sudo", "chmod",             # Destructive
    "git push", "git reset", "git rebase",        # Git write
]
```

---

### Flow 6: Session Management

```
┌─────────────────────────────────────────────────────────────┐
│                    SESSION LIFECYCLE                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐                                            │
│  │ User Starts  │                                            │
│  │ Agent        │                                            │
│  └──────┬───────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────┐     ┌──────────────┐                      │
│  │ Check for    │────▶│ Resume or    │                      │
│  │ Session ID   │     │ New Session  │                      │
│  └──────────────┘     └──────┬───────┘                      │
│                              │                              │
│              ┌───────────────┼───────────────┐              │
│              │               │               │              │
│              ▼               ▼               ▼              │
│     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│     │ Resume       │ │ New Session  │ │ List         │    │
│     │ (load from   │ │ (create new) │ │ (show past)  │    │
│     │  SQLite)     │ │              │ │              │    │
│     └──────┬───────┘ └──────┬───────┘ └──────┬───────┘    │
│            │                │                │              │
│            │                ▼                │              │
│            │         ┌──────────────┐        │              │
│            │         │ Load Context │        │              │
│            │         │ (AGENTS.md,  │        │              │
│            │         │  README.md)  │        │              │
│            │         └──────┬───────┘        │              │
│            │                │                │              │
│            ▼                ▼                ▼              │
│     ┌─────────────────────────────────────────┐            │
│     │          RUN AGENT LOOP                  │            │
│     │  (all interactions saved to SQLite)      │            │
│     └─────────────────────────────────────────┘            │
│                          │                                  │
│                          ▼                                  │
│  ┌─────────────────────────────────────────┐               │
│  │           SESSION END                    │               │
│  │  - Save final state                     │               │
│  │  - Calculate total tokens used          │               │
│  │  - Estimate total cost                  │               │
│  │  - Show session summary                 │               │
│  └─────────────────────────────────────────┘               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Session Database Schema:**

```sql
-- Sessions table
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model TEXT,
    workspace_path TEXT,
    total_tokens INTEGER DEFAULT 0,
    total_cost REAL DEFAULT 0.0,
    status TEXT DEFAULT 'active'  -- active, completed, failed
);

-- Messages table
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    role TEXT,  -- user, assistant, tool, system
    content TEXT,
    tool_calls TEXT,  -- JSON array of tool calls
    tool_results TEXT,  -- JSON array of results
    tokens_used INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Operations table (for undo)
CREATE TABLE operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    operation_type TEXT,  -- read, write, edit, execute
    tool_name TEXT,
    parameters TEXT,  -- JSON
    result TEXT,
    file_path TEXT,
    before_content TEXT,  -- for undo
    after_content TEXT,   -- for undo
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Project Structure

```
coding-agent/
├── pyproject.toml              # Project config, dependencies
├── Dockerfile.sandbox          # Docker image for sandbox
├── docker-compose.yml          # Local dev setup
├── .env.example                # Environment variables template
├── .gitignore
├── README.md
│
├── src/
│   └── coding_agent/
│       ├── __init__.py         # Package metadata
│       ├── main.py             # CLI entry point
│       ├── config.py           # Pydantic settings
│       ├── logging.py          # Structured logging setup
│       │
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── loop.py         # Core agent loop
│       │   ├── context.py      # Context window management
│       │   └── permissions.py  # Permission system
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── client.py       # LiteLLM wrapper
│       │   ├── streaming.py    # Stream handling
│       │   └── tokens.py       # Token counting + cost tracking
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── registry.py     # Tool registration + dispatch
│       │   ├── base.py         # Base tool class
│       │   ├── file_ops.py     # Read/write/edit files
│       │   ├── search.py       # ripgrep + glob
│       │   ├── shell.py        # Shell execution
│       │   └── git.py          # Git operations
│       │
│       ├── sandbox/
│       │   ├── __init__.py
│       │   ├── docker.py       # Docker container management
│       │   └── executor.py     # Sandboxed execution
│       │
│       ├── session/
│       │   ├── __init__.py
│       │   ├── manager.py      # Session persistence
│       │   └── history.py      # Operation history (undo)
│       │
│       └── tui/
│           ├── __init__.py
│           ├── app.py          # Textual app
│           ├── screens.py      # Different views
│           └── widgets.py      # Custom widgets
│
├── tests/
│   ├── conftest.py             # Fixtures
│   ├── test_agent_loop.py
│   ├── test_tools/
│   │   ├── test_file_ops.py
│   │   ├── test_search.py
│   │   ├── test_shell.py
│   │   └── test_git.py
│   ├── test_sandbox.py
│   ├── test_llm.py
│   └── test_session.py
│
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI
│
└── docs/
    ├── architecture.md         # This file
    ├── features.md
    ├── techstack.md
    └── phase-checklist.md
```

---

## Error Handling Strategy

### Error Categories

```python
class ErrorCode(Enum):
    # Tool errors (recoverable)
    FILE_NOT_FOUND = "E001"
    PERMISSION_DENIED = "E002"
    INVALID_SYNTAX = "E003"
    COMMAND_FAILED = "E004"
    TIMEOUT = "E005"

    # LLM errors (retryable)
    RATE_LIMIT = "E100"
    CONTEXT_TOO_LONG = "E101"
    INVALID_RESPONSE = "E102"

    # System errors (critical)
    DOCKER_NOT_RUNNING = "E200"
    API_KEY_MISSING = "E201"
    DATABASE_ERROR = "E202"
```

### Error Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Tool Fails  │────▶│ Classify    │────▶│ Handle      │
│             │     │ Error       │     │             │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                    │
              ┌────────────┼────────────┐       │
              │            │            │       │
              ▼            ▼            ▼       ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
       │ Retry    │ │ Fallback │ │ Ask User │ │ Abort    │
       │ (3 times)│ │ (alt cmd)│ │ (help)   │ │ (report) │
       └──────────┘ └──────────┘ └──────────┘ └──────────┘
```

### Retry Logic

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((RateLimitError, TimeoutError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def safe_tool_execution(tool, *args, **kwargs):
    try:
        return await tool.execute(*args, **kwargs)
    except ToolError as e:
        logger.error("tool_failed", tool=tool.name, error=str(e))
        raise
```

---

## Security Considerations

### 1. API Key Protection
- Never log API keys
- Never store in code
- Use environment variables
- `.env` file in `.gitignore`

### 2. Sandbox Isolation
- Container runs as non-root user
- Limited CPU/memory
- No network access (optional)
- Workspace mounted read-write only

### 3. Permission System
- Default to least privilege
- User confirmation for risky ops
- Audit log of all operations
- No `sudo` in sandbox

### 4. Input Validation
- Validate all file paths (no `../`)
- Validate commands (no injection)
- Validate tool parameters (schema check)
- Sanitize user input

---

## Performance Considerations

### 1. Streaming
- Token-by-token display
- No buffering delays
- Immediate feedback

### 2. Caching
- Cache file reads (invalidate on write)
- Cache search results (short TTL)
- Cache token counts

### 3. Async Operations
- Non-blocking I/O throughout
- Concurrent tool execution (where safe)
- Parallel file reads

### 4. Resource Limits
- Docker container limits
- Context window limits
- Iteration limits
- Timeout limits
