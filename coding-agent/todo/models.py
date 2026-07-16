"""Data models for the todo CLI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TodoItem:
    id: int
    title: str
    done: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodoItem:
        return cls(
            id=data["id"],
            title=data["title"],
            done=data.get("done", False),
            created_at=data.get("created_at", ""),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> TodoItem:
        return cls.from_dict(json.loads(raw))
