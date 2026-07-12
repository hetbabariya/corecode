"""Tests for JSON Schema inference from Python type hints."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from coding_agent.tools.schema import infer_schema

# ------------------------------------------------------------------
# Helpers — sample functions for each inference case
# ------------------------------------------------------------------


def _fn_str(path: str) -> None: ...


def _fn_int(count: int) -> None: ...


def _fn_float(ratio: float) -> None: ...


def _fn_bool(flag: bool) -> None: ...


def _fn_list_str(items: list[str]) -> None: ...


def _fn_list_int(items: list[int]) -> None: ...


def _fn_dict_any(data: dict) -> None: ...


def _fn_dict_str_str(data: dict[str, str]) -> None: ...


def _fn_optional_str(label: str | None = None) -> None: ...


def _fn_path(path: Path) -> None: ...


def _fn_literal(value: Literal["read", "write", "execute"]) -> None: ...


class _Color(StrEnum):
    RED = "red"
    BLUE = "blue"


def _fn_enum(color: _Color) -> None: ...


class _SearchArgs(BaseModel):
    pattern: str = Field(description="Regex pattern")
    file_type: str | None = Field(default=None, description="File type filter")
    max_results: int = Field(default=10, description="Max results")


def _fn_pydantic(args: _SearchArgs) -> None: ...


def _fn_no_hints(data) -> None: ...  # type: ignore[no-untyped-def]


def _fn_multi(a: str, b: int, flag: bool = False) -> None: ...


def _fn_kwargs(**kwargs: Any) -> None: ...


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestInferSchemaPrimitives:
    def test_str(self) -> None:
        schema = infer_schema(_fn_str)
        assert schema["properties"]["path"] == {"type": "string"}
        assert schema["required"] == ["path"]

    def test_int(self) -> None:
        schema = infer_schema(_fn_int)
        assert schema["properties"]["count"] == {"type": "integer"}
        assert schema["required"] == ["count"]

    def test_float(self) -> None:
        schema = infer_schema(_fn_float)
        assert schema["properties"]["ratio"] == {"type": "number"}

    def test_bool(self) -> None:
        schema = infer_schema(_fn_bool)
        assert schema["properties"]["flag"] == {"type": "boolean"}


class TestInferSchemaCollections:
    def test_list_of_str(self) -> None:
        schema = infer_schema(_fn_list_str)
        prop = schema["properties"]["items"]
        assert prop == {"type": "array", "items": {"type": "string"}}

    def test_list_of_int(self) -> None:
        schema = infer_schema(_fn_list_int)
        prop = schema["properties"]["items"]
        assert prop == {"type": "array", "items": {"type": "integer"}}

    def test_dict_any(self) -> None:
        schema = infer_schema(_fn_dict_any)
        assert schema["properties"]["data"] == {"type": "object"}

    def test_dict_str_str(self) -> None:
        schema = infer_schema(_fn_dict_str_str)
        prop = schema["properties"]["data"]
        assert prop == {
            "type": "object",
            "additionalProperties": {"type": "string"},
        }


class TestInferSchemaSpecial:
    def test_optional_str(self) -> None:
        schema = infer_schema(_fn_optional_str)
        assert schema["properties"]["label"] == {"type": "string"}
        # Optional params are NOT in required
        assert "label" not in schema.get("required", [])

    def test_path(self) -> None:
        schema = infer_schema(_fn_path)
        assert schema["properties"]["path"] == {
            "type": "string",
            "format": "path",
        }

    def test_literal(self) -> None:
        schema = infer_schema(_fn_literal)
        prop = schema["properties"]["value"]
        assert prop["type"] == "string"
        assert set(prop["enum"]) == {"read", "write", "execute"}

    def test_enum(self) -> None:
        schema = infer_schema(_fn_enum)
        prop = schema["properties"]["color"]
        assert prop["type"] == "string"
        assert set(prop["enum"]) == {"red", "blue"}

    def test_pydantic_model(self) -> None:
        schema = infer_schema(_fn_pydantic)
        prop = schema["properties"]["args"]
        # Pydantic model_json_schema returns a full schema
        assert prop["type"] == "object"
        assert "pattern" in prop.get("properties", {})

    def test_no_hints_defaults_to_string(self) -> None:
        schema = infer_schema(_fn_no_hints)
        assert schema["properties"]["data"] == {"type": "string"}


class TestInferSchemaRequiredVsOptional:
    def test_required_params(self) -> None:
        schema = infer_schema(_fn_multi)
        assert "a" in schema["required"]
        assert "b" in schema["required"]

    def test_optional_params_not_required(self) -> None:
        schema = infer_schema(_fn_multi)
        assert "flag" not in schema.get("required", [])

    def test_all_optional(self) -> None:
        schema = infer_schema(_fn_optional_str)
        assert "required" not in schema or len(schema.get("required", [])) == 0

    def test_kwargs_no_additional_properties(self) -> None:
        schema = infer_schema(_fn_kwargs)
        assert schema.get("additionalProperties") is not False


class TestInferSchemaShape:
    def test_top_level_is_object(self) -> None:
        schema = infer_schema(_fn_str)
        assert schema["type"] == "object"

    def test_no_additional_properties_by_default(self) -> None:
        schema = infer_schema(_fn_str)
        assert "additionalProperties" not in schema

    def test_kwargs_allows_additional_properties(self) -> None:
        schema = infer_schema(_fn_kwargs)
        assert (
            "additionalProperties" not in schema
            or schema.get("additionalProperties") is not False
        )
