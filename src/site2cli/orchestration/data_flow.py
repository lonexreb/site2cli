"""JSONPath-like data extraction for orchestration data flow."""

from __future__ import annotations

import re
from typing import Any

from site2cli.models import OrchestrationStep, StepResult


def extract_value(data: Any, path: str) -> Any:
    """Extract a value from nested data using a simple path expression.

    Supports:
        $result.data[0].id          -> data["data"][0]["id"]
        $steps.step1.result.price   -> step_results["step1"].result["price"]
        $result.items[2].name       -> data["items"][2]["name"]

    Returns None for missing keys or out-of-bounds indices.
    """
    # Strip leading $result. or $steps.xxx.result.
    parts = _parse_path(path)
    current = data
    for part in parts:
        if current is None:
            return None
        if isinstance(part, int):
            if isinstance(current, (list, tuple)) and 0 <= part < len(current):
                current = current[part]
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _parse_path(path: str) -> list[str | int]:
    """Parse a path expression into segments.

    "data[0].id" -> ["data", 0, "id"]
    "$result.data[0].id" -> ["data", 0, "id"]
    "$steps.step1.result.price" -> ["price"]  (step1.result prefix stripped)
    """
    # Strip $result. prefix
    if path.startswith("$result."):
        path = path[len("$result."):]
    elif path.startswith("$steps."):
        # $steps.step_id.result.field -> just "field" (step lookup done by caller)
        parts = path.split(".", 3)  # ["$steps", "step_id", "result", "rest"]
        if len(parts) >= 4:
            path = parts[3]
        else:
            return []

    segments: list[str | int] = []
    for token in path.split("."):
        if not token:
            continue
        # Handle array indexing: "items[0]" -> "items", 0
        match = re.match(r"^(\w+)\[(\d+)\]$", token)
        if match:
            segments.append(match.group(1))
            segments.append(int(match.group(2)))
        else:
            segments.append(token)
    return segments


def get_step_reference(path: str) -> str | None:
    """Extract the step_id from a $steps.xxx reference, or None."""
    if path.startswith("$steps."):
        parts = path.split(".", 3)
        if len(parts) >= 2:
            return parts[1]
    return None


def resolve_params(
    step: OrchestrationStep,
    step_results: dict[str, StepResult],
    previous_result: dict | None = None,
) -> dict:
    """Merge static params with dynamically resolved data mappings."""
    resolved = dict(step.params)

    for mapping in step.data_mappings:
        step_ref = get_step_reference(mapping.source_path)
        if step_ref and step_ref in step_results:
            source_data = step_results[step_ref].result
        elif previous_result is not None:
            source_data = previous_result
        else:
            continue

        value = extract_value(source_data, mapping.source_path)
        if value is not None:
            resolved[mapping.target_param] = value

    return resolved
