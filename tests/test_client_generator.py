"""Tests for Python client code generation."""

from webcli.discovery.client_generator import (
    _sanitize_name,
    _schema_to_type_hint,
    generate_client_code,
)


def test_sanitize_name():
    assert _sanitize_name("hello-world") == "hello_world"
    assert _sanitize_name("123start") == "_123start"
    assert _sanitize_name("camelCase") == "camelcase"
    assert _sanitize_name("foo__bar") == "foo_bar"


def test_schema_to_type_hint():
    assert _schema_to_type_hint({"type": "string"}) == "str"
    assert _schema_to_type_hint({"type": "integer"}) == "int"
    assert _schema_to_type_hint({"type": "number"}) == "float"
    assert _schema_to_type_hint({"type": "boolean"}) == "bool"
    assert _schema_to_type_hint({"type": "array", "items": {"type": "string"}}) == "list[str]"


def test_generate_client_code():
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Example API", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/search": {
                "get": {
                    "operationId": "search_items",
                    "summary": "Search for items",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        },
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/items": {
                "post": {
                    "operationId": "create_item",
                    "summary": "Create an item",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "price": {"type": "number"},
                                    },
                                    "required": ["name"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Created"}},
                }
            },
        },
    }

    code = generate_client_code(spec)

    assert "class ExampleClient" in code
    assert "def search_items" in code
    assert "def create_item" in code
    assert "q: str" in code
    assert "limit: int | None = None" in code
    assert "name: str" in code
    assert "httpx" in code
    assert "self._base_url" in code


def test_generate_client_custom_class_name():
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "servers": [{"url": "https://test.com"}],
        "paths": {},
    }
    code = generate_client_code(spec, class_name="MyCustomClient")
    assert "class MyCustomClient" in code
