# Phase 7: Agent Loop + Permissions

## Status: Ready to Build

---

## Overview

Phase 7 is the **core of the project** — it connects all existing components (LLM client, tools, sandbox) into a functioning agent. Without this phase, the tools exist but nothing drives them.

**What we're building:**
- `agent/permissions.py` — Permission system (gate tool execution)
- `agent/context.py` — Context window management (conversation, token tracking, summarization)
- `agent/system_prompt.py` — System prompt builder (static + dynamic sections)
- `agent/loop.py` — Core agentic loop (observe → think → act → repeat)
- `agent/events.py` — Event types for TUI communication

**What already exists (Weeks 1-6):**
- LLM client with Gemini + OpenRouter (native SDKs, NOT LiteLLM)
- 10 tools: read_file, write_file, edit_file, list_files, search_content, search_files, execute_command, git_status, git_diff, git_log, git_commit
- Docker sandbox with host fallback
- 286 tests passing, 0 lint errors, 0 type errors

---

## Architecture

### Data Flow

```
User types "Fix the bug in main.py"
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                    AGENT LOOP                            │
│                                                          │
│  1. Build system prompt + project context                │
│  2. Add user message to conversation                     │
│  3. Call LLM (streaming) with messages + tool schemas    │
│  4. Stream tokens to TUI in real-time                    │
│  5. Parse tool calls from stream                         │
│  6. For each tool call:                                  │
│     a. Permission check ──► ask user if needed           │
│     b. Execute via ToolRegistry                          │
│     c. Add result to conversation                        │
│  7. Loop back to step 3 (if tool calls existed)          │
│  8. Done (no more tool calls OR max iterations)          │
└─────────────────────────────────────────────────────────┘
```

### Component Diagram

```
main.py (Typer CLI)
    │ creates
    ▼
AgentLoop(llm_client, tool_registry, permissions, context)
    │
    ├──► ContextManager.build_messages()
    │         returns: [{"role": "system", ...}, {"role": "user", ...}]
    │
    ├──► LLMClient.stream(messages, tools)
    │         yields: StreamEvent(TEXT="I'll"), StreamEvent(TEXT=" read"), 
    │                  ..., StreamEvent(TOOL_CALL={...}), StreamEvent(DONE)
    │
    ├──► PermissionManager.check(tool_name, level)
    │         returns: True/False
    │
    ├──► ToolRegistry.execute_from_llm(tool_call)
    │         returns: ToolResult(success=True, output="file contents...")
    │
    └──► yields AgentEvent back to caller
              used by TUI (Week 8) or REPL
```

---

## Module 1: `agent/events.py`

**Purpose:** Typed events for TUI communication.

```python
"""Event types for agent-to-TUI communication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EventType(Enum):
    """Types of events the agent loop can emit."""

    TEXT = "text"                    # Streaming text token
    TOOL_START = "tool_start"        # Tool call beginning
    TOOL_RESULT = "tool_result"      # Tool execution result
    PERMISSION_REQUEST = "perm_req"  # Need user approval
    PERMISSION_RESPONSE = "perm_res" # User responded
    USAGE = "usage"                  # Token usage update
    DONE = "done"                    # Agent finished
    ERROR = "error"                  # Something went wrong
    MAX_ITERATIONS = "max_iter"      # Hit iteration limit


@dataclass
class AgentEvent:
    """A single event from the agent loop."""

    type: EventType
    data: Any = None
```

**Notes:**
- Simple dataclasses, no logic
- `data` field is typed loosely for flexibility
- TUI (Week 8) consumes these events to render the interface

---

## Module 2: `agent/permissions.py`

**Purpose:** Gate tool execution based on operation risk level.

```python
"""Permission system for tool execution."""

from __future__ import annotations

from enum import Enum
from typing import Callable, Awaitable


class Permission(Enum):
    """Permission levels for tool operations."""

    READ = "read"            # Auto-allow: file read, search, git status
    WRITE = "write"          # Ask once per session: file edit, git commit
    EXECUTE = "execute"      # Ask every time: shell commands
    DANGEROUS = "dangerous"  # Always ask + show warning


class TrustLevel(Enum):
    """Trust levels that determine which operations are auto-allowed."""

    READONLY = "readonly"    # Only READ operations
    STANDARD = "standard"    # READ + WRITE (default)
    FULL = "full"            # READ + WRITE + EXECUTE
    UNSAFE = "unsafe"        # Everything (not recommended)


# Permission hierarchy: higher index = more restrictive
_PERMISSION_HIERARCHY = {
    Permission.READ: 0,
    Permission.WRITE: 1,
    Permission.EXECUTE: 2,
    Permission.DANGEROUS: 3,
}

# Trust level to max auto-allowed permission
_TRUST_TO_PERMISSION = {
    TrustLevel.READONLY: Permission.READ,
    TrustLevel.STANDARD: Permission.WRITE,
    TrustLevel.FULL: Permission.EXECUTE,
    TrustLevel.UNSAFE: Permission.DANGEROUS,
}


class PermissionManager:
    """Decides whether a tool call needs user confirmation.

    Usage:
        pm = PermissionManager(level=Permission.WRITE)
        
        # For each tool call:
        if pm.check(tool_name, tool_permission_level):
            # Auto-allowed
            result = await execute_tool(tool_name, args)
        else:
            # Needs user confirmation
            approved = await ask_user(tool_name, args)
            if approved:
                pm.approve_tool(tool_name)  # Remember for session
                result = await execute_tool(tool_name, args)
    """

    def __init__(self, level: Permission = Permission.WRITE) -> None:
        self.level = level
        self._approved_writes: set[str] = set()
    
    def check(self, tool_name: str, permission_level: str) -> bool:
        """Check if a tool execution is allowed.

        Returns True if auto-allowed, False if needs user confirmation.
        """
        required = Permission(permission_level)
        
        # Read is always allowed
        if required == Permission.READ:
            return True
        
        # Dangerous always asks
        if required == Permission.DANGEROUS:
            return False
        
        # Write: ask once per tool name, then auto-allow
        if required == Permission.WRITE:
            if tool_name in self._approved_writes:
                return True
            return False
        
        # Execute: ask every time (unless trust level is FULL+)
        if required == Permission.EXECUTE:
            return False
        
        return False
    
    def approve_tool(self, tool_name: str) -> None:
        """Mark a write tool as approved for this session."""
        self._approved_writes.add(tool_name)
    
    def reset(self) -> None:
        """Reset all approvals (e.g., for new session)."""
        self._approved_writes.clear()


def get_permission_level(tool_name: str) -> Permission:
    """Look up the permission level for a tool by name.

    This reads from the tool registry's metadata. Call this
    to determine what permission check is needed.
    """
    # This will be wired to ToolRegistry.get(name).permission_level
    # Returns Permission.READ as default (safe fallback)
    from coding_agent.tools.registry import tool_registry
    
    try:
        tool = tool_registry.get(tool_name)
        return Permission(tool.permission_level)
    except (KeyError, ValueError):
        return Permission.READ
```

**Key behaviors:**
- `READ` tools: always allowed, no questions
- `WRITE` tools: ask once per tool name per session (approve once, auto-allow next time)
- `EXECUTE` tools: ask every time (show the command)
- `DANGEROUS` tools: always ask + show red warning

**Trust levels** (configurable via CLI):
- `readonly` → only READ allowed
- `standard` → READ + WRITE (default)
- `full` → READ + WRITE + EXECUTE
- `unsafe` → everything

---

## Module 3: `agent/system_prompt.py`

**Purpose:** Build the system prompt with static + dynamic sections.

This is the **brain** of the agent — it tells the LLM how to behave.

```python
"""System prompt builder for the coding agent.

The prompt is assembled in two layers:
1. Static sections (cacheable, same every session)
2. Dynamic sections (per-session: environment, project context, memory)
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from coding_agent.config import Settings


# ============================================================================
# STATIC SECTIONS (cacheable)
# ============================================================================

def _identity_section() -> str:
    """Section 1: Who is this agent."""
    return """You are a coding agent — an AI-powered software engineering assistant that reads, edits, and executes code in the user's workspace.

You are precise, helpful, and autonomous. You figure out what files to read, what code to change, and what commands to run — then do it.

You have access to tools for:
- Reading and writing files
- Searching codebases (content and filenames)
- Running shell commands (in a sandboxed environment)
- Git operations (status, diff, log, commit)"""


def _core_principles_section() -> str:
    """Section 2: How the agent behaves."""
    return """## Core Principles

1. **Think first.** Before any tool call, decide what you need and why.
2. **Read before writing.** Always read files before editing them. Understand the codebase before making changes.
3. **Minimal changes.** Make the smallest change that solves the problem. Don't refactor, don't add features, don't "improve" unrelated code.
4. **Verify your work.** After making changes, run tests or check the result. Don't assume it worked.
5. **Be explicit.** Show what you changed and why. Use file:line references."""


def _tool_rules_section() -> str:
    """Section 3: How to use tools."""
    return """## Tool Rules

- Use dedicated tools over shell commands:
  - `read_file` instead of `cat`
  - `search_content` instead of `grep`/`rg`
  - `search_files` instead of `find`/`ls`
  - `list_files` instead of `ls -la`
  - `git_status`, `git_diff`, `git_log` instead of shell git commands

- Use `execute_command` only when no dedicated tool exists.

- **Parallelize** when possible:
  - Read multiple files in one step
  - Search different patterns simultaneously
  - Run independent checks in parallel

- **Batch reads**: If you need 5 files, read all 5 at once, not one by one."""


def _code_editing_section() -> str:
    """Section 4: How to edit code."""
    return """## Editing Code

- **Edit, don't rewrite.** Use `edit_file` for targeted changes. Only use `write_file` for new files or complete rewrites.

- **Preserve style.** Match the existing code's:
  - Indentation (spaces vs tabs, width)
  - Quote style (single vs double)
  - Naming conventions (snake_case, camelCase)
  - Import style
  - Comment style

- **No unnecessary changes.** Don't:
  - Add type hints unless asked
  - Add docstrings unless asked
  - Add comments unless asked
  - Refactor working code
  - "Improve" unrelated code

- **No premature abstractions.** Three similar lines are better than a bad abstraction.

- **Show diffs.** Before applying edits, show what will change."""


def _task_execution_section() -> str:
    """Section 5: How to approach tasks."""
    return """## Task Execution

**Be autonomous.** Once the user gives a direction, work through it completely. Don't stop at analysis or partial fixes.

**Persist until done.** Keep going until the task is fully resolved:
- Understand the problem
- Explore the codebase
- Make the changes
- Verify they work
- Report what you did

**Plan multi-step tasks.** For complex work:
1. Break it into steps
2. Execute each step
3. Verify after each step
4. Report progress

**Don't guess.** If you're unsure:
- Read more files
- Search for patterns
- Ask the user
- Never make up an answer

**Diagnose before switching.** If something fails:
- Read the error message carefully
- Check what went wrong
- Try a targeted fix
- Only switch tactics if the approach is fundamentally wrong"""


def _safety_section() -> str:
    """Section 6: Safety and permissions."""
    return """## Safety

**Read operations** (auto-allowed):
- Reading files
- Searching code
- Git status, diff, log

**Write operations** (requires confirmation):
- Editing files
- Creating files
- Git commit

**Execute operations** (requires confirmation every time):
- Shell commands
- Running tests
- Build commands

**Destructive operations** (always confirm + warning):
- Delete files
- Force push
- System commands

When you need permission, explain what you want to do and why, then wait for approval."""


def _communication_section() -> str:
    """Section 7: How to communicate."""
    return """## Communication

- **Concise.** Keep responses short. One sentence over three.
- **Direct.** Lead with the answer, skip preamble.
- **Technical.** Use file:line references: `src/main.py:42`
- **No emojis.** Unless the user asks for them.
- **No fluff.** Don't say "I'd be happy to help!" or "Great question!"
- **Show, don't tell.** Show the code, don't describe it verbosely.

### Preambles

Before tool calls, send a brief update (1-2 sentences):
- "Let me read the main.py file to understand the structure."
- "I'll search for all uses of this function."
- "Running the tests to verify the fix."

### Final Answers

After completing work:
- Summarize what you did
- Show key changes with file:line references
- Mention any tests run
- Note any follow-up needed

### Tool Call Format

When using tools, don't add text between parallel calls. Just make the calls."""


def _error_handling_section() -> str:
    """Section 8: How to handle errors."""
    return """## Errors

When a tool fails:
1. Read the error message carefully
2. Identify the root cause
3. Try a targeted fix
4. If the fix doesn't work, try a different approach
5. Never silently ignore errors

Common error patterns:
- **File not found**: Check path, check typos, search for similar files
- **Permission denied**: Ask user for permission
- **Command failed**: Check syntax, check dependencies, read error output
- **Rate limit**: Wait and retry
- **Context too long**: Focus on recent context, summarize if needed"""


def build_static_prompt() -> str:
    """Build the complete static (cacheable) prompt."""
    sections = [
        _identity_section(),
        _core_principles_section(),
        _tool_rules_section(),
        _code_editing_section(),
        _task_execution_section(),
        _safety_section(),
        _communication_section(),
        _error_handling_section(),
    ]
    return "\n\n".join(sections)


# ============================================================================
# DYNAMIC SECTIONS (per-session)
# ============================================================================

def _environment_section(settings: Settings, workspace: Path) -> str:
    """Section 9: Environment info."""
    cwd = workspace.resolve()
    branch = _get_git_branch(workspace)
    file_count = _count_workspace_files(workspace)
    
    lines = [
        "## Environment",
        f"- Working directory: `{cwd}`",
        f"- Platform: {platform.system().lower()}",
        f"- Model: {settings.get_active_model()}",
        f"- Provider: {settings.llm_provider}",
    ]
    if branch:
        lines.append(f"- Git branch: `{branch}`")
    if file_count:
        lines.append(f"- Files in workspace: {file_count}")
    
    return "\n".join(lines)


def _project_context_section(workspace: Path) -> str:
    """Section 10: Project-specific context (AGENTS.md, README.md)."""
    sections = []
    
    # Load AGENTS.md
    agents_md = _load_project_file(workspace, "AGENTS.md")
    if agents_md:
        sections.append(f"## Project Instructions (AGENTS.md)\n\n{agents_md}")
    
    # Load README.md
    readme = _load_project_file(workspace, "README.md")
    if readme:
        # Truncate to first 2000 chars to save context
        if len(readme) > 2000:
            readme = readme[:2000] + "\n\n[truncated...]"
        sections.append(f"## Project Overview (README.md)\n\n{readme}")
    
    if not sections:
        return ""
    
    return "\n\n".join(sections)


def _memory_section(memory_content: str = "") -> str:
    """Section 11: Memory from past conversations."""
    if not memory_content:
        return ""
    return f"## Memory\n\n{memory_content}"


# ============================================================================
# BUILDER
# ============================================================================

# Dynamic boundary marker (like Claude Code)
DYNAMIC_BOUNDARY = "__DYNAMIC_BOUNDARY__"


def build_system_prompt(
    settings: Settings,
    workspace: Path,
    memory_content: str = "",
) -> str:
    """Build the complete system prompt.

    Structure:
    1. Static sections (cacheable, same every session)
    2. DYNAMIC_BOUNDARY marker
    3. Dynamic sections (per-session: environment, project context, memory)
    """
    static = build_static_prompt()
    
    dynamic_sections = []
    
    env = _environment_section(settings, workspace)
    if env:
        dynamic_sections.append(env)
    
    project = _project_context_section(workspace)
    if project:
        dynamic_sections.append(project)
    
    memory = _memory_section(memory_content)
    if memory:
        dynamic_sections.append(memory)
    
    if dynamic_sections:
        dynamic = "\n\n".join(dynamic_sections)
        return f"{static}\n\n{DYNAMIC_BOUNDARY}\n\n{dynamic}"
    
    return static


# ============================================================================
# HELPERS
# ============================================================================

def _get_git_branch(workspace: Path) -> str:
    """Get current git branch name."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _count_workspace_files(workspace: Path) -> int:
    """Count files in workspace (excluding .git, node_modules, etc.)."""
    ignore = {".git", "node_modules", "__pycache__", ".venv", "venv", ".env"}
    count = 0
    try:
        for item in workspace.rglob("*"):
            if item.is_file():
                if not any(part in ignore for part in item.parts):
                    count += 1
                    if count > 10000:
                        return count  # Cap at 10k
    except Exception:
        pass
    return count


def _load_project_file(workspace: Path, filename: str) -> str:
    """Load a project file if it exists."""
    filepath = workspace / filename
    if filepath.exists() and filepath.is_file():
        try:
            return filepath.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""
```

**Key design decisions:**

1. **Layered structure** — Static sections are cacheable (same every session), dynamic sections change per session. This matches Claude Code's architecture.

2. **Functions for each section** — Easy to test, modify, and compose. Each section is independent.

3. **AGENTS.md support** — Like Codex, we load project-specific instructions from AGENTS.md. This gives the agent project-specific knowledge.

4. **Dynamic boundary marker** — Explicit marker separates static from dynamic content for potential prompt caching.

5. **No unnecessary verbosity** — The prompt is comprehensive but not bloated. Each section has a clear purpose.

---

## Module 4: `agent/context.py`

**Purpose:** Manage the conversation state and context window.

```python
"""Context window management for the coding agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from coding_agent.llm.tokens import count_tokens


@dataclass
class ConversationMessage:
    """A single message in the conversation."""

    role: str                          # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to OpenAI format dict."""
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        return msg


class ContextManager:
    """Manages conversation history and context window limits.

    Usage:
        ctx = ContextManager(max_tokens=100_000)
        ctx.system_prompt = build_system_prompt(settings, workspace)
        
        ctx.add_user_message("Fix the bug in main.py")
        
        # In agent loop:
        messages = ctx.build_messages()  # Returns list[dict] for LLM
        
        # After LLM responds:
        ctx.add_assistant_message(response.content, tool_calls=response.tool_calls)
        
        # After tool execution:
        ctx.add_tool_result(tool_call_id, tool_name, result.output)
    """

    def __init__(self, max_tokens: int = 100_000) -> None:
        self.max_tokens = max_tokens
        self.system_prompt: str = ""
        self.project_context: str = ""
        self.messages: list[ConversationMessage] = []
        self._summary: str = ""  # Summarized old messages
    
    def build_messages(self) -> list[dict[str, Any]]:
        """Build the full message list for the LLM.

        Structure:
        1. System prompt (always first)
        2. Project context (from AGENTS.md, README.md)
        3. Conversation history (may be summarized)
        """
        result: list[dict[str, Any]] = []
        
        # System prompt
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        
        # Project context (if separate from system prompt)
        if self.project_context:
            result.append({"role": "system", "content": self.project_context})
        
        # Summarized old messages (if any)
        if self._summary:
            result.append({
                "role": "system",
                "content": f"Summary of previous conversation:\n{self._summary}",
            })
        
        # Current conversation
        for msg in self.messages:
            result.append(msg.to_dict())
        
        return result
    
    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation."""
        self.messages.append(ConversationMessage(role="user", content=content))
    
    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add an assistant message to the conversation."""
        self.messages.append(
            ConversationMessage(
                role="assistant",
                content=content,
                tool_calls=tool_calls,
            )
        )
    
    def add_tool_result(
        self,
        tool_call_id: str,
        name: str,
        result: str,
    ) -> None:
        """Add a tool result to the conversation."""
        self.messages.append(
            ConversationMessage(
                role="tool",
                content=result,
                tool_call_id=tool_call_id,
                name=name,
            )
        )
    
    def estimate_tokens(self) -> int:
        """Estimate total tokens in the conversation."""
        total = 0
        for msg in self.messages:
            total += count_tokens(msg.content)
            if msg.tool_calls:
                import json
                total += count_tokens(json.dumps(msg.tool_calls))
        return total
    
    def needs_summarization(self) -> bool:
        """Check if we're approaching the token limit."""
        return self.estimate_tokens() > self.max_tokens * 0.8
    
    def summarize_old_messages(self, summary: str) -> None:
        """Replace old messages with a summary.

        Call this after generating a summary with the LLM.
        Keeps the last 5 messages.
        """
        if len(self.messages) <= 5:
            return
        
        # Keep last 5 messages
        recent = self.messages[-5:]
        old = self.messages[:-5]
        
        # Build summary of old messages
        old_content = []
        for msg in old:
            if msg.role in ("user", "assistant"):
                old_content.append(f"{msg.role}: {msg.content[:200]}")
        
        self._summary = summary or "\n".join(old_content)
        
        # Replace with recent only
        self.messages = recent
    
    def clear(self) -> None:
        """Clear the conversation (start fresh)."""
        self.messages.clear()
        self._summary = ""
```

**Key behaviors:**

1. **Message list structure** — Always: system prompt → project context → summary (if any) → conversation messages

2. **Token estimation** — Uses the `chars // 4` heuristic from `llm/tokens.py`

3. **Summarization trigger** — When tokens exceed 80% of max, summarize old messages

4. **Summary strategy** — Keep last 5 messages, summarize everything else into a single summary

5. **Tool result formatting** — Tool results are added as `role: "tool"` messages with `tool_call_id` linking them to the original call

---

## Module 5: `agent/loop.py`

**Purpose:** The core agentic loop.

```python
"""Core agent loop — observe, think, act, repeat."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from coding_agent.agent.context import ContextManager
from coding_agent.agent.events import AgentEvent, EventType
from coding_agent.agent.permissions import PermissionManager, get_permission_level
from coding_agent.agent.system_prompt import build_system_prompt
from coding_agent.llm.client import LLMClient
from coding_agent.llm.streaming import StreamEventType
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool_registry
from coding_agent.logging import logger


class AgentLoop:
    """Core agentic loop — observe, think, act, repeat.

    Usage:
        llm = LLMClient(model="gemini-2.5-flash", api_key="...")
        permissions = PermissionManager(level=Permission.WRITE)
        context = ContextManager(max_tokens=100_000)
        
        agent = AgentLoop(
            llm_client=llm,
            permission_manager=permissions,
            context_manager=context,
            workspace=Path("."),
            max_iterations=20,
        )
        
        async for event in agent.process_input("Fix the bug in main.py"):
            if event.type == EventType.TEXT:
                print(event.data, end="", flush=True)
            elif event.type == EventType.TOOL_START:
                print(f"\n[Tool: {event.data['name']}]")
            elif event.type == EventType.TOOL_RESULT:
                print(f"\n[Result: {event.data['result'].success}]")
            elif event.type == EventType.DONE:
                print("\n[Done]")
    """

    def __init__(
        self,
        llm_client: LLMClient,
        permission_manager: PermissionManager,
        context_manager: ContextManager,
        workspace: Any,  # Path
        max_iterations: int = 20,
    ) -> None:
        self.llm_client = llm_client
        self.permissions = permission_manager
        self.context = context_manager
        self.workspace = workspace
        self.max_iterations = max_iterations
        
        # Build and inject system prompt
        self.context.system_prompt = build_system_prompt(
            settings=None,  # Will be passed from config
            workspace=workspace,
        )
    
    async def process_input(
        self,
        user_input: str,
    ) -> AsyncIterator[AgentEvent]:
        """Process user input and yield events for the TUI.

        This is the main entry point. It:
        1. Adds user message to context
        2. Runs the agentic loop
        3. Yields events as they happen
        """
        # Add user message
        self.context.add_user_message(user_input)
        
        # Agentic loop
        for iteration in range(self.max_iterations):
            logger.info("agent_iteration", iteration=iteration + 1)
            
            # Build messages for LLM
            messages = self.context.build_messages()
            tools = tool_registry.get_schemas()
            
            # Stream LLM response
            tool_calls: list[dict[str, Any]] = []
            text_buffer: list[str] = []
            
            async for event in self.llm_client.stream(messages, tools=tools):
                if event.type == StreamEventType.TEXT:
                    text_buffer.append(event.data)
                    yield AgentEvent(type=EventType.TEXT, data=event.data)
                
                elif event.type == StreamEventType.TOOL_CALL:
                    tool_calls.append(event.data)
                
                elif event.type == StreamEventType.USAGE:
                    yield AgentEvent(type=EventType.USAGE, data=event.data)
                
                elif event.type == StreamEventType.DONE:
                    break
            
            # Combine text for context
            full_text = "".join(text_buffer)
            
            # Add assistant message to context
            if full_text or tool_calls:
                self.context.add_assistant_message(
                    content=full_text,
                    tool_calls=tool_calls if tool_calls else None,
                )
            
            # No tool calls → done
            if not tool_calls:
                yield AgentEvent(type=EventType.DONE)
                return
            
            # Execute each tool call
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                tool_args_raw = tc["function"]["arguments"]
                
                # Parse arguments
                try:
                    tool_args = json.loads(tool_args_raw)
                except json.JSONDecodeError:
                    tool_args = {}
                
                # Permission check
                tool = tool_registry.get(tool_name)
                permission_level = tool.permission_level
                
                if not self.permissions.check(tool_name, permission_level):
                    # Needs user confirmation
                    yield AgentEvent(
                        type=EventType.PERMISSION_REQUEST,
                        data={
                            "tool_name": tool_name,
                            "args": tool_args,
                            "permission_level": permission_level,
                        },
                    )
                    # Note: In production, this would await a queue/callback
                    # For now, we'll assume approval for the first version
                    # TODO: Wire up actual permission flow
                    self.permissions.approve_tool(tool_name)
                
                # Execute tool
                yield AgentEvent(
                    type=EventType.TOOL_START,
                    data={"name": tool_name, "args": tool_args},
                )
                
                result = await tool_registry.execute_from_llm(tc)
                
                yield AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={"name": tool_name, "result": result},
                )
                
                # Add result to conversation
                self.context.add_tool_result(
                    tool_call_id=tc.get("id", ""),
                    name=tool_name,
                    result=result.output,
                )
            
            # Check if we should summarize
            if self.context.needs_summarization():
                # TODO: Generate summary with LLM
                pass
        
        # Max iterations reached
        yield AgentEvent(type=EventType.MAX_ITERATIONS)
    
    def reset(self) -> None:
        """Reset the agent loop (clear conversation)."""
        self.context.clear()
        self.permissions.reset()
```

**Key behaviors:**

1. **Streaming response** — Tokens are yielded in real-time via `EventType.TEXT`

2. **Tool call accumulation** — Tool calls are accumulated from the stream and executed after the stream finishes

3. **Permission gating** — Each tool call goes through permission check before execution

4. **Context management** — All messages (user, assistant, tool results) are added to context

5. **Iteration limit** — Stops after `max_iterations` (default 20) to prevent infinite loops

6. **Error recovery** — Tool errors are fed back to LLM as results, it can retry

7. **Summarization trigger** — Checks if context needs summarization after each iteration

---

## Implementation Order

1. **`agent/events.py`** — Simple dataclasses, no dependencies (5 min)
2. **`agent/permissions.py`** — Simple enum + logic, no dependencies (15 min)
3. **`agent/system_prompt.py` — Template functions, depends on config (30 min)
4. **`agent/context.py`** — Conversation management, depends on tokens.py (20 min)
5. **`agent/loop.py`** — Core loop, depends on all above + LLM + tools (45 min)
6. **Tests** — After each module (60 min total)

**Total estimated time: ~3 hours**

---

## Testing Strategy

### Test Files

| Test File | What It Tests |
|-----------|--------------|
| `test_events.py` | Event types, dataclass creation |
| `test_permissions.py` | Permission levels, trust modes, approval flow |
| `test_system_prompt.py` | Prompt building, section functions, dynamic injection |
| `test_context.py` | Message building, token estimation, summarization trigger |
| `test_agent_loop.py` | Full loop with mocked LLM (tool calls → execution → result feeding) |

### Test Patterns

Follow existing patterns from `test_tools/test_registry.py` and `test_llm.py`:

```python
# Pattern 1: Async test with mocked LLM
async def test_agent_loop_tool_call():
    # Mock LLM client
    mock_llm = AsyncMock(spec=LLMClient)
    mock_llm.stream.return_value = async_iter([
        StreamEvent(type=StreamEventType.TEXT, data="I'll read the file."),
        StreamEvent(type=StreamEventType.TOOL_CALL, data={
            "id": "call_0",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path": "main.py"}'},
        }),
        StreamEvent(type=StreamEventType.DONE),
    ])
    
    # Create agent
    agent = AgentLoop(
        llm_client=mock_llm,
        permission_manager=PermissionManager(level=Permission.READ),
        context_manager=ContextManager(),
        workspace=Path("."),
    )
    
    # Process input
    events = []
    async for event in agent.process_input("Read main.py"):
        events.append(event)
    
    # Verify
    assert events[0].type == EventType.TEXT
    assert events[1].type == EventType.TOOL_START
    assert events[2].type == EventType.TOOL_RESULT
    assert events[-1].type == EventType.DONE
```

```python
# Pattern 2: Permission test
def test_permission_manager():
    pm = PermissionManager(level=Permission.WRITE)
    
    # Read is always allowed
    assert pm.check("read_file", "read") == True
    
    # Write needs approval
    assert pm.check("write_file", "write") == False
    pm.approve_tool("write_file")
    assert pm.check("write_file", "write") == True  # Now auto-allowed
    
    # Execute always asks
    assert pm.check("execute_command", "execute") == False
```

```python
# Pattern 3: Context test
def test_context_manager():
    ctx = ContextManager(max_tokens=1000)
    ctx.system_prompt = "You are a coding agent."
    
    ctx.add_user_message("Hello")
    ctx.add_assistant_message("Hi there!")
    ctx.add_tool_result("call_0", "read_file", "file contents...")
    
    messages = ctx.build_messages()
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    assert messages[3]["role"] == "tool"
```

---

## Success Criteria

- [ ] Agent processes user input and returns response
- [ ] Agent calls tools when LLM requests them
- [ ] Agent feeds tool results back to LLM
- [ ] Agent stops after max iterations
- [ ] Permission system blocks unauthorized operations
- [ ] Context window manages token limits
- [ ] Streaming works (text tokens yielded in real-time)
- [ ] All 286+ existing tests still pass
- [ ] New tests pass for agent components
- [ ] Linting passes (ruff check, ruff format)
- [ ] Type checking passes (pyright)

---

## Known Issues / TODOs

1. **Permission flow not wired** — The agent loop currently auto-approves after first request. Need to wire up actual user confirmation (queue/callback pattern) in Week 8 with TUI.

2. **Summarization not implemented** — The `summarize_old_messages()` method exists but isn't called with an actual LLM-generated summary. Need to add a `_summarize_with_llm()` method.

3. **Memory system** — Currently empty. Can add conversation persistence in a future phase.

4. **Parallel tool execution** — The current implementation executes tools sequentially. Can add parallel execution in a future phase.

5. **Project context loading** — `_project_context_section()` reads AGENTS.md and README.md. Need to verify this works correctly with the workspace path.

---

## Files to Create

```
src/coding_agent/agent/
├── __init__.py          (already exists, empty)
├── events.py            (NEW - ~60 lines)
├── permissions.py       (NEW - ~120 lines)
├── system_prompt.py     (NEW - ~250 lines)
├── context.py           (NEW - ~180 lines)
└── loop.py              (NEW - ~250 lines)

tests/
├── test_agent/
│   ├── __init__.py      (NEW)
│   ├── test_events.py   (NEW - ~30 lines)
│   ├── test_permissions.py (NEW - ~80 lines)
│   ├── test_system_prompt.py (NEW - ~100 lines)
│   ├── test_context.py  (NEW - ~80 lines)
│   └── test_agent_loop.py (NEW - ~150 lines)
```

---

## Integration with Week 8 (TUI)

The agent loop yields `AgentEvent` objects. The TUI (Week 8) will consume these events:

```python
# Week 8: TUI integration (pseudocode)
class AgentApp(App):
    async def on_input_submitted(self, event):
        agent = self.get_agent()
        async for evt in agent.process_input(event.value):
            if evt.type == EventType.TEXT:
                self.write(evt.data)
            elif evt.type == EventType.TOOL_START:
                self.write(f"\n🔧 {evt.data['name']}...")
            elif evt.type == EventType.PERMISSION_REQUEST:
                approved = await self.ask_permission(evt.data)
                if not approved:
                    # Feed denial back to agent
                    pass
            elif evt.type == EventType.DONE:
                self.write("\n✅ Done!")
```

---

## References

| Document | Purpose |
|----------|---------|
| [architecture.md](architecture.md) | System architecture (pre-phase-7) |
| [features.md](features.md) | Feature specifications |
| [techstack.md](techstack.md) | Tech stack choices |
| [phase-checklist.md](phase-checklist.md) | Week-by-week build plan |
| Claude Code source | System prompt structure, permission model |
| Codex source | Agent loop, tool usage, AGENTS.md |
