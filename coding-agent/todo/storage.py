"""JSON-based persistence for todo items."""

from __future__ import annotations

import json
import os
from pathlib import Path

from todo.models import TodoItem

DEFAULT_STORE = Path("todos.json")


def _next_id(todos: list[TodoItem]) -> int:
    if not todos:
        return 1
    return max(t.id for t in todos) + 1


def load_todos(path: Path = DEFAULT_STORE) -> list[TodoItem]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return [TodoItem.from_dict(item) for item in data]


def save_todos(todos: list[TodoItem], path: Path = DEFAULT_STORE) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([t.to_dict() for t in todos], fh, indent=2)


def next_id(todos: list[TodoItem]) -> int:
    return _next_id(todos)
