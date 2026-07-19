"""Todo tools — task tracking visible in the system prompt.

The LLM can create, update, list, and delete todos to track multi-step work.
The current state is injected into the system prompt on every turn.
"""

from __future__ import annotations

from typing import Any

from coding_agent.logging import logger
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import tool

VALID_STATUSES = {"pending", "in_progress", "completed", "blocked", "cancelled"}
VALID_PRIORITIES = {"low", "medium", "high"}

_todos: list[dict[str, Any]] = []
_next_id: int = 0


def get_todos_summary() -> str:
    """Return a summary of current todos for prompt injection."""
    if not _todos:
        return ""
    lines = ["Current todos:"]
    for i, t in enumerate(_todos):
        priority_tag = f" [{t['priority']}]" if t["priority"] != "medium" else ""
        lines.append(f"  {i + 1}.{priority_tag} {t['description']} — {t['status']}")
    return "\n".join(lines)


def reset_todos() -> None:
    """Clear all todos (used for session reset)."""
    global _todos, _next_id
    _todos.clear()
    _next_id = 0


def _validate_index(index: int) -> int:
    """Validate 1-based index, return 0-based. Returns -1 if invalid."""
    if not _todos:
        return -1
    zb = index - 1
    if zb < 0 or zb >= len(_todos):
        return -1
    return zb


@tool(
    name="add_todo",
    description="Add a task to your todo list. Use this to track multi-step work. The current todos are visible in every system prompt.",
    permission="read",
)
async def add_todo(description: str, priority: str = "medium") -> ToolResult:
    """Add a new todo item.

    Parameters
    ----------
    description:
        What needs to be done.
    priority:
        Priority level: low, medium, or high (default medium).
    """
    global _next_id

    if not description.strip():
        return ToolResult(success=False, error="Description cannot be empty.")

    priority = priority.lower()
    if priority not in VALID_PRIORITIES:
        return ToolResult(
            success=False,
            error=f"Invalid priority '{priority}'. Use: low, medium, or high.",
        )

    todo: dict[str, Any] = {
        "id": _next_id,
        "description": description.strip(),
        "priority": priority,
        "status": "pending",
    }
    _next_id += 1
    _todos.append(todo)

    logger.info("todo_added", id=todo["id"], description=description.strip()[:80], priority=priority)
    return ToolResult(
        success=True,
        output=f"Todo #{len(_todos)} added: {description.strip()} [{priority}]",
    )


@tool(
    name="update_todo",
    description="Update a todo's status or priority by number (use list_todos to see numbers).",
    permission="read",
)
async def update_todo(
    index: int,
    status: str = "",
    priority: str = "",
) -> ToolResult:
    """Update a todo item.

    Parameters
    ----------
    index:
        1-based index of the todo to update (use list_todos to see numbers).
    status:
        New status: pending, in_progress, completed, blocked, or cancelled.
    priority:
        New priority: low, medium, or high.
    """
    zb = _validate_index(index)
    if zb == -1:
        return ToolResult(
            success=False,
            error=f"Invalid index {index}. Use list_todos to see valid numbers.",
        )

    todo = _todos[zb]
    changes: list[str] = []

    if status:
        status = status.lower()
        if status not in VALID_STATUSES:
            return ToolResult(
                success=False,
                error=f"Invalid status '{status}'. Use: {', '.join(sorted(VALID_STATUSES))}.",
            )
        todo["status"] = status
        changes.append(f"status={status}")

    if priority:
        priority = priority.lower()
        if priority not in VALID_PRIORITIES:
            return ToolResult(
                success=False,
                error=f"Invalid priority '{priority}'. Use: low, medium, or high.",
            )
        todo["priority"] = priority
        changes.append(f"priority={priority}")

    if not changes:
        return ToolResult(success=False, error="Nothing to update. Provide status or priority.")

    logger.info("todo_updated", index=index, changes=changes)
    return ToolResult(success=True, output=f"Todo #{index} updated: {', '.join(changes)}")


@tool(
    name="list_todos",
    description="List all todos, optionally filtered by status. Shows the number you use to update or delete.",
    permission="read",
)
async def list_todos(status: str = "") -> ToolResult:
    """List todos.

    Parameters
    ----------
    status:
        Optional filter: pending, in_progress, completed, blocked, or cancelled.
        Empty string returns all todos.
    """
    if not _todos:
        return ToolResult(success=True, output="No todos yet. Use add_todo to create one.")

    if status:
        status = status.lower()
        if status not in VALID_STATUSES:
            return ToolResult(
                success=False,
                error=f"Invalid status '{status}'. Use: {', '.join(sorted(VALID_STATUSES))}.",
            )

    items = []
    for idx, t in enumerate(_todos):
        if status and t["status"] != status:
            continue
        priority_tag = f" [{t['priority']}]" if t["priority"] != "medium" else ""
        items.append(f"  {idx + 1}.{priority_tag} {t['description']} — {t['status']}")

    if not items:
        return ToolResult(success=True, output=f"No todos with status '{status}'.")

    header = f"Todos ({len(_todos)}):" if not status else f"Todos ({len(items)} filtered):"
    return ToolResult(success=True, output=header + "\n" + "\n".join(items))


@tool(
    name="delete_todo",
    description="Delete a todo by number (use list_todos to see numbers).",
    permission="read",
)
async def delete_todo(index: int) -> ToolResult:
    """Delete a todo.

    Parameters
    ----------
    index:
        1-based index of the todo to delete.
    """
    zb = _validate_index(index)
    if zb == -1:
        return ToolResult(
            success=False,
            error=f"Invalid index {index}. Use list_todos to see valid numbers.",
        )

    removed = _todos.pop(zb)
    logger.info("todo_deleted", index=index, description=removed["description"][:80])
    return ToolResult(success=True, output=f"Todo #{index} deleted: {removed['description']}")
