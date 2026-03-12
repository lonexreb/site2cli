"""Generate OpenAPI 3.1 specs from discovered endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from webcli.models import DiscoveredAPI, EndpointInfo, ParameterInfo


def _param_to_openapi(param: ParameterInfo) -> dict:
    """Convert a ParameterInfo to OpenAPI parameter or schema property."""
    type_map = {
        "string": "string",
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "array": "array",
        "object": "object",
    }
    schema = {"type": type_map.get(param.param_type, "string")}
    if param.example:
        schema["example"] = param.example

    if param.location in ("query", "path", "header"):
        result = {
            "name": param.name,
            "in": param.location,
            "required": param.required,
            "schema": schema,
        }
        if param.description:
            result["description"] = param.description
        return result
    return schema


def _endpoint_to_openapi_path(endpoint: EndpointInfo) -> dict:
    """Convert an EndpointInfo to an OpenAPI path item operation."""
    operation: dict = {
        "operationId": endpoint.description.replace(" ", "_").lower()
        if endpoint.description
        else f"{endpoint.method.lower()}_{endpoint.path_pattern.replace('/', '_').strip('_')}",
        "summary": endpoint.description or f"{endpoint.method} {endpoint.path_pattern}",
    }

    # Parameters (query, path, header)
    params = []
    body_props = {}
    body_required = []
    for param in endpoint.parameters:
        if param.location in ("query", "path", "header"):
            params.append(_param_to_openapi(param))
        elif param.location == "body":
            body_props[param.name] = _param_to_openapi(param)
            if param.required:
                body_required.append(param.name)

    if params:
        operation["parameters"] = params

    # Request body
    if body_props or endpoint.request_schema:
        schema = endpoint.request_schema or {
            "type": "object",
            "properties": body_props,
        }
        if body_required and "required" not in schema:
            schema["required"] = body_required
        operation["requestBody"] = {
            "required": True,
            "content": {
                endpoint.request_content_type
                or "application/json": {"schema": schema},
            },
        }

    # Responses
    responses: dict = {"200": {"description": "Successful response"}}
    if endpoint.response_schema:
        responses["200"]["content"] = {
            endpoint.response_content_type
            or "application/json": {"schema": endpoint.response_schema},
        }
    operation["responses"] = responses

    # Security
    if endpoint.auth_required:
        operation["security"] = [{"bearerAuth": []}]

    return operation


def generate_openapi_spec(api: DiscoveredAPI) -> dict:
    """Generate a complete OpenAPI 3.1 spec from a DiscoveredAPI."""
    parsed = urlparse(api.base_url)

    spec: dict = {
        "openapi": "3.1.0",
        "info": {
            "title": f"{api.site_url} API",
            "description": api.description or f"Auto-discovered API for {api.site_url}",
            "version": "1.0.0",
            "x-generated-by": "webcli",
        },
        "servers": [{"url": api.base_url}],
        "paths": {},
    }

    # Group endpoints by path
    for endpoint in api.endpoints:
        path = endpoint.path_pattern
        if path not in spec["paths"]:
            spec["paths"][path] = {}
        method = endpoint.method.lower()
        spec["paths"][path][method] = _endpoint_to_openapi_path(endpoint)

    # Add security schemes if any endpoint requires auth
    if any(ep.auth_required for ep in api.endpoints):
        spec["components"] = {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                },
                "apiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                },
                "cookieAuth": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "session",
                },
            }
        }

    return spec


def save_spec(spec: dict, output_path: Path) -> Path:
    """Save an OpenAPI spec to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(spec, f, indent=2)
    return output_path


def load_spec(spec_path: Path) -> dict:
    """Load an OpenAPI spec from a JSON file."""
    with open(spec_path) as f:
        return json.load(f)
