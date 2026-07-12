# Features

## Core Features (Phase 1)

### 1. File System Tools

#### 1.1 Read File
- **Description:** Read contents of any file in the workspace
- **User Story:** As a developer, I want the agent to read my source files so it can understand my codebase
- **Acceptance Criteria:**
  - Can read any file type (text-based)
  - Handles binary files gracefully (returns error or hex dump)
  - Respects `.gitignore` patterns
  - Returns file content with line numbers
  - Supports reading specific line ranges (offset + limit)
- **Permission Level:** READ
- **Tools Used:** `pathlib`, `aiofiles`

#### 1.2 Write File
- **Description:** Create or overwrite a file with new content
- **User Story:** As a developer, I want the agent to create new files or update existing ones
- **Acceptance Criteria:**
  - Creates parent directories if they don't exist
  - Overwrites existing files with confirmation (if enabled)
  - Returns success message with file path
  - Handles permission errors gracefully
- **Permission Level:** WRITE
- **Tools Used:** `pathlib`, `aiofiles`

#### 1.3 Edit File
- **Description:** Make targeted edits to specific parts of a file
- **User Story:** As a developer, I want the agent to make precise edits without rewriting entire files
- **Acceptance Criteria:**
  - Supports exact string replacement
  - Supports line-based editing (replace line N)
  - Shows diff preview before applying changes
  - Can undo last edit (via session history)
  - Validates edit didn't break syntax (optional, via tree-sitter)
- **Permission Level:** WRITE
- **Tools Used:** `pathlib`, `aiofiles`

#### 1.4 List Files
- **Description:** List files and directories in a given path
- **User Story:** As a developer, I want the agent to explore my project structure
- **Acceptance Criteria:**
  - Lists files with metadata (size, modified date)
  - Supports glob patterns (e.g., `**/*.py`)
  - Respects `.gitignore`
  - Can show tree view (nested structure)
- **Permission Level:** READ
- **Tools Used:** `pathlib`, `glob`

### 2. Search Tools

#### 2.1 Content Search (ripgrep)
- **Description:** Search file contents using regex patterns
- **User Story:** As a developer, I want the agent to find code patterns across my codebase
- **Acceptance Criteria:**
  - Uses `rg` (ripgrep) for fast searching
  - Returns file paths with line numbers and context
  - Supports regex patterns
  - Can filter by file type (e.g., `--type py`)
  - Respects `.gitignore`
- **Permission Level:** READ
- **Tools Used:** `ripgrep`, `asyncio.subprocess`

#### 2.2 File Search (glob)
- **Description:** Find files by name patterns
- **User Story:** As a developer, I want the agent to find files matching specific patterns
- **Acceptance Criteria:**
  - Supports glob patterns (`*.py`, `src/**/*.ts`)
  - Returns full paths
  - Can search specific directories
- **Permission Level:** READ
- **Tools Used:** `pathlib`, `glob`

### 3. Shell Execution

#### 3.1 Run Shell Command
- **Description:** Execute shell commands in a sandboxed environment
- **User Story:** As a developer, I want the agent to run tests, build commands, or system operations
- **Acceptance Criteria:**
  - Executes commands in Docker container
  - Captures stdout and stderr separately
  - Enforces timeout (default 30s, configurable)
  - Returns exit code
  - Handles commands that produce no output
- **Permission Level:** EXECUTE
- **Tools Used:** `asyncio.subprocess`, Docker SDK

#### 3.2 Interactive Shell
- **Description:** Maintain a persistent shell session for multi-step commands
- **User Story:** As a developer, I want the agent to run commands that depend on previous state
- **Acceptance Criteria:**
  - Maintains working directory across commands
  - Preserves environment variables
  - Can run commands in sequence (e.g., `cd dir && make`)
- **Permission Level:** EXECUTE
- **Tools Used:** `asyncio.subprocess`, Docker SDK

### 4. Git Tools

#### 4.1 Git Status
- **Description:** Show working tree status
- **User Story:** As a developer, I want the agent to know the current state of my repo
- **Acceptance Criteria:**
  - Shows modified, staged, untracked files
  - Shows branch name
  - Shows ahead/behind remote
- **Permission Level:** READ
- **Tools Used:** `asyncio.subprocess`

#### 4.2 Git Diff
- **Description:** Show changes between commits, working tree, etc.
- **User Story:** As a developer, I want the agent to see what changed
- **Acceptance Criteria:**
  - Can show unstaged changes
  - Can show staged changes
  - Can show diff for specific files
  - Returns unified diff format
- **Permission Level:** READ
- **Tools Used:** `asyncio.subprocess`

#### 4.3 Git Add + Commit
- **Description:** Stage and commit changes
- **User Story:** As a developer, I want the agent to commit changes with meaningful messages
- **Acceptance Criteria:**
  - Can stage specific files or all changes
  - Generates meaningful commit messages
  - Returns commit hash
- **Permission Level:** WRITE
- **Tools Used:** `asyncio.subprocess`

#### 4.4 Git Log
- **Description:** Show commit history
- **User Story:** As a developer, I want the agent to understand recent changes
- **Acceptance Criteria:**
  - Shows last N commits (default 10)
  - Shows commit hash, author, date, message
  - Can filter by branch
- **Permission Level:** READ
- **Tools Used:** `asyncio.subprocess`

---

## Agent Features (Phase 1)

### 5. Agent Loop

#### 5.1 Core Loop
- **Description:** Observe → Think → Act → Observe cycle
- **User Story:** As a user, I want the agent to autonomously complete tasks
- **Acceptance Criteria:**
  - Receives user input
  - Sends to LLM with tool schemas
  - Parses tool calls from response
  - Executes tools with permission checks
  - Feeds results back to LLM
  - Repeats until task complete or max iterations reached
  - Max iterations configurable (default 20)
- **Flow:**
  ```
  User Input → Context Builder → LLM → Tool Parser → Permission Check → Tool Executor → Result Formatter → Loop/Exit
  ```

#### 5.2 Streaming Response
- **Description:** Stream LLM responses token-by-token
- **User Story:** As a user, I want to see the agent's thinking in real-time
- **Acceptance Criteria:**
  - Streams text tokens as they arrive
  - Shows tool calls as they're parsed
  - Handles partial JSON in tool calls
  - Graceful handling of stream interruptions
- **Flow:**
  ```
  LLM Stream → Token Buffer → Tool Call Detector → Text Yielder → TUI Display
  ```

#### 5.3 Multi-Model Support
- **Description:** Support multiple LLM providers via LiteLLM
- **User Story:** As a user, I want to choose which model to use
- **Acceptance Criteria:**
  - Supports Anthropic Claude models
  - Supports OpenAI GPT models
  - Supports Google Gemini models
  - Model selection via config or CLI flag
  - Graceful fallback if provider unavailable
- **Supported Models:**
  - `claude-3-5-sonnet-20241022` (Anthropic)
  - `gpt-4o` (OpenAI)
  - `gemini-2.0-flash` (Google)

### 6. Permission System

#### 6.1 Permission Levels
- **Description:** Control what the agent can do
- **User Story:** As a user, I want to control the agent's access
- **Permission Levels:**
  - `READ` - Read files, search, git status (safe)
  - `WRITE` - Edit files, create files, git commit (modifies state)
  - `EXECUTE` - Run shell commands (potentially dangerous)
  - `DANGEROUS` - Destructive operations, system commands
- **Acceptance Criteria:**
  - Each tool declares its permission level
  - Agent checks permissions before execution
  - User can set global permission level
  - User can override per-operation

#### 6.2 User Confirmation
- **Description:** Ask user before sensitive operations
- **User Story:** As a user, I want to approve risky actions
- **Acceptance Criteria:**
  - Configurable confirmation thresholds
  - Shows preview of what will change
  - Can approve/deny individual operations
  - Can set "trust mode" for known-safe patterns

### 7. Context Management

#### 7.1 Context Window
- **Description:** Manage LLM context window limits
- **User Story:** As a user, I want the agent to handle large codebases without losing context
- **Acceptance Criteria:**
  - Tracks token usage per message
  - Summarizes old messages when approaching limit
  - Keeps system prompt and recent messages
  - Configurable max tokens (default 100k)
- **Flow:**
  ```
  New Message → Token Counter → Check Limit → If Over → Summarize Old → Add New → Trim Summary
  ```

#### 7.2 Project Context
- **Description:** Load project-specific context files
- **User Story:** As a user, I want the agent to understand my project conventions
- **Acceptance Criteria:**
  - Reads `AGENTS.md` if present
  - Reads `README.md` if present
  - Reads `.cursorrules` if present (for familiarity)
  - Injects into system prompt
- **Priority Files:**
  - `AGENTS.md` - Agent instructions
  - `README.md` - Project overview
  - `CONTRIBUTING.md` - Contribution guidelines
  - `.gitignore` - Patterns to ignore

### 8. Session Management

#### 8.1 Session Persistence
- **Description:** Save and restore conversation state
- **User Story:** As a user, I want to resume conversations later
- **Acceptance Criteria:**
  - Saves conversation history to SQLite
  - Stores tool call results
  - Can list past sessions
  - Can resume a session by ID
- **Storage:** SQLite database

#### 8.2 Session History
- **Description:** Track all operations for undo capability
- **User Story:** As a user, I want to undo agent actions
- **Acceptance Criteria:**
  - Records all file changes with before/after
  - Records shell commands executed
  - Can undo last N operations
  - Shows history of changes
- **Storage:** SQLite database

---

## Infrastructure Features (Phase 1)

### 9. Docker Sandboxing

#### 9.1 Container Management
- **Description:** Run agent operations in isolated containers
- **User Story:** As a user, I want the agent to execute code safely
- **Acceptance Criteria:**
  - Creates container from pre-built image
  - Mounts workspace as volume
  - Sets resource limits (CPU, memory)
  - Cleans up after execution
  - Handles container startup failures
- **Docker Image:** Custom image with Python, Node, common dev tools

#### 9.2 Resource Limits
- **Description:** Prevent agent from consuming excessive resources
- **User Story:** As a user, I want the agent to not crash my machine
- **Acceptance Criteria:**
  - Memory limit (default 512MB)
  - CPU limit (default 1 core)
  - Execution timeout (default 30s)
  - Disk space limit (optional)
  - Network isolation (optional)

### 10. Configuration

#### 10.1 Settings Management
- **Description:** Configure agent behavior via config files
- **User Story:** As a user, I want to customize the agent
- **Acceptance Criteria:**
  - Reads from `pyproject.toml` or `.env`
  - Supports environment variables
  - CLI flags override config
  - Validates config on startup
- **Config Options:**
  - `LLM_PROVIDER` - Which LLM to use
  - `LLM_MODEL` - Specific model name
  - `MAX_ITERATIONS` - Agent loop limit
  - `MAX_TOKENS` - Context window size
  - `SANDBOX_ENABLED` - Docker on/off
  - `PERMISSION_LEVEL` - Default permission
  - `LOG_LEVEL` - Logging verbosity

### 11. Logging & Monitoring

#### 11.1 Structured Logging
- **Description:** Log all operations for debugging
- **User Story:** As a developer, I want to debug agent behavior
- **Acceptance Criteria:**
  - Logs tool calls with parameters
  - Logs LLM requests/responses
  - Logs permission checks
  - Logs errors with stack traces
  - Structured JSON format for parsing
- **Log Levels:**
  - `DEBUG` - Verbose output
  - `INFO` - Normal operations
  - `WARNING` - Recoverable errors
  - `ERROR` - Failures
  - `CRITICAL` - System failures

#### 11.2 Usage Tracking
- **Description:** Track token usage and costs
- **User Story:** As a user, I want to know how much I'm spending
- **Acceptance Criteria:**
  - Counts tokens per request
  - Tracks total usage per session
  - Estimates cost based on model pricing
  - Stores usage history in SQLite
  - Shows summary at session end

### 12. Error Handling

#### 12.1 Retry Logic
- **Description:** Automatically retry failed operations
- **User Story:** As a user, I want the agent to recover from transient failures
- **Acceptance Criteria:**
  - Retries on network errors (up to 3 times)
  - Exponential backoff
  - Retries on rate limits
  - No retry on permanent errors (404, 401)
- **Implementation:** `tenacity` library

#### 12.2 Graceful Degradation
- **Description:** Continue working when some tools fail
- **User Story:** As a user, I want the agent to keep trying even if one operation fails
- **Acceptance Criteria:**
  - If one tool fails, continues with others
  - Reports failures clearly
  - Suggests alternatives when possible
  - Never crashes silently

---

## TUI Features (Phase 1)

### 13. Textual Interface

#### 13.1 Main View
- **Description:** Primary interaction screen
- **User Story:** As a user, I want a clean, readable interface
- **Acceptance Criteria:**
  - Shows conversation history
  - Shows agent's thinking (streaming)
  - Shows tool calls and results
  - Input area at bottom
  - Scrollback for long conversations

#### 13.2 Diff View
- **Description:** Show file changes before applying
- **User Story:** As a user, I want to see what the agent will change
- **Acceptance Criteria:**
  - Side-by-side diff (or unified)
  - Syntax highlighting
  - Can approve/deny changes
  - Shows line numbers

#### 13.3 Status Panel
- **Description:** Show current agent state
- **User Story:** As a user, I want to know what the agent is doing
- **Acceptance Criteria:**
  - Shows current tool being executed
  - Shows token usage
  - Shows elapsed time
  - Shows permission level

---

## Future Features (Phase 2+)

### 14. Sub-Agents (Phase 2)
- Spawn child agents for parallel tasks
- Coordinate multiple agents
- Aggregate results

### 15. Plan/Build Mode (Phase 2)
- Plan mode: agent only reads and plans
- Build mode: agent executes changes
- User switches between modes

### 16. MCP Integration (Phase 2)
- Connect to external MCP servers
- Extend tools via plugins
- Custom tool creation

### 17. Hooks (Phase 2)
- Pre/post execution hooks
- Custom validation logic
- Integration with CI/CD

### 18. Undo System (Phase 2)
- Full undo/redo stack
- Snapshot-based recovery
- Selective undo (specific operations)

### 19. Background Jobs (Phase 2)
- Queue long-running tasks
- Monitor progress
- Cancel running jobs

### 20. Cost Optimization (Phase 2)
- Auto-select cheapest model for simple tasks
- Cache common queries
- Batch similar operations
