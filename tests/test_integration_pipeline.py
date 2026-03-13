"""Integration test: Full pipeline with mock captured traffic.

Tests the complete flow:
  Captured exchanges → Analyze → OpenAPI spec → Client code → MCP server → Site registry

No browser or API keys required.
"""

import json
from pathlib import Path

from site2cli.discovery.analyzer import TrafficAnalyzer
from site2cli.discovery.client_generator import generate_client_code, save_client
from site2cli.discovery.spec_generator import generate_openapi_spec, save_spec
from site2cli.generators.mcp_gen import generate_mcp_server_code, save_mcp_server
from site2cli.models import (
    AuthType,
    CapturedExchange,
    CapturedHeader,
    CapturedRequest,
    CapturedResponse,
    DiscoveredAPI,
    SiteAction,
    SiteEntry,
    Tier,
)
from site2cli.registry import SiteRegistry

# --- Realistic mock traffic for JSONPlaceholder-like API ---

MOCK_EXCHANGES = [
    # GET /posts
    CapturedExchange(
        request=CapturedRequest(
            method="GET",
            url="https://jsonplaceholder.typicode.com/posts",
            headers=[CapturedHeader(name="Accept", value="application/json")],
        ),
        response=CapturedResponse(
            status=200,
            body=json.dumps([
                {"userId": 1, "id": 1, "title": "Test post", "body": "This is a test"},
                {"userId": 1, "id": 2, "title": "Another post", "body": "More content"},
            ]),
            content_type="application/json; charset=utf-8",
        ),
        duration_ms=45.0,
    ),
    # GET /posts/1
    CapturedExchange(
        request=CapturedRequest(
            method="GET",
            url="https://jsonplaceholder.typicode.com/posts/1",
            headers=[CapturedHeader(name="Accept", value="application/json")],
        ),
        response=CapturedResponse(
            status=200,
            body=json.dumps(
                {"userId": 1, "id": 1, "title": "Test post", "body": "This is a test"}
            ),
            content_type="application/json; charset=utf-8",
        ),
        duration_ms=32.0,
    ),
    # GET /posts/2
    CapturedExchange(
        request=CapturedRequest(
            method="GET",
            url="https://jsonplaceholder.typicode.com/posts/2",
            headers=[CapturedHeader(name="Accept", value="application/json")],
        ),
        response=CapturedResponse(
            status=200,
            body=json.dumps(
                {"userId": 1, "id": 2, "title": "Another post", "body": "More content"}
            ),
            content_type="application/json; charset=utf-8",
        ),
        duration_ms=28.0,
    ),
    # POST /posts
    CapturedExchange(
        request=CapturedRequest(
            method="POST",
            url="https://jsonplaceholder.typicode.com/posts",
            headers=[
                CapturedHeader(name="Content-Type", value="application/json"),
                CapturedHeader(name="Accept", value="application/json"),
            ],
            body=json.dumps({"title": "New post", "body": "New body", "userId": 1}),
            content_type="application/json",
        ),
        response=CapturedResponse(
            status=201,
            body=json.dumps({"id": 101, "title": "New post", "body": "New body", "userId": 1}),
            content_type="application/json; charset=utf-8",
        ),
        duration_ms=120.0,
    ),
    # GET /posts?userId=1
    CapturedExchange(
        request=CapturedRequest(
            method="GET",
            url="https://jsonplaceholder.typicode.com/posts?userId=1",
            headers=[CapturedHeader(name="Accept", value="application/json")],
        ),
        response=CapturedResponse(
            status=200,
            body=json.dumps([
                {"userId": 1, "id": 1, "title": "Test post", "body": "This is a test"},
            ]),
            content_type="application/json; charset=utf-8",
        ),
        duration_ms=38.0,
    ),
    # GET /comments?postId=1
    CapturedExchange(
        request=CapturedRequest(
            method="GET",
            url="https://jsonplaceholder.typicode.com/comments?postId=1",
            headers=[CapturedHeader(name="Accept", value="application/json")],
        ),
        response=CapturedResponse(
            status=200,
            body=json.dumps([
                {
                    "postId": 1,
                    "id": 1,
                    "name": "Comment 1",
                    "email": "test@example.com",
                    "body": "Great post!",
                },
            ]),
            content_type="application/json; charset=utf-8",
        ),
        duration_ms=42.0,
    ),
    # DELETE /posts/1
    CapturedExchange(
        request=CapturedRequest(
            method="DELETE",
            url="https://jsonplaceholder.typicode.com/posts/1",
            headers=[CapturedHeader(name="Accept", value="application/json")],
        ),
        response=CapturedResponse(
            status=200,
            body="{}",
            content_type="application/json; charset=utf-8",
        ),
        duration_ms=55.0,
    ),
]


class TestFullPipeline:
    """Test the complete discovery → generation → registration pipeline."""

    def test_step1_analyze_traffic(self):
        """Step 1: Analyze captured traffic into endpoint patterns."""
        analyzer = TrafficAnalyzer(MOCK_EXCHANGES)
        groups = analyzer.group_by_endpoint()

        # Should group: GET /posts, GET /posts/{id}, POST /posts,
        # GET /comments, DELETE /posts/{id}
        assert len(groups) >= 4
        assert "GET /posts" in groups
        assert "GET /posts/{id}" in groups
        assert "POST /posts" in groups

    def test_step2_extract_endpoints(self):
        """Step 2: Extract endpoint info with parameters and schemas."""
        analyzer = TrafficAnalyzer(MOCK_EXCHANGES)
        endpoints = analyzer.extract_endpoints()

        assert len(endpoints) >= 4

        # Verify GET /posts has query params
        get_posts = [e for e in endpoints if e.method == "GET" and e.path_pattern == "/posts"]
        assert len(get_posts) == 1
        param_names = {p.name for p in get_posts[0].parameters}
        assert "userId" in param_names

        # Verify POST /posts has body params
        post_posts = [e for e in endpoints if e.method == "POST"]
        assert len(post_posts) >= 1
        body_params = [p for p in post_posts[0].parameters if p.location == "body"]
        assert len(body_params) >= 2
        body_names = {p.name for p in body_params}
        assert "title" in body_names
        assert "body" in body_names

        # Verify response schemas were inferred
        assert get_posts[0].response_schema is not None
        assert get_posts[0].response_schema["type"] == "array"

    def test_step3_detect_auth(self):
        """Step 3: Auth detection (should be NONE for JSONPlaceholder)."""
        analyzer = TrafficAnalyzer(MOCK_EXCHANGES)
        auth = analyzer.detect_auth()
        assert auth == AuthType.NONE

    def test_step4_generate_openapi_spec(self):
        """Step 4: Generate valid OpenAPI 3.1 spec."""
        analyzer = TrafficAnalyzer(MOCK_EXCHANGES)
        endpoints = analyzer.extract_endpoints()

        api = DiscoveredAPI(
            site_url="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
            endpoints=endpoints,
            auth_type=AuthType.NONE,
            description="JSONPlaceholder fake REST API",
        )
        spec = generate_openapi_spec(api)

        # Validate spec structure
        assert spec["openapi"] == "3.1.0"
        assert "jsonplaceholder" in spec["info"]["title"].lower()
        assert len(spec["paths"]) >= 3
        assert "/posts" in spec["paths"]
        assert "/posts/{id}" in spec["paths"]

        # Validate GET /posts has parameters
        get_op = spec["paths"]["/posts"]["get"]
        assert "parameters" in get_op
        param_names = {p["name"] for p in get_op["parameters"]}
        assert "userId" in param_names

        # Validate POST /posts has request body
        post_op = spec["paths"]["/posts"]["post"]
        assert "requestBody" in post_op

        return spec

    def test_step5_save_and_load_spec(self, tmp_path):
        """Step 5: Persist spec to disk and reload."""
        spec = self.test_step4_generate_openapi_spec()

        spec_path = tmp_path / "jsonplaceholder.json"
        save_spec(spec, spec_path)
        assert spec_path.exists()

        from site2cli.discovery.spec_generator import load_spec

        loaded = load_spec(spec_path)
        assert loaded["openapi"] == spec["openapi"]
        assert loaded["paths"] == spec["paths"]

    def test_step6_generate_client_code(self):
        """Step 6: Generate Python client from spec."""
        spec = self.test_step4_generate_openapi_spec()
        code = generate_client_code(spec, class_name="JSONPlaceholderClient")

        # Verify class and methods exist
        assert "class JSONPlaceholderClient" in code
        assert "httpx" in code
        assert "self._base_url" in code
        assert "self._client" in code

        # Verify it has methods for our endpoints
        assert "def " in code  # At least one method

        # Verify the code is syntactically valid Python
        compile(code, "<generated>", "exec")

        return code

    def test_step7_save_client(self, tmp_path):
        """Step 7: Save client code to disk."""
        code = self.test_step6_generate_client_code()
        client_path = tmp_path / "jsonplaceholder_client.py"
        save_client(code, client_path)
        assert client_path.exists()

        # Verify the saved file is importable
        import importlib.util

        spec = importlib.util.spec_from_file_location("test_client", client_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "JSONPlaceholderClient")

    def test_step8_generate_mcp_server(self):
        """Step 8: Generate MCP server code from spec."""
        spec = self.test_step4_generate_openapi_spec()
        site = SiteEntry(
            domain="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
            description="JSONPlaceholder fake REST API",
        )
        code = generate_mcp_server_code(site, spec)

        # Verify MCP server structure
        assert "from mcp.server import Server" in code
        assert "from mcp import types" in code
        assert "async def list_tools" in code
        assert "async def call_tool" in code
        assert "jsonplaceholder" in code.lower()

        # Verify it compiles
        compile(code, "<generated_mcp>", "exec")

        return code

    def test_step9_save_mcp_server(self, tmp_path):
        """Step 9: Save MCP server to disk."""
        code = self.test_step8_generate_mcp_server()
        mcp_path = tmp_path / "jsonplaceholder_mcp.py"
        save_mcp_server(code, mcp_path)
        assert mcp_path.exists()

    def test_step10_register_site(self, tmp_path):
        """Step 10: Register discovered site in SQLite registry."""
        analyzer = TrafficAnalyzer(MOCK_EXCHANGES)
        endpoints = analyzer.extract_endpoints()
        spec = self.test_step4_generate_openapi_spec()

        # Save spec and client
        spec_path = tmp_path / "specs" / "jsonplaceholder.json"
        save_spec(spec, spec_path)

        code = generate_client_code(spec, class_name="JSONPlaceholderClient")
        client_path = tmp_path / "clients" / "jsonplaceholder_client.py"
        save_client(code, client_path)

        # Build site entry
        actions = [
            SiteAction(
                name=(
                    ep.description.replace(" ", "_").lower()
                    if ep.description
                    else f"{ep.method}_{ep.path_pattern}"
                ),
                description=ep.description or f"{ep.method} {ep.path_pattern}",
                tier=Tier.API,
                endpoint=ep,
            )
            for ep in endpoints
        ]
        site = SiteEntry(
            domain="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
            description="JSONPlaceholder fake REST API",
            actions=actions,
            auth_type=AuthType.NONE,
            openapi_spec_path=str(spec_path),
            client_module_path=str(client_path),
        )

        # Register
        db_path = tmp_path / "registry.db"
        registry = SiteRegistry(db_path)
        registry.add_site(site)

        # Verify retrieval
        retrieved = registry.get_site("jsonplaceholder.typicode.com")
        assert retrieved is not None
        assert retrieved.domain == "jsonplaceholder.typicode.com"
        assert len(retrieved.actions) >= 4
        assert retrieved.openapi_spec_path == str(spec_path)
        assert retrieved.client_module_path == str(client_path)

        # Verify actions have endpoints
        api_actions = [a for a in retrieved.actions if a.tier == Tier.API]
        assert len(api_actions) >= 4

        for action in api_actions:
            assert action.endpoint is not None

        registry.close()


class TestPipelineEndToEnd:
    """Single test that runs the entire pipeline start to finish."""

    def test_full_pipeline(self, tmp_path):
        """Complete pipeline: traffic → analyze → spec → client → MCP → registry."""
        # 1. Analyze
        analyzer = TrafficAnalyzer(MOCK_EXCHANGES)
        endpoints = analyzer.extract_endpoints()
        auth_type = analyzer.detect_auth()
        assert len(endpoints) >= 4
        assert auth_type == AuthType.NONE

        # 2. Generate OpenAPI spec
        api = DiscoveredAPI(
            site_url="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
            endpoints=endpoints,
            auth_type=auth_type,
        )
        spec = generate_openapi_spec(api)
        spec_path = tmp_path / "spec.json"
        save_spec(spec, spec_path)

        # Validate spec with openapi-spec-validator
        from openapi_spec_validator import validate

        validate(spec)  # Raises if invalid

        # 3. Generate Python client
        client_code = generate_client_code(spec)
        client_path = tmp_path / "client.py"
        save_client(client_code, client_path)
        compile(client_code, "<client>", "exec")

        # 4. Generate MCP server
        site = SiteEntry(
            domain="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
        )
        mcp_code = generate_mcp_server_code(site, spec)
        mcp_path = tmp_path / "mcp_server.py"
        save_mcp_server(mcp_code, mcp_path)
        compile(mcp_code, "<mcp>", "exec")

        # 5. Register in SQLite
        registry = SiteRegistry(tmp_path / "registry.db")
        actions = [
            SiteAction(
                name=(
                    f"{ep.method.lower()}_"
                    + ep.path_pattern.strip("/")
                    .replace("/", "_")
                    .replace("{", "")
                    .replace("}", "")
                ),
                description=ep.description or f"{ep.method} {ep.path_pattern}",
                tier=Tier.API,
                endpoint=ep,
            )
            for ep in endpoints
        ]
        full_site = SiteEntry(
            domain="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
            description="Auto-discovered API",
            actions=actions,
            auth_type=auth_type,
            openapi_spec_path=str(spec_path),
            client_module_path=str(client_path),
        )
        registry.add_site(full_site)

        # 6. Verify everything round-trips
        retrieved = registry.get_site("jsonplaceholder.typicode.com")
        assert retrieved is not None
        assert len(retrieved.actions) == len(actions)
        assert retrieved.openapi_spec_path is not None
        assert retrieved.client_module_path is not None

        # 7. Verify we can load the spec back
        from site2cli.discovery.spec_generator import load_spec

        loaded_spec = load_spec(Path(retrieved.openapi_spec_path))
        assert loaded_spec["openapi"] == "3.1.0"

        # 8. Verify we can import the client
        import importlib.util

        client_spec = importlib.util.spec_from_file_location(
            "client", retrieved.client_module_path
        )
        client_module = importlib.util.module_from_spec(client_spec)
        client_spec.loader.exec_module(client_module)

        registry.close()
