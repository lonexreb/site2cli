"""Integration test: Live API discovery against real public APIs.

Tests the full pipeline against:
- JSONPlaceholder (jsonplaceholder.typicode.com) — free fake REST API
- httpbin.org — HTTP request/response testing

These tests make real HTTP requests but do NOT require API keys.
They DO require network access.

Marked with pytest.mark.live so they can be skipped in CI:
    pytest -m "not live"
"""

import json

import httpx
import pytest

from site2cli.discovery.analyzer import TrafficAnalyzer
from site2cli.discovery.client_generator import generate_client_code, save_client
from site2cli.discovery.spec_generator import generate_openapi_spec
from site2cli.generators.mcp_gen import generate_mcp_server_code
from site2cli.models import (
    AuthType,
    CapturedExchange,
    CapturedHeader,
    CapturedRequest,
    CapturedResponse,
    DiscoveredAPI,
    SiteEntry,
)


def _capture_real_request(method: str, url: str, body: str | None = None) -> CapturedExchange:
    """Make a real HTTP request and capture it as a CapturedExchange."""
    headers = {"Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"

    with httpx.Client(timeout=15) as client:
        response = client.request(method, url, content=body, headers=headers)

    return CapturedExchange(
        request=CapturedRequest(
            method=method,
            url=url,
            headers=[CapturedHeader(name=k, value=v) for k, v in headers.items()],
            body=body,
            content_type=headers.get("Content-Type"),
        ),
        response=CapturedResponse(
            status=response.status_code,
            body=response.text,
            content_type=response.headers.get("content-type", ""),
            headers=[CapturedHeader(name=k, value=v) for k, v in response.headers.items()],
        ),
    )


@pytest.mark.live
class TestJSONPlaceholderDiscovery:
    """Discover JSONPlaceholder API from real HTTP traffic."""

    @pytest.fixture(autouse=True)
    def capture_traffic(self):
        """Capture real traffic from JSONPlaceholder."""
        try:
            self.exchanges = [
                _capture_real_request("GET", "https://jsonplaceholder.typicode.com/posts"),
                _capture_real_request("GET", "https://jsonplaceholder.typicode.com/posts/1"),
                _capture_real_request("GET", "https://jsonplaceholder.typicode.com/posts/2"),
                _capture_real_request("GET", "https://jsonplaceholder.typicode.com/posts?userId=1"),
                _capture_real_request(
                    "POST",
                    "https://jsonplaceholder.typicode.com/posts",
                    json.dumps({"title": "test", "body": "test body", "userId": 1}),
                ),
                _capture_real_request("GET", "https://jsonplaceholder.typicode.com/comments?postId=1"),
                _capture_real_request("GET", "https://jsonplaceholder.typicode.com/users/1"),
            ]
        except httpx.ConnectError:
            pytest.skip("No network access")

    def test_analyze_real_traffic(self):
        """Analyze real JSONPlaceholder traffic."""
        analyzer = TrafficAnalyzer(self.exchanges)
        endpoints = analyzer.extract_endpoints()

        assert len(endpoints) >= 4

        # Should find GET /posts, GET /posts/{id}, POST /posts, GET /comments, GET /users/{id}
        methods_paths = {(e.method, e.path_pattern) for e in endpoints}
        assert ("GET", "/posts") in methods_paths
        assert ("GET", "/posts/{id}") in methods_paths
        assert ("POST", "/posts") in methods_paths

    def test_generate_valid_spec(self):
        """Generate and validate OpenAPI spec from real traffic."""
        analyzer = TrafficAnalyzer(self.exchanges)
        endpoints = analyzer.extract_endpoints()

        api = DiscoveredAPI(
            site_url="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
            endpoints=endpoints,
            auth_type=AuthType.NONE,
        )
        spec = generate_openapi_spec(api)

        # Validate with openapi-spec-validator
        from openapi_spec_validator import validate

        validate(spec)

        assert spec["openapi"] == "3.1.0"
        assert "/posts" in spec["paths"]
        assert "/posts/{id}" in spec["paths"]

    def test_generate_working_client(self, tmp_path):
        """Generate a client that can make real API calls."""
        analyzer = TrafficAnalyzer(self.exchanges)
        endpoints = analyzer.extract_endpoints()

        api = DiscoveredAPI(
            site_url="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
            endpoints=endpoints,
            auth_type=AuthType.NONE,
        )
        spec = generate_openapi_spec(api)
        code = generate_client_code(spec, class_name="JSONPlaceholderClient")

        # Save and import
        client_path = tmp_path / "client.py"
        save_client(code, client_path)

        import importlib.util

        mod_spec = importlib.util.spec_from_file_location("client", client_path)
        module = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(module)

        # Use the generated client to make a real API call
        client = module.JSONPlaceholderClient()
        try:
            # Find a GET method that doesn't require params
            for attr_name in dir(client):
                method = getattr(client, attr_name)
                if callable(method) and not attr_name.startswith("_") and attr_name != "close":
                    try:
                        # Try calling with no args (will work for list endpoints)
                        result = method()
                        assert isinstance(result, (dict, list))
                        break
                    except TypeError:
                        continue  # Method requires args
                    except httpx.HTTPStatusError:
                        continue  # Endpoint needs params
        finally:
            client.close()

    def test_generate_mcp_server(self):
        """Generate MCP server code from real traffic."""
        analyzer = TrafficAnalyzer(self.exchanges)
        endpoints = analyzer.extract_endpoints()

        api = DiscoveredAPI(
            site_url="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
            endpoints=endpoints,
            auth_type=AuthType.NONE,
        )
        spec = generate_openapi_spec(api)
        site = SiteEntry(
            domain="jsonplaceholder.typicode.com",
            base_url="https://jsonplaceholder.typicode.com",
        )
        code = generate_mcp_server_code(site, spec)

        # Verify it compiles and has expected structure
        compile(code, "<mcp>", "exec")
        assert "list_tools" in code
        assert "call_tool" in code
        assert "jsonplaceholder" in code.lower()


@pytest.mark.live
class TestHTTPBinDiscovery:
    """Discover httpbin.org API from real HTTP traffic."""

    @pytest.fixture(autouse=True)
    def capture_traffic(self):
        try:
            self.exchanges = [
                _capture_real_request("GET", "https://httpbin.org/get"),
                _capture_real_request(
                    "POST",
                    "https://httpbin.org/post",
                    json.dumps({"key": "value", "number": 42}),
                ),
                _capture_real_request("GET", "https://httpbin.org/headers"),
                _capture_real_request("GET", "https://httpbin.org/ip"),
                _capture_real_request("GET", "https://httpbin.org/user-agent"),
            ]
        except httpx.ConnectError:
            pytest.skip("No network access")

    def test_analyze_httpbin(self):
        """Analyze httpbin traffic."""
        analyzer = TrafficAnalyzer(self.exchanges)
        endpoints = analyzer.extract_endpoints()
        assert len(endpoints) >= 4

    def test_full_pipeline(self, tmp_path):
        """Full pipeline from traffic to registry for httpbin."""
        analyzer = TrafficAnalyzer(self.exchanges)
        endpoints = analyzer.extract_endpoints()

        api = DiscoveredAPI(
            site_url="httpbin.org",
            base_url="https://httpbin.org",
            endpoints=endpoints,
            auth_type=AuthType.NONE,
        )
        spec = generate_openapi_spec(api)

        from openapi_spec_validator import validate

        validate(spec)

        # Client
        code = generate_client_code(spec)
        compile(code, "<httpbin_client>", "exec")

        # MCP
        site = SiteEntry(domain="httpbin.org", base_url="https://httpbin.org")
        mcp_code = generate_mcp_server_code(site, spec)
        compile(mcp_code, "<httpbin_mcp>", "exec")
