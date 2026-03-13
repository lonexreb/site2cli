"""Tests that generated code (client, MCP server) compiles correctly."""

from site2cli.discovery.client_generator import generate_client_code
from site2cli.generators.mcp_gen import generate_mcp_server_code
from site2cli.models import SiteEntry


def _make_spec(paths=None):
    return {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": paths or {},
    }


def _make_site(domain="example.com", base_url="https://api.example.com"):
    return SiteEntry(domain=domain, base_url=base_url)


# --- Client code compilation tests ---


def test_client_compiles_empty_spec():
    """Generated client for an empty spec (no paths) must compile."""
    code = generate_client_code(_make_spec())
    compile(code, "<generated>", "exec")


def test_client_compiles_get_endpoints():
    """Generated client for GET-only endpoints must compile."""
    spec = _make_spec(
        paths={
            "/items": {
                "get": {
                    "operationId": "list_items",
                    "summary": "List all items",
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
            "/items/{id}": {
                "get": {
                    "operationId": "get_item",
                    "summary": "Get a single item",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        }
    )
    code = generate_client_code(spec)
    compile(code, "<generated>", "exec")


def test_client_compiles_post_with_request_body():
    """Generated client for a POST endpoint with a JSON request body must compile."""
    spec = _make_spec(
        paths={
            "/orders": {
                "post": {
                    "operationId": "create_order",
                    "summary": "Create a new order",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "product_id": {"type": "string"},
                                        "quantity": {"type": "integer"},
                                        "price": {"type": "number"},
                                    },
                                    "required": ["product_id", "quantity"],
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            }
        }
    )
    code = generate_client_code(spec)
    compile(code, "<generated>", "exec")


def test_client_compiles_path_parameters():
    """Generated client for endpoints with path parameters must compile."""
    spec = _make_spec(
        paths={
            "/users/{user_id}/posts/{post_id}": {
                "get": {
                    "operationId": "get_user_post",
                    "summary": "Get a specific post by a user",
                    "parameters": [
                        {
                            "name": "user_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "post_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        },
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
    )
    code = generate_client_code(spec)
    compile(code, "<generated>", "exec")


# --- MCP server compilation tests ---


def test_mcp_server_compiles_empty_spec():
    """Generated MCP server for an empty spec must compile."""
    site = _make_site()
    code = generate_mcp_server_code(site, _make_spec())
    compile(code, "<generated>", "exec")


def test_mcp_server_compiles_multiple_endpoints():
    """Generated MCP server for a spec with multiple endpoints must compile."""
    spec = _make_spec(
        paths={
            "/search": {
                "get": {
                    "operationId": "search",
                    "summary": "Search resources",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/resources": {
                "post": {
                    "operationId": "create_resource",
                    "summary": "Create a resource",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "value": {"type": "number"},
                                    },
                                    "required": ["name"],
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            },
            "/resources/{id}": {
                "delete": {
                    "operationId": "delete_resource",
                    "summary": "Delete a resource",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"204": {"description": "No Content"}},
                }
            },
        }
    )
    site = _make_site(domain="example.com", base_url="https://api.example.com")
    code = generate_mcp_server_code(site, spec)
    compile(code, "<generated>", "exec")


# --- Content correctness tests ---


def test_client_includes_correct_class_name():
    """generate_client_code respects an explicit class_name argument."""
    code = generate_client_code(_make_spec(), class_name="MyCustomClient")
    assert "class MyCustomClient" in code


def test_mcp_server_includes_correct_server_name():
    """Generated MCP server uses the site domain as the server name."""
    site = _make_site(domain="widgets.io", base_url="https://api.widgets.io")
    code = generate_mcp_server_code(site, _make_spec())
    assert "widgets.io-site2cli" in code
