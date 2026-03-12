"""LLM-assisted pattern analysis of captured API traffic."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from webcli.config import get_config
from webcli.models import (
    AuthType,
    CapturedExchange,
    EndpointInfo,
    ParameterInfo,
)

# Regex for common path parameter patterns (UUIDs, numeric IDs, slugs)
PATH_PARAM_PATTERNS = [
    (re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "/{id}"),
    (re.compile(r"/\d+(?=/|$)"), "/{id}"),
    (re.compile(r"/[0-9a-f]{24}(?=/|$)"), "/{id}"),  # MongoDB ObjectIDs
]


def _normalize_path(path: str) -> str:
    """Replace dynamic path segments with parameter placeholders."""
    for pattern, replacement in PATH_PARAM_PATTERNS:
        path = pattern.sub(replacement, path)
    return path


def _infer_json_schema(data: object) -> dict:
    """Infer a JSON Schema from a sample value."""
    if data is None:
        return {"type": "null"}
    if isinstance(data, bool):
        return {"type": "boolean"}
    if isinstance(data, int):
        return {"type": "integer"}
    if isinstance(data, float):
        return {"type": "number"}
    if isinstance(data, str):
        return {"type": "string"}
    if isinstance(data, list):
        if not data:
            return {"type": "array", "items": {}}
        return {"type": "array", "items": _infer_json_schema(data[0])}
    if isinstance(data, dict):
        properties = {}
        for k, v in data.items():
            properties[k] = _infer_json_schema(v)
        return {"type": "object", "properties": properties}
    return {}


def _detect_auth_type(exchanges: list[CapturedExchange]) -> AuthType:
    """Detect the authentication scheme from request headers."""
    for ex in exchanges:
        for header in ex.request.headers:
            name_lower = header.name.lower()
            if name_lower == "authorization":
                val = header.value.lower()
                if val.startswith("bearer"):
                    return AuthType.OAUTH
                if val.startswith("basic"):
                    return AuthType.API_KEY
            if name_lower == "x-api-key":
                return AuthType.API_KEY
            if name_lower == "cookie" and header.value:
                return AuthType.COOKIE
    return AuthType.NONE


class TrafficAnalyzer:
    """Analyzes captured traffic to discover API patterns."""

    def __init__(self, exchanges: list[CapturedExchange]) -> None:
        self.exchanges = exchanges
        self._grouped: dict[str, list[CapturedExchange]] | None = None

    def group_by_endpoint(self) -> dict[str, list[CapturedExchange]]:
        """Group exchanges by normalized endpoint pattern."""
        if self._grouped is not None:
            return self._grouped
        groups: dict[str, list[CapturedExchange]] = {}
        for ex in self.exchanges:
            parsed = urlparse(ex.request.url)
            norm_path = _normalize_path(parsed.path)
            key = f"{ex.request.method} {norm_path}"
            groups.setdefault(key, []).append(ex)
        self._grouped = groups
        return groups

    def extract_endpoints(self) -> list[EndpointInfo]:
        """Extract endpoint info from grouped exchanges (no LLM needed)."""
        groups = self.group_by_endpoint()
        endpoints = []
        for key, exchanges in groups.items():
            method, path_pattern = key.split(" ", 1)
            ex = exchanges[0]  # Use first exchange as representative

            # Extract query parameters
            params = []
            parsed = urlparse(ex.request.url)
            query_params = parse_qs(parsed.query)
            for param_name, values in query_params.items():
                params.append(
                    ParameterInfo(
                        name=param_name,
                        location="query",
                        param_type="string",
                        required=False,
                        example=values[0] if values else None,
                    )
                )

            # Extract path parameters
            if "/{id}" in path_pattern:
                params.append(
                    ParameterInfo(
                        name="id",
                        location="path",
                        param_type="string",
                        required=True,
                    )
                )

            # Extract request body schema
            request_schema = None
            example_request = None
            if ex.request.body:
                try:
                    body_data = json.loads(ex.request.body)
                    request_schema = _infer_json_schema(body_data)
                    example_request = body_data
                    # Also extract body params
                    if isinstance(body_data, dict):
                        for param_name, val in body_data.items():
                            schema = _infer_json_schema(val)
                            params.append(
                                ParameterInfo(
                                    name=param_name,
                                    location="body",
                                    param_type=schema.get("type", "string"),
                                    required=True,
                                    example=str(val) if val is not None else None,
                                )
                            )
                except (json.JSONDecodeError, TypeError):
                    pass

            # Extract response schema
            response_schema = None
            example_response = None
            if ex.response.body:
                try:
                    resp_data = json.loads(ex.response.body)
                    response_schema = _infer_json_schema(resp_data)
                    # Truncate example if too large
                    resp_str = json.dumps(resp_data)
                    if len(resp_str) < 5000:
                        example_response = resp_data
                except (json.JSONDecodeError, TypeError):
                    pass

            # Detect auth
            auth_required = any(
                h.name.lower() in ("authorization", "x-api-key", "cookie")
                for h in ex.request.headers
            )

            endpoints.append(
                EndpointInfo(
                    method=method,
                    path_pattern=path_pattern,
                    parameters=params,
                    request_content_type=ex.request.content_type,
                    response_content_type=ex.response.content_type,
                    request_schema=request_schema,
                    response_schema=response_schema,
                    example_request=example_request,
                    example_response=example_response,
                    auth_required=auth_required,
                )
            )
        return endpoints

    def detect_auth(self) -> AuthType:
        return _detect_auth_type(self.exchanges)

    async def analyze_with_llm(self, endpoints: list[EndpointInfo]) -> list[EndpointInfo]:
        """Use LLM to enhance endpoint descriptions and parameter info."""
        config = get_config()
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=config.llm.get_api_key())
        except (ImportError, ValueError):
            return endpoints  # Return unenhanced if no LLM available

        # Prepare a summary for the LLM
        endpoint_summaries = []
        for ep in endpoints:
            summary = {
                "method": ep.method,
                "path": ep.path_pattern,
                "params": [p.model_dump() for p in ep.parameters],
                "request_schema": ep.request_schema,
                "response_schema": ep.response_schema,
            }
            endpoint_summaries.append(summary)

        prompt = f"""Analyze these API endpoints discovered from network traffic and provide descriptions.

Endpoints:
{json.dumps(endpoint_summaries, indent=2)}

For each endpoint, respond with a JSON array where each element has:
- "index": the endpoint index (0-based)
- "description": a clear description of what this endpoint does
- "param_descriptions": a dict mapping parameter name to description
- "inferred_name": a snake_case action name (e.g., "search_flights", "get_user_profile")

Respond with ONLY the JSON array, no other text."""

        try:
            response = client.messages.create(
                model=config.llm.model,
                max_tokens=config.llm.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            # Extract JSON from response
            json_match = re.search(r"\[.*\]", text, re.DOTALL)
            if json_match:
                enhancements = json.loads(json_match.group())
                for enh in enhancements:
                    idx = enh.get("index", -1)
                    if 0 <= idx < len(endpoints):
                        endpoints[idx].description = enh.get("description", "")
                        for param in endpoints[idx].parameters:
                            desc = enh.get("param_descriptions", {}).get(param.name)
                            if desc:
                                param.description = desc
        except Exception:
            pass  # Gracefully degrade if LLM fails

        return endpoints
