"""Command implementations for add, list, and delete."""

from __future__ import annotations

import sys
from pathlib import Path

from todo.models import TodoItem
from todo.storage import load_todos, next_id, save_todos, DEFAULT_STORE


def add_todo(title: str, *, path: Path = DEFAULT_STORE) -> None:
    todos = load_todos(path)
    item = TodoItem(id=next_id(todos), title=title)
    todos.append(item)
    save_todos(todos, path)
    print(f"Added todo #{item.id}: {item.title}")


def list_todos(*, path: Path = DEFAULT_STORE) -> None:
    todos = load_todos(path)
    if not todos:
        print("No todos yet.")
        return
    for item in todos:
        mark = "x" if item.done else " "
        print(f"  [{mark}] #{item.id}  {item.title}")


def delete_todo(todo_id: int, *, path: Path = DEFAULT_STORE) -> None:
    todos = load_todos(path)
    for i, item in enumerate(todos):
        if item.id == todo_id:
            removed = todos.pop(i)
            save_todos(todos, path)
            print(f"Deleted todo #{removed.id}: {removed.title}")
            return
    print(f"Todo #{todo_id} not found.", file=sys.stderr)
    sys.exit(1)
