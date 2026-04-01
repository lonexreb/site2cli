"""Tests for orchestration data flow (JSONPath-like extraction)."""

from __future__ import annotations

from site2cli.models import DataMapping, OrchestrationStep, StepResult
from site2cli.orchestration.data_flow import extract_value, get_step_reference, resolve_params

# --- extract_value tests ---


def test_extract_simple_key():
    assert extract_value({"status": 200}, "$result.status") == 200


def test_extract_nested_key():
    data = {"data": {"name": "Alice"}}
    assert extract_value(data, "$result.data.name") == "Alice"


def test_extract_array_index():
    data = {"items": [{"id": 1}, {"id": 2}]}
    assert extract_value(data, "$result.items[0].id") == 1


def test_extract_deep_nesting():
    data = {"data": [{"items": [{"x": 0}, {"x": 42}]}]}
    assert extract_value(data, "$result.data[0].items[1].x") == 42


def test_extract_step_reference():
    data = {"price": 99.99}
    assert extract_value(data, "$steps.search.result.price") == 99.99


def test_extract_missing_key_returns_none():
    assert extract_value({"a": 1}, "$result.b") is None


def test_extract_out_of_bounds_returns_none():
    assert extract_value({"items": [1]}, "$result.items[5]") is None


def test_extract_from_none_returns_none():
    assert extract_value(None, "$result.x") is None


def test_extract_from_empty_dict():
    assert extract_value({}, "$result.x") is None


# --- get_step_reference tests ---


def test_get_step_reference_with_steps():
    assert get_step_reference("$steps.search_flights.result.price") == "search_flights"


def test_get_step_reference_without_steps():
    assert get_step_reference("$result.data") is None


# --- resolve_params tests ---


def test_resolve_static_only():
    step = OrchestrationStep(
        step_id="s1", domain="example.com", action="test",
        params={"q": "hello"},
    )
    result = resolve_params(step, {}, None)
    assert result == {"q": "hello"}


def test_resolve_with_data_mapping():
    step = OrchestrationStep(
        step_id="s2", domain="example.com", action="test",
        params={"city": "NYC"},
        data_mappings=[
            DataMapping(source_path="$result.data[0].id", target_param="user_id"),
        ],
    )
    previous = {"data": [{"id": 42}]}
    result = resolve_params(step, {}, previous)
    assert result == {"city": "NYC", "user_id": 42}


def test_resolve_data_mapping_overrides_static():
    step = OrchestrationStep(
        step_id="s2", domain="example.com", action="test",
        params={"user_id": "default"},
        data_mappings=[
            DataMapping(source_path="$result.id", target_param="user_id"),
        ],
    )
    previous = {"id": 99}
    result = resolve_params(step, {}, previous)
    assert result["user_id"] == 99


def test_resolve_from_named_step():
    step = OrchestrationStep(
        step_id="s3", domain="example.com", action="test",
        data_mappings=[
            DataMapping(
                source_path="$steps.search.result.price",
                target_param="max_price",
            ),
        ],
    )
    step_results = {
        "search": StepResult(
            step_id="search", domain="x.com", action="find",
            success=True, result={"price": 150},
        ),
    }
    result = resolve_params(step, step_results, None)
    assert result["max_price"] == 150


def test_resolve_missing_source_skips():
    step = OrchestrationStep(
        step_id="s2", domain="example.com", action="test",
        params={"q": "hello"},
        data_mappings=[
            DataMapping(source_path="$result.missing", target_param="extra"),
        ],
    )
    result = resolve_params(step, {}, {"other": 1})
    assert result == {"q": "hello"}  # extra not added


def test_resolve_multiple_mappings():
    step = OrchestrationStep(
        step_id="s3", domain="example.com", action="test",
        data_mappings=[
            DataMapping(source_path="$steps.a.result.x", target_param="px"),
            DataMapping(source_path="$steps.b.result.y", target_param="py"),
        ],
    )
    step_results = {
        "a": StepResult(step_id="a", domain="", action="", success=True, result={"x": 1}),
        "b": StepResult(step_id="b", domain="", action="", success=True, result={"y": 2}),
    }
    result = resolve_params(step, step_results, None)
    assert result == {"px": 1, "py": 2}
