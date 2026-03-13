"""Tests for traffic analysis."""

from site2cli.discovery.analyzer import (
    TrafficAnalyzer,
    _detect_auth_type,
    _infer_json_schema,
    _normalize_path,
)
from site2cli.models import (
    AuthType,
    CapturedExchange,
    CapturedHeader,
    CapturedRequest,
    CapturedResponse,
)


def test_normalize_path_numeric_id():
    assert _normalize_path("/api/users/123") == "/api/users/{id}"
    assert _normalize_path("/api/users/123/posts/456") == "/api/users/{id}/posts/{id}"


def test_normalize_path_uuid():
    assert _normalize_path("/api/items/550e8400-e29b-41d4-a716-446655440000") == "/api/items/{id}"


def test_normalize_path_no_change():
    assert _normalize_path("/api/search") == "/api/search"


def test_infer_json_schema_primitives():
    assert _infer_json_schema("hello") == {"type": "string"}
    assert _infer_json_schema(42) == {"type": "integer"}
    assert _infer_json_schema(3.14) == {"type": "number"}
    assert _infer_json_schema(True) == {"type": "boolean"}
    assert _infer_json_schema(None) == {"type": "null"}


def test_infer_json_schema_array():
    result = _infer_json_schema([1, 2, 3])
    assert result["type"] == "array"
    assert result["items"]["type"] == "integer"


def test_infer_json_schema_object():
    result = _infer_json_schema({"name": "test", "count": 5})
    assert result["type"] == "object"
    assert "name" in result["properties"]
    assert result["properties"]["count"]["type"] == "integer"


def _make_exchange(method, url, req_body=None, resp_body=None, status=200, headers=None):
    req_headers = [CapturedHeader(name=k, value=v) for k, v in (headers or {}).items()]
    return CapturedExchange(
        request=CapturedRequest(
            method=method,
            url=url,
            body=req_body,
            content_type="application/json" if req_body else None,
            headers=req_headers,
        ),
        response=CapturedResponse(
            status=status,
            body=resp_body,
            content_type="application/json" if resp_body else None,
        ),
    )


def test_group_by_endpoint():
    exchanges = [
        _make_exchange("GET", "https://api.example.com/users/1"),
        _make_exchange("GET", "https://api.example.com/users/2"),
        _make_exchange("POST", "https://api.example.com/users"),
    ]
    analyzer = TrafficAnalyzer(exchanges)
    groups = analyzer.group_by_endpoint()

    assert len(groups) == 2
    assert "GET /users/{id}" in groups
    assert "POST /users" in groups
    assert len(groups["GET /users/{id}"]) == 2


def test_extract_endpoints():
    exchanges = [
        _make_exchange(
            "GET",
            "https://api.example.com/search?q=test&limit=10",
            resp_body='{"results": []}',
        ),
        _make_exchange(
            "POST",
            "https://api.example.com/items",
            req_body='{"name": "widget", "price": 9.99}',
            resp_body='{"id": 123}',
        ),
    ]
    analyzer = TrafficAnalyzer(exchanges)
    endpoints = analyzer.extract_endpoints()

    assert len(endpoints) == 2

    get_ep = [e for e in endpoints if e.method == "GET"][0]
    assert any(p.name == "q" for p in get_ep.parameters)

    post_ep = [e for e in endpoints if e.method == "POST"][0]
    assert any(p.name == "name" for p in post_ep.parameters)
    assert post_ep.request_schema is not None


def test_detect_auth_bearer():
    exchanges = [
        _make_exchange(
            "GET", "https://api.example.com/me",
            headers={"Authorization": "Bearer abc123"},
        ),
    ]
    assert _detect_auth_type(exchanges) == AuthType.OAUTH


def test_detect_auth_api_key():
    exchanges = [
        _make_exchange(
            "GET", "https://api.example.com/data",
            headers={"X-API-Key": "key123"},
        ),
    ]
    assert _detect_auth_type(exchanges) == AuthType.API_KEY


def test_detect_auth_cookie():
    exchanges = [
        _make_exchange(
            "GET", "https://api.example.com/data",
            headers={"Cookie": "session=abc123"},
        ),
    ]
    assert _detect_auth_type(exchanges) == AuthType.COOKIE


def test_detect_auth_none():
    exchanges = [
        _make_exchange("GET", "https://api.example.com/public"),
    ]
    assert _detect_auth_type(exchanges) == AuthType.NONE


# --- Additional analyzer tests ---


def test_normalize_path_mongodb_objectid():
    assert _normalize_path("/api/docs/507f1f77bcf86cd799439011") == "/api/docs/{id}"


def test_normalize_path_preserves_non_id_segments():
    assert _normalize_path("/api/v2/search/results") == "/api/v2/search/results"


def test_infer_json_schema_empty_array():
    result = _infer_json_schema([])
    assert result["type"] == "array"
    assert result["items"] == {}


def test_infer_json_schema_nested_object():
    result = _infer_json_schema({"user": {"name": "test", "age": 25}})
    assert result["type"] == "object"
    assert result["properties"]["user"]["type"] == "object"
    assert result["properties"]["user"]["properties"]["name"]["type"] == "string"


def test_group_by_endpoint_caches_result():
    exchanges = [_make_exchange("GET", "https://api.example.com/items")]
    analyzer = TrafficAnalyzer(exchanges)
    groups1 = analyzer.group_by_endpoint()
    groups2 = analyzer.group_by_endpoint()
    assert groups1 is groups2


def test_extract_endpoints_with_path_params():
    exchanges = [
        _make_exchange(
            "GET", "https://api.example.com/users/42",
            resp_body='{"id": 42, "name": "Alice"}',
        ),
    ]
    analyzer = TrafficAnalyzer(exchanges)
    endpoints = analyzer.extract_endpoints()
    assert len(endpoints) == 1
    assert endpoints[0].path_pattern == "/users/{id}"
    assert any(p.name == "id" and p.location == "path" for p in endpoints[0].parameters)


def test_extract_endpoints_detects_auth_required():
    exchanges = [
        _make_exchange(
            "GET", "https://api.example.com/private",
            headers={"Authorization": "Bearer token123"},
            resp_body='{"data": "secret"}',
        ),
    ]
    analyzer = TrafficAnalyzer(exchanges)
    endpoints = analyzer.extract_endpoints()
    assert endpoints[0].auth_required is True


def test_extract_endpoints_response_schema_inferred():
    exchanges = [
        _make_exchange(
            "GET", "https://api.example.com/stats",
            resp_body='{"count": 42, "active": true}',
        ),
    ]
    analyzer = TrafficAnalyzer(exchanges)
    endpoints = analyzer.extract_endpoints()
    assert endpoints[0].response_schema is not None
    assert endpoints[0].response_schema["type"] == "object"


def test_extract_endpoints_large_response_no_example():
    large_body = '{"data": "' + "x" * 6000 + '"}'
    exchanges = [
        _make_exchange(
            "GET", "https://api.example.com/big",
            resp_body=large_body,
        ),
    ]
    analyzer = TrafficAnalyzer(exchanges)
    endpoints = analyzer.extract_endpoints()
    assert endpoints[0].example_response is None
    assert endpoints[0].response_schema is not None


def test_detect_auth_basic():
    exchanges = [
        _make_exchange(
            "GET", "https://api.example.com/data",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        ),
    ]
    assert _detect_auth_type(exchanges) == AuthType.API_KEY


def test_group_multiple_methods_same_path():
    exchanges = [
        _make_exchange("GET", "https://api.example.com/items"),
        _make_exchange("POST", "https://api.example.com/items"),
        _make_exchange("DELETE", "https://api.example.com/items/1"),
    ]
    analyzer = TrafficAnalyzer(exchanges)
    groups = analyzer.group_by_endpoint()
    assert "GET /items" in groups
    assert "POST /items" in groups
    assert "DELETE /items/{id}" in groups
