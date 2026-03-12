"""Tests for OpenAPI spec generation."""

import json
import tempfile
from pathlib import Path

from webcli.discovery.spec_generator import generate_openapi_spec, load_spec, save_spec
from webcli.models import (
    AuthType,
    DiscoveredAPI,
    EndpointInfo,
    ParameterInfo,
)


def _make_api():
    return DiscoveredAPI(
        site_url="example.com",
        base_url="https://api.example.com",
        endpoints=[
            EndpointInfo(
                method="GET",
                path_pattern="/api/search",
                parameters=[
                    ParameterInfo(name="q", location="query", required=True, description="Search query"),
                    ParameterInfo(name="limit", location="query", param_type="integer"),
                ],
                description="Search for items",
                response_schema={"type": "object", "properties": {"results": {"type": "array"}}},
            ),
            EndpointInfo(
                method="POST",
                path_pattern="/api/items",
                parameters=[
                    ParameterInfo(name="name", location="body", required=True),
                    ParameterInfo(name="price", location="body", param_type="number"),
                ],
                description="Create an item",
                request_schema={"type": "object", "properties": {"name": {"type": "string"}}},
                auth_required=True,
            ),
            EndpointInfo(
                method="GET",
                path_pattern="/api/items/{id}",
                parameters=[
                    ParameterInfo(name="id", location="path", required=True),
                ],
                description="Get item by ID",
            ),
        ],
        auth_type=AuthType.API_KEY,
        description="Test API",
    )


def test_generate_spec_structure():
    api = _make_api()
    spec = generate_openapi_spec(api)

    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "example.com API"
    assert len(spec["servers"]) == 1
    assert spec["servers"][0]["url"] == "https://api.example.com"


def test_generate_spec_paths():
    api = _make_api()
    spec = generate_openapi_spec(api)

    assert "/api/search" in spec["paths"]
    assert "/api/items" in spec["paths"]
    assert "/api/items/{id}" in spec["paths"]


def test_generate_spec_get_parameters():
    api = _make_api()
    spec = generate_openapi_spec(api)

    search_op = spec["paths"]["/api/search"]["get"]
    params = search_op["parameters"]
    assert len(params) == 2
    q_param = [p for p in params if p["name"] == "q"][0]
    assert q_param["required"] is True
    assert q_param["in"] == "query"


def test_generate_spec_post_body():
    api = _make_api()
    spec = generate_openapi_spec(api)

    create_op = spec["paths"]["/api/items"]["post"]
    assert "requestBody" in create_op
    assert create_op["requestBody"]["required"] is True


def test_generate_spec_auth():
    api = _make_api()
    spec = generate_openapi_spec(api)

    assert "components" in spec
    assert "securitySchemes" in spec["components"]
    create_op = spec["paths"]["/api/items"]["post"]
    assert "security" in create_op


def test_save_and_load_spec(tmp_path):
    api = _make_api()
    spec = generate_openapi_spec(api)

    path = tmp_path / "test_spec.json"
    save_spec(spec, path)
    assert path.exists()

    loaded = load_spec(path)
    assert loaded["openapi"] == "3.1.0"
    assert loaded["paths"] == spec["paths"]
