"""Schema-driven structured data extraction from web pages using LLM."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from site2cli.config import get_config
from site2cli.content.converter import fetch_and_convert, format_for_llm


class ExtractionResult(BaseModel):
    """Result of a structured extraction."""

    success: bool
    data: dict | list | None = None
    url: str = ""
    error: str | None = None
    model: str = ""
    usage: dict = Field(default_factory=dict)


def _build_extraction_prompt(
    content: str,
    prompt: str | None = None,
    schema: dict | None = None,
) -> str:
    """Build the LLM prompt for structured extraction."""
    parts = [
        "You are a precise data extraction agent. Extract structured data from the "
        "provided web page content. Return ONLY valid JSON, no explanation or markdown.",
    ]

    if schema:
        parts.append(f"\nOutput must conform to this JSON Schema:\n```json\n"
                      f"{json.dumps(schema, indent=2)}\n```")

    if prompt:
        parts.append(f"\nExtraction instructions: {prompt}")

    if not prompt and not schema:
        parts.append(
            "\nExtract all meaningful structured data from the page. "
            "Return as a JSON object with descriptive keys."
        )

    parts.append(f"\n---\nPage content:\n{content}")

    return "\n".join(parts)


def _validate_against_schema(data: Any, schema: dict) -> tuple[bool, str | None]:
    """Validate extracted data against a JSON Schema.

    Returns (is_valid, error_message).
    """
    schema_type = schema.get("type", "object")

    if schema_type == "object" and not isinstance(data, dict):
        return False, f"Expected object, got {type(data).__name__}"

    if schema_type == "array" and not isinstance(data, list):
        return False, f"Expected array, got {type(data).__name__}"

    if schema_type == "object" and isinstance(data, dict):
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        for field_name in required:
            if field_name not in data:
                return False, f"Missing required field: {field_name}"

        for field_name, field_schema in properties.items():
            if field_name in data:
                value = data[field_name]
                expected_type = field_schema.get("type")
                if expected_type and not _check_type(value, expected_type):
                    return False, (
                        f"Field '{field_name}': expected {expected_type}, "
                        f"got {type(value).__name__}"
                    )

    return True, None


def _check_type(value: Any, expected: str) -> bool:
    """Check if a value matches a JSON Schema type."""
    type_map = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None),
    }
    expected_types = type_map.get(expected)
    if expected_types is None:
        return True
    return isinstance(value, expected_types)


def load_schema(schema_input: str | dict) -> dict:
    """Load a JSON Schema from a string, file path, or dict.

    Accepts:
        - A dict (already parsed)
        - A JSON string
        - A file path to a .json file
        - A Python import path like "mymodule.MyModel" (Pydantic model)
    """
    if isinstance(schema_input, dict):
        return schema_input

    if isinstance(schema_input, str):
        # Try as JSON string
        try:
            return json.loads(schema_input)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try as file path
        from pathlib import Path

        path = Path(schema_input)
        if path.exists() and path.suffix == ".json":
            return json.loads(path.read_text())

        # Try as Pydantic model import
        if "." in schema_input:
            try:
                module_path, class_name = schema_input.rsplit(".", 1)
                import importlib

                module = importlib.import_module(module_path)
                model_class = getattr(module, class_name)
                if hasattr(model_class, "model_json_schema"):
                    return model_class.model_json_schema()
            except (ImportError, AttributeError):
                pass

        raise ValueError(
            f"Cannot load schema from: {schema_input!r}. "
            "Provide a JSON string, .json file path, or Pydantic model path (module.Class)."
        )

    raise TypeError(f"Schema must be a dict or string, got {type(schema_input).__name__}")


async def extract(
    url: str,
    *,
    prompt: str | None = None,
    schema: dict | str | None = None,
    output_format: str = "markdown",
    main_content_only: bool = True,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    proxy: str | None = None,
    max_content_chars: int = 50_000,
) -> ExtractionResult:
    """Extract structured data from a web page using an LLM.

    Args:
        url: URL to extract data from.
        prompt: Natural language description of what to extract.
        schema: JSON Schema (dict, JSON string, file path, or Pydantic model path).
        output_format: How to convert HTML before sending to LLM.
        main_content_only: Only send main content to LLM.
        headers: Extra HTTP headers.
        cookies: Cookies for authenticated pages.
        proxy: Proxy URL.
        max_content_chars: Max chars to send to LLM.

    Returns:
        ExtractionResult with extracted data.
    """
    # Resolve schema
    resolved_schema = load_schema(schema) if schema else None

    if not prompt and not resolved_schema:
        return ExtractionResult(
            success=False,
            url=url,
            error="Either prompt or schema (or both) is required.",
        )

    # Fetch and convert the page
    try:
        page = fetch_and_convert(
            url,
            output_format=output_format,
            main_content_only=main_content_only,
            headers=headers,
            cookies=cookies,
            proxy=proxy,
        )
    except Exception as e:
        return ExtractionResult(success=False, url=url, error=f"Fetch failed: {e}")

    content = format_for_llm(page["content"], url=url, max_chars=max_content_chars)

    # Build prompt and call LLM
    extraction_prompt = _build_extraction_prompt(content, prompt, resolved_schema)

    config = get_config()
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.llm.get_api_key())
        response = client.messages.create(
            model=config.llm.model,
            max_tokens=config.llm.max_tokens,
            messages=[{"role": "user", "content": extraction_prompt}],
        )

        raw_text = response.content[0].text.strip()
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
    except ImportError:
        return ExtractionResult(
            success=False,
            url=url,
            error="Anthropic SDK not installed. Run: pip install site2cli[llm]",
        )
    except Exception as e:
        return ExtractionResult(success=False, url=url, error=f"LLM call failed: {e}")

    # Parse JSON from LLM response
    try:
        # Strip markdown code fences if present
        json_text = raw_text
        if json_text.startswith("```"):
            lines = json_text.split("\n")
            # Remove first and last fence lines
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            json_text = "\n".join(lines)

        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        return ExtractionResult(
            success=False,
            url=url,
            error=f"LLM returned invalid JSON: {e}",
            model=config.llm.model,
            usage=usage,
        )

    # Validate against schema
    if resolved_schema:
        is_valid, validation_error = _validate_against_schema(data, resolved_schema)
        if not is_valid:
            return ExtractionResult(
                success=False,
                data=data,
                url=url,
                error=f"Schema validation failed: {validation_error}",
                model=config.llm.model,
                usage=usage,
            )

    return ExtractionResult(
        success=True,
        data=data,
        url=url,
        model=config.llm.model,
        usage=usage,
    )


async def extract_batch(
    urls: list[str],
    *,
    prompt: str | None = None,
    schema: dict | str | None = None,
    **kwargs: Any,
) -> list[ExtractionResult]:
    """Extract structured data from multiple URLs.

    Processes URLs concurrently for efficiency.
    """
    import asyncio

    tasks = [
        extract(url, prompt=prompt, schema=schema, **kwargs)
        for url in urls
    ]
    return await asyncio.gather(*tasks)
