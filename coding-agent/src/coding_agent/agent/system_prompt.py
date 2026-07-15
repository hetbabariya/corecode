"""System prompt builder for the coding agent.

The prompt is assembled in two layers:

1. **Static** (cacheable, identical across sessions) — behavioral rules,
   tool usage policy, safety guardrails, tone.
2. **Dynamic** (per-session) — environment info, project context loaded
   from AGENTS.md / README.md, memory.

The ``DYNAMIC_BOUNDARY`` marker separates the two halves so that a future
prompt-caching layer can treat them differently.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from coding_agent.logging import logger

# Marker that separates static (cacheable) from dynamic (per-session) content.
DYNAMIC_BOUNDARY = "__DYNAMIC_BOUNDARY__"

# Module-level cache for the static prompt (rebuilt only when model changes).
_STATIC_CACHE: str | None = None
_STATIC_CACHE_MODEL: str | None = None


# ============================================================================
# Static sections — identical across all sessions
# ============================================================================


def _identity_section() -> str:
    return """\
You are a coding agent — an AI-powered software engineering assistant that reads, edits, and executes code in the user's workspace.

You are precise, helpful, and autonomous. You figure out what files to read, what code to change, and what commands to run — then do it.

You have access to tools for:
- Reading and writing files
- Searching codebases (content and filenames)
- Running shell commands (in a sandboxed environment)
- Git operations (status, diff, log, commit)"""


def _core_principles_section() -> str:
    return """\
## Core Principles

1. **Think first.** Before any tool call, decide what you need and why.
2. **Read before writing.** Always read files before editing them. Understand the codebase before making changes.
3. **Minimal changes.** Make the smallest change that solves the problem. Don't refactor, don't add features, don't "improve" unrelated code.
4. **Verify your work.** After making changes, run tests or check the result. Don't assume it worked.
5. **Be explicit.** Show what you changed and why. Use file:line references."""


def _tool_rules_section() -> str:
    return """\
## Tool Rules

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
    return """\
## Editing Code

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
    return """\
## Task Execution

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


def _get_model_tier(model: str) -> str:
    """Determine model capability tier from model name.

    Returns one of: "fast", "balanced", "advanced".
    """
    model_lower = model.lower()
    # Fast tier — smaller, cheaper models
    if any(k in model_lower for k in ("flash", "mini", "lite", "haiku", "small")):
        return "fast"
    # Advanced tier — largest, most capable models
    if any(k in model_lower for k in ("ultra", "pro", "o1", "o3", "opus", "sonnet")):
        return "advanced"
    # Default
    return "balanced"


def _adaptive_notes_section(model_tier: str) -> str:
    """Return model-tier-specific guidance notes."""
    if model_tier == "fast":
        return """\
## Model Notes (Fast Tier)

You are a fast, efficient model. Focus on:
- Concise responses — get to the point
- Single-pass edits when possible
- Skip verbose explanations unless asked
- Prioritize speed over thoroughness"""
    elif model_tier == "advanced":
        return """\
## Model Notes (Advanced Tier)

You are a highly capable model. Leverage your strengths:
- Deep analysis before acting
- Consider edge cases and side effects
- Suggest architectural improvements when relevant
- Be thorough but still prefer minimal changes"""
    return ""  # balanced tier uses default behavior


def _safety_section() -> str:
    return """\
## Safety

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
    return """\
## Communication

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
    return """\
## Errors

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


def _planning_section() -> str:
    return """\
## Planning

For multi-step tasks, use the planning tools:

1. **Create a plan first.** Call `create_plan` with a goal and ordered steps.
2. **Track progress.** Call `update_plan` to mark steps as in_progress, done, or failed.
3. **Replan on failure.** If a step fails, assess whether to retry or create a new plan.

A good plan has:
- Clear, actionable steps (not vague)
- 3-10 steps (fewer for simple tasks, more for complex ones)
- Each step produces a verifiable result

Don't over-plan. For simple tasks (read a file, make one edit), skip planning and just act."""


def build_static_prompt(model: str = "") -> str:
    """Build the complete static (cacheable) prompt.

    Parameters
    ----------
    model:
        Model name for adaptive tier detection. Empty uses "balanced".
    """
    sections = [
        _identity_section(),
        _core_principles_section(),
        _tool_rules_section(),
        _code_editing_section(),
        _task_execution_section(),
        _safety_section(),
        _communication_section(),
        _error_handling_section(),
        _planning_section(),
    ]

    # Adaptive notes based on model tier
    if model:
        tier = _get_model_tier(model)
        notes = _adaptive_notes_section(tier)
        if notes:
            sections.append(notes)

    return "\n\n".join(sections)


def get_static_prompt(model: str = "") -> str:
    """Return cached static prompt, rebuilding only if model changes.

    This avoids rebuilding the ~1500-token static section every session.
    """
    global _STATIC_CACHE, _STATIC_CACHE_MODEL
    if _STATIC_CACHE is None or _STATIC_CACHE_MODEL != model:
        _STATIC_CACHE = build_static_prompt(model=model)
        _STATIC_CACHE_MODEL = model
        logger.debug("static_prompt_cache_miss", model=model)
    else:
        logger.debug("static_prompt_cache_hit", model=model)
    return _STATIC_CACHE


# ============================================================================
# Dynamic sections — per-session
# ============================================================================


def _environment_section(
    model: str,
    provider: str,
    workspace: Path,
) -> str:
    """Section 9: environment info."""
    cwd = workspace.resolve()
    branch = _get_git_branch(workspace)
    file_count = _count_workspace_files(workspace)

    lines = [
        "## Environment",
        f"- Working directory: `{cwd}`",
        f"- Platform: {platform.system().lower()}",
        f"- Model: {model}",
        f"- Provider: {provider}",
    ]
    if branch:
        lines.append(f"- Git branch: `{branch}`")
    if file_count:
        lines.append(f"- Files in workspace: {file_count}")

    return "\n".join(lines)


def _project_context_section(workspace: Path) -> str:
    """Section 10: project-specific context (AGENTS.md, README.md)."""
    parts: list[str] = []

    agents_md = _load_project_file(workspace, "AGENTS.md")
    if agents_md:
        parts.append(f"## Project Instructions (AGENTS.md)\n\n{agents_md}")

    readme = _load_project_file(workspace, "README.md")
    if readme:
        if len(readme) > 2000:
            readme = readme[:2000] + "\n\n[truncated...]"
        parts.append(f"## Project Overview (README.md)\n\n{readme}")

    return "\n\n".join(parts)


def _memory_section(memory_content: str = "") -> str:
    """Section 11: memory from past conversations."""
    if not memory_content:
        return ""
    return f"## Memory\n\n{memory_content}"


def _plan_section(plan_prompt: str = "") -> str:
    """Dynamic section showing the current plan state."""
    if not plan_prompt:
        return ""
    return plan_prompt


def _workspace_index_section(index_summary: str = "") -> str:
    """Dynamic section showing the workspace file tree."""
    if not index_summary:
        return ""
    return f"## Workspace Files\n\n{index_summary}"


# ============================================================================
# Public builder
# ============================================================================


def build_system_prompt(
    model: str = "",
    provider: str = "",
    workspace: Path | None = None,
    memory_content: str = "",
    plan_prompt: str = "",
    workspace_index_summary: str = "",
) -> str:
    """Build the complete system prompt.

    Structure::

        [static — cacheable]
          identity → principles → tools → editing → execution
          → safety → communication → errors → planning

        [dynamic — per-session]
          environment → project context → memory → plan state → workspace files

    Parameters
    ----------
    model:
        Active LLM model name (e.g. ``"gemini-2.5-flash"``).
    provider:
        Active LLM provider (e.g. ``"gemini"``).
    workspace:
        Project root directory. Used to load AGENTS.md, README.md, git info.
    memory_content:
        Optional memory string from past conversations.
    plan_prompt:
        Optional serialized plan state from PlanManager.to_prompt().
    workspace_index_summary:
        Optional workspace file tree from WorkspaceIndex.to_summary().
    """
    static = get_static_prompt(model=model)

    dynamic_parts: list[str] = []

    if workspace is not None:
        env = _environment_section(model, provider, workspace)
        if env:
            dynamic_parts.append(env)

        project = _project_context_section(workspace)
        if project:
            dynamic_parts.append(project)

    if memory_content:
        mem = _memory_section(memory_content)
        if mem:
            dynamic_parts.append(mem)

    if plan_prompt:
        plan = _plan_section(plan_prompt)
        if plan:
            dynamic_parts.append(plan)

    if workspace_index_summary:
        idx = _workspace_index_section(workspace_index_summary)
        if idx:
            dynamic_parts.append(idx)

    if dynamic_parts:
        dynamic = "\n\n".join(dynamic_parts)
        result = f"{static}\n\n{DYNAMIC_BOUNDARY}\n\n{dynamic}"
    else:
        result = static

    logger.debug(
        "system_prompt_built",
        total_length=len(result),
        static_length=len(static),
        dynamic_sections=len(dynamic_parts),
        has_plan=bool(plan_prompt),
        has_memory=bool(memory_content),
        has_workspace_index=bool(workspace_index_summary),
    )
    return result


# ============================================================================
# Helpers
# ============================================================================


def _get_git_branch(workspace: Path) -> str:
    """Return the current git branch name, or ``""`` on failure."""
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
    """Count files in workspace, excluding common ignore dirs."""
    ignore = {".git", "node_modules", "__pycache__", ".venv", "venv", ".env"}
    count = 0
    try:
        for item in workspace.rglob("*"):
            if item.is_file():
                if not any(part in ignore for part in item.parts):
                    count += 1
                    if count > 10000:
                        return count
    except Exception:
        pass
    return count


def _load_project_file(workspace: Path, filename: str) -> str:
    """Load a project file if it exists, else return ``""``."""
    filepath = workspace / filename
    if filepath.exists() and filepath.is_file():
        try:
            return filepath.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""
