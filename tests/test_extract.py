"""Tests for schema-driven extraction."""

from __future__ import annotations

import json

import pytest

from site2cli.extract.extractor import (
    ExtractionResult,
    _build_extraction_prompt,
    _check_type,
    _validate_against_schema,
    load_schema,
)

# --- load_schema ---


def test_load_schema_from_dict():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    result = load_schema(schema)
    assert result == schema


def test_load_schema_from_json_string():
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
    result = load_schema(json.dumps(schema))
    assert result == schema


def test_load_schema_from_file(tmp_path):
    schema = {"type": "object", "properties": {"url": {"type": "string"}}}
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))
    result = load_schema(str(schema_file))
    assert result == schema


def test_load_schema_invalid_string():
    with pytest.raises(ValueError, match="Cannot load schema"):
        load_schema("not-a-valid-schema")


def test_load_schema_invalid_type():
    with pytest.raises(TypeError, match="must be a dict or string"):
        load_schema(123)  # type: ignore[arg-type]


def test_load_schema_from_pydantic_model():
    """Test loading schema from a Pydantic model import path."""
    # Use a known Pydantic model from our own codebase
    result = load_schema("site2cli.extract.extractor.ExtractionResult")
    assert "properties" in result
    assert "success" in result["properties"]


# --- _validate_against_schema ---


def test_validate_valid_object():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }
    is_valid, error = _validate_against_schema({"name": "Alice", "age": 30}, schema)
    assert is_valid
    assert error is None


def test_validate_missing_required():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    is_valid, error = _validate_against_schema({"age": 30}, schema)
    assert not is_valid
    assert "Missing required field: name" in error


def test_validate_wrong_type():
    schema = {
        "type": "object",
        "properties": {"age": {"type": "integer"}},
    }
    is_valid, error = _validate_against_schema({"age": "thirty"}, schema)
    assert not is_valid
    assert "expected integer" in error


def test_validate_expected_object_got_list():
    schema = {"type": "object", "properties": {}}
    is_valid, error = _validate_against_schema([1, 2, 3], schema)
    assert not is_valid
    assert "Expected object" in error


def test_validate_array_type():
    schema = {"type": "array"}
    is_valid, error = _validate_against_schema([1, 2, 3], schema)
    assert is_valid


def test_validate_expected_array_got_object():
    schema = {"type": "array"}
    is_valid, error = _validate_against_schema({"key": "value"}, schema)
    assert not is_valid
    assert "Expected array" in error


# --- _check_type ---


def test_check_type_string():
    assert _check_type("hello", "string")
    assert not _check_type(123, "string")


def test_check_type_number():
    assert _check_type(42, "number")
    assert _check_type(3.14, "number")
    assert not _check_type("42", "number")


def test_check_type_integer():
    assert _check_type(42, "integer")
    assert not _check_type(3.14, "integer")


def test_check_type_boolean():
    assert _check_type(True, "boolean")
    assert not _check_type("true", "boolean")


def test_check_type_array():
    assert _check_type([1, 2], "array")
    assert not _check_type({"a": 1}, "array")


def test_check_type_object():
    assert _check_type({"a": 1}, "object")
    assert not _check_type([1, 2], "object")


def test_check_type_null():
    assert _check_type(None, "null")
    assert not _check_type("", "null")


def test_check_type_unknown():
    # Unknown types pass validation
    assert _check_type("anything", "custom_type")


# --- _build_extraction_prompt ---


def test_prompt_with_schema():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    result = _build_extraction_prompt("page content", schema=schema)
    assert "JSON Schema" in result
    assert "page content" in result


def test_prompt_with_natural_language():
    result = _build_extraction_prompt("page content", prompt="Get all prices")
    assert "Get all prices" in result
    assert "page content" in result


def test_prompt_with_both():
    schema = {"type": "object", "properties": {"price": {"type": "number"}}}
    result = _build_extraction_prompt("content", prompt="Get prices", schema=schema)
    assert "Get prices" in result
    assert "JSON Schema" in result


def test_prompt_without_schema_or_prompt():
    result = _build_extraction_prompt("page content")
    assert "meaningful structured data" in result


# --- ExtractionResult model ---


def test_extraction_result_success():
    result = ExtractionResult(success=True, data={"title": "Hello"}, url="https://example.com")
    assert result.success
    assert result.data["title"] == "Hello"


def test_extraction_result_failure():
    result = ExtractionResult(success=False, error="LLM failed", url="https://example.com")
    assert not result.success
    assert "LLM" in result.error
