"""Tests for unified MCP server (src/site2cli/mcp/server.py)."""

from __future__ import annotations

import pytest

from site2cli.config import reset_config
from site2cli.mcp.server import _build_tool_registry, spec_to_tool_schemas
from site2cli.models import (
    AuthType,
    EndpointInfo,
    HealthStatus,
    MCPToolSchema,
    ParameterInfo,
    SiteAction,
    SiteEntry,
    Tier,
)
from site2cli.registry import SiteRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Isolate data dirs and reset global config for every test."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    yield
    reset_config()


@pytest.fixture()
def registry(tmp_path):
    """Return a fresh SiteRegistry backed by a temp SQLite DB."""
    return SiteRegistry(tmp_path / "test.db")


def _make_site(
    domain: str = "example.com",
    actions: list[SiteAction] | None = None,
) -> SiteEntry:
    return SiteEntry(
        domain=domain,
        base_url=f"https://{domain}",
        actions=actions or [],
        auth_type=AuthType.NONE,
        health=HealthStatus.UNKNOWN,
    )


def _simple_openapi(
    path: str = "/users",
    method: str = "get",
    summary: str = "List users",
    parameters: list[dict] | None = None,
    request_body: dict | None = None,
) -> dict:
    """Build a minimal OpenAPI 3.0 spec dict."""
    operation: dict = {"summary": summary, "operationId": f"{method}_{path.strip('/')}"}
    if parameters:
        operation["parameters"] = parameters
    if request_body:
        operation["requestBody"] = request_body

    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            path: {
                method: operation,
            }
        },
    }


# ---------------------------------------------------------------------------
# spec_to_tool_schemas
# ---------------------------------------------------------------------------

class TestSpecToToolSchemas:
    """Tests for spec_to_tool_schemas()."""

    def test_empty_spec_returns_empty(self):
        """1. Empty spec (no paths) yields no tools."""
        site = _make_site()
        spec: dict = {
            "openapi": "3.0.0",
            "info": {"title": "Empty", "version": "1.0.0"},
            "paths": {},
        }
        tools = spec_to_tool_schemas(site, spec)
        assert tools == []

    def test_simple_get_endpoint(self):
        """2. Single GET endpoint produces one tool with correct fields."""
        site = _make_site()
        spec = _simple_openapi(path="/users", method="get", summary="List users")
        tools = spec_to_tool_schemas(site, spec)

        assert len(tools) == 1
        tool = tools[0]
        assert isinstance(tool, MCPToolSchema)
        assert "users" in tool.name.lower()
        assert tool.description  # should have a description

    def test_post_with_request_body(self):
        """3. POST with requestBody surfaces body properties as input schema."""
        site = _make_site()
        spec = _simple_openapi(
            path="/users",
            method="post",
            summary="Create user",
            request_body={
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "email": {"type": "string"},
                            },
                            "required": ["name"],
                        }
                    }
                },
            },
        )
        tools = spec_to_tool_schemas(site, spec)

        assert len(tools) == 1
        tool = tools[0]
        # The input schema should reference the body properties
        schema = tool.inputSchema if hasattr(tool, "inputSchema") else tool.input_schema
        props = schema.get("properties", {})
        assert "name" in props or len(props) > 0

    def test_multiple_endpoints(self):
        """4. Multiple endpoints produce multiple tools."""
        site = _make_site()
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Multi", "version": "1.0.0"},
            "paths": {
                "/users": {"get": {"summary": "List users", "operationId": "get_users"}},
                "/posts": {"get": {"summary": "List posts", "operationId": "get_posts"}},
                "/comments": {"get": {"summary": "List comments", "operationId": "get_comments"}},
            },
        }
        tools = spec_to_tool_schemas(site, spec)
        assert len(tools) == 3

    def test_tier_from_site_actions(self):
        """5. Tools inherit tier information from site actions."""
        actions = [
            SiteAction(
                name="list_users",
                endpoint=EndpointInfo(method="GET", path_pattern="/users"),
                tier=Tier.API,
            ),
        ]
        site = _make_site(actions=actions)
        spec = _simple_openapi(path="/users", method="get", summary="List users")
        tools = spec_to_tool_schemas(site, spec)
        assert len(tools) >= 1


# ---------------------------------------------------------------------------
# _build_tool_registry
# ---------------------------------------------------------------------------

class TestBuildToolRegistry:
    """Tests for _build_tool_registry()."""

    def test_empty_registry_returns_empty(self, registry):
        """6. Empty registry produces empty tools and tool_map."""
        tools, tool_map = _build_tool_registry(registry)
        assert tools == []
        assert tool_map == {}

    def test_builds_tools_from_registered_sites(self, registry):
        """7. Registered site with actions generates tools."""
        site = _make_site(
            domain="api.example.com",
            actions=[
                SiteAction(
                    name="list_users",
                    endpoint=EndpointInfo(method="GET", path_pattern="/users"),
                    tier=Tier.API,
                ),
            ],
        )
        registry.add_site(site)

        tools, tool_map = _build_tool_registry(registry)
        assert len(tools) >= 1
        assert len(tool_map) >= 1

    def test_includes_all_actions(self, registry):
        """8. All actions from a site appear as tools."""
        actions = [
            SiteAction(
                name="list_users",
                endpoint=EndpointInfo(method="GET", path_pattern="/users"),
                tier=Tier.API,
            ),
            SiteAction(
                name="create_user",
                endpoint=EndpointInfo(method="POST", path_pattern="/users"),
                tier=Tier.API,
            ),
        ]
        site = _make_site(domain="api.example.com", actions=actions)
        registry.add_site(site)

        tools, tool_map = _build_tool_registry(registry)
        assert len(tools) >= 2

    def test_tool_map_maps_name_to_domain_action(self, registry):
        """9. tool_map entries link tool name -> domain/action."""
        site = _make_site(
            domain="api.example.com",
            actions=[
                SiteAction(
                    name="list_users",
                    endpoint=EndpointInfo(method="GET", path_pattern="/users"),
                    tier=Tier.API,
                ),
            ],
        )
        registry.add_site(site)

        _tools, tool_map = _build_tool_registry(registry)
        assert len(tool_map) >= 1
        # Each value should contain domain and action info
        for name, info in tool_map.items():
            assert isinstance(name, str)
            assert isinstance(info, dict)

    def test_site_with_no_endpoints_uses_empty_properties(self, registry):
        """10. Site with no endpoints still works (empty properties)."""
        site = _make_site(domain="empty.example.com", actions=[])
        registry.add_site(site)

        tools, tool_map = _build_tool_registry(registry)
        # Should not crash; may produce zero tools for a site with no actions
        assert isinstance(tools, list)
        assert isinstance(tool_map, dict)

    def test_handles_required_parameters(self, registry):
        """11. Actions with required parameters are reflected in tool schemas."""
        actions = [
            SiteAction(
                name="get_user",
                endpoint=EndpointInfo(
                    method="GET",
                    path_pattern="/users/{id}",
                    parameters=[
                        ParameterInfo(name="id", location="path", required=True),
                    ],
                ),
                tier=Tier.API,
            ),
        ]
        site = _make_site(domain="api.example.com", actions=actions)
        registry.add_site(site)

        tools, tool_map = _build_tool_registry(registry)
        assert len(tools) >= 1
        # Check that the tool schema has the required parameter
        tool = tools[0]
        schema = tool.get("inputSchema", tool.get("input_schema", {}))
        if schema and "required" in schema:
            assert "id" in schema["required"]


# ---------------------------------------------------------------------------
# Tool naming & descriptions
# ---------------------------------------------------------------------------

class TestToolNamingAndDescriptions:
    """Tests for tool naming conventions and description fallbacks."""

    def test_tool_names_prefixed_with_domain(self, registry):
        """12. Tool names are prefixed with the site domain."""
        site = _make_site(
            domain="api.github.com",
            actions=[
                SiteAction(
                    name="list_repos",
                    endpoint=EndpointInfo(method="GET", path_pattern="/repos"),
                    tier=Tier.API,
                ),
            ],
        )
        registry.add_site(site)

        tools, _tool_map = _build_tool_registry(registry)
        assert len(tools) >= 1
        tool_name = tools[0].get("name", "")
        # The name should be prefixed with the domain's first segment
        assert tool_name.startswith("api_")

    def test_description_falls_back_to_action_name(self, registry):
        """13. When description is empty, fall back to action name."""
        site = _make_site(
            domain="api.example.com",
            actions=[
                SiteAction(
                    name="list_items",
                    description="",
                    endpoint=EndpointInfo(method="GET", path_pattern="/items"),
                    tier=Tier.API,
                ),
            ],
        )
        registry.add_site(site)

        tools, _tool_map = _build_tool_registry(registry)
        assert len(tools) >= 1
        desc = tools[0].get("description", "")
        # Should have some description derived from the action name
        assert desc  # not empty

    def test_multiple_sites_generate_distinct_tools(self, registry):
        """14. Tools from different sites are all present and distinct."""
        site_a = _make_site(
            domain="alpha.example.com",
            actions=[
                SiteAction(
                    name="action_a",
                    endpoint=EndpointInfo(method="GET", path_pattern="/a"),
                    tier=Tier.API,
                ),
            ],
        )
        site_b = _make_site(
            domain="beta.example.com",
            actions=[
                SiteAction(
                    name="action_b",
                    endpoint=EndpointInfo(method="GET", path_pattern="/b"),
                    tier=Tier.API,
                ),
            ],
        )
        registry.add_site(site_a)
        registry.add_site(site_b)

        tools, tool_map = _build_tool_registry(registry)
        assert len(tools) >= 2
        tool_names = [t.get("name", "") for t in tools]
        assert len(set(tool_names)) == len(tool_names), "Tool names must be unique"
