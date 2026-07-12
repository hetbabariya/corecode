"""Infer JSON Schema from Python type hints for tool parameters."""

from __future__ import annotations

import inspect
import typing
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin


def infer_schema(func: Any) -> dict[str, Any]:
    """Build a JSON Schema ``parameters`` dict from a function's type hints.

    Handles: str, int, float, bool, list[T], dict[K, V], Optional[X],
    Path, Literal, Enum subclasses, and Pydantic BaseModel subclasses.
    """
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = {}

    sig = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.POSITIONAL_ONLY,
        ):
            continue

        annotation = hints.get(param_name, str)
        is_optional, inner = _unwrap_optional(annotation)

        schema = _type_to_schema(inner)
        if schema is not None:
            properties[param_name] = schema

        if param.default is inspect.Parameter.empty and not is_optional:
            required.append(param_name)

    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        result["required"] = required

    return result


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _unwrap_optional(annotation: Any) -> tuple[bool, Any]:
    """Return ``(is_optional, inner_type)`` for Optional/Union[X, None]."""
    origin = get_origin(annotation)

    # ``X | None`` syntax (Python 3.10+)
    if origin is getattr(typing, "UnionType", None):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) < len(get_args(annotation)):
            return True, args[0] if len(args) == 1 else typing.Union[tuple(args)]  # type: ignore[return-value]  # noqa: UP007
        return False, annotation

    # ``Optional[X]`` / ``Union[X, None]``
    if origin is typing.Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) < len(get_args(annotation)):
            return True, args[0] if len(args) == 1 else typing.Union[tuple(args)]  # type: ignore[return-value]  # noqa: UP007
        return False, annotation

    return False, annotation


def _type_to_schema(annotation: Any) -> dict[str, Any] | None:
    """Convert a single type annotation to a JSON Schema fragment."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}

    # --- Primitives ---
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}

    # --- Path → string with format hint ---
    if annotation is Path:
        return {"type": "string", "format": "path"}

    # --- Literal ---
    if hasattr(typing, "Literal") and get_origin(annotation) is typing.Literal:
        values = list(get_args(annotation))
        if values and isinstance(values[0], str):
            return {"type": "string", "enum": values}
        return {"type": "string", "enum": [str(v) for v in values]}

    # --- Enum subclass ---
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        values = [m.value for m in annotation]
        if all(isinstance(v, str) for v in values):
            return {"type": "string", "enum": values}
        return {"type": "string", "enum": [str(v) for v in values]}

    # --- Pydantic BaseModel ---
    if isinstance(annotation, type) and _is_pydantic_model(annotation):
        return annotation.model_json_schema()  # type: ignore[union-attr]

    # --- list[T] / Sequence[T] ---
    origin = get_origin(annotation)
    if (
        origin is list
        or annotation is list
        or (hasattr(typing, "Sequence") and origin is typing.Sequence)
    ):
        args = get_args(annotation)
        if args and args[0] is not Any:
            item_schema = _type_to_schema(args[0])
            if item_schema:
                return {"type": "array", "items": item_schema}
        return {"type": "array"}

    # --- dict[K, V] / Mapping[K, V] / dict ---
    if (
        origin is dict
        or annotation is dict
        or (hasattr(typing, "Mapping") and origin is typing.Mapping)
    ):
        args = get_args(annotation)
        if len(args) == 2 and args[1] is not Any:
            val_schema = _type_to_schema(args[1])
            if val_schema:
                return {"type": "object", "additionalProperties": val_schema}
        return {"type": "object"}

    # --- Fallback ---
    return {"type": "string"}


def _is_pydantic_model(cls: type) -> bool:
    """Check if *cls* is a Pydantic BaseModel subclass without importing pydantic at module level."""
    try:
        from pydantic import BaseModel

        return issubclass(cls, BaseModel)
    except ImportError:
        return False
