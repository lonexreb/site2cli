"""Tests for browser-to-api parity features: coverage report, JS client,
YAML spec, and offline trace replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from site2cli.discovery.coverage_report import (
    compute_coverage,
    render_report,
    save_report,
)
from site2cli.discovery.js_client_generator import (
    generate_js_client,
    save_js_client,
)
from site2cli.discovery.spec_generator import (
    generate_openapi_spec,
    load_spec,
    save_spec,
)
from site2cli.discovery.trace import load_trace, save_trace
from site2cli.models import (
    AuthType,
    CapturedExchange,
    CapturedHeader,
    CapturedRequest,
    CapturedResponse,
    DiscoveredAPI,
    EndpointInfo,
    ParameterInfo,
)


def _sample_api() -> DiscoveredAPI:
    return DiscoveredAPI(
        site_url="example.com",
        base_url="https://example.com",
        endpoints=[
            EndpointInfo(
                method="GET",
                path_pattern="/api/items/{id}",
                description="Get item",
                parameters=[
                    ParameterInfo(name="id", location="path", required=True),
                    ParameterInfo(name="lang", location="query"),
                ],
                response_schema={"type": "object", "properties": {"id": {"type": "integer"}}},
                auth_required=True,
            ),
            EndpointInfo(
                method="POST",
                path_pattern="/api/items",
                description="Create item",
                parameters=[
                    ParameterInfo(name="name", location="body", required=True),
                ],
                request_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            ),
        ],
        auth_type=AuthType.API_KEY,
        description="Sample",
    )


def _sample_exchange(url: str, status: int = 200) -> CapturedExchange:
    return CapturedExchange(
        request=CapturedRequest(
            method="GET",
            url=url,
            headers=[CapturedHeader(name="accept", value="application/json")],
            content_type="application/json",
        ),
        response=CapturedResponse(status=status, content_type="application/json"),
    )


def test_compute_coverage_counts_endpoints_and_gaps() -> None:
    api = _sample_api()
    exchanges = [
        _sample_exchange("https://example.com/api/items/1"),
        _sample_exchange("https://example.com/api/items/2"),
        _sample_exchange("https://example.com/api/orphan", status=404),
    ]
    stats = compute_coverage(api, exchanges)

    assert stats.unique_endpoints == 2
    assert stats.api_requests == 3
    assert stats.endpoints_with_response_schema == 1
    assert stats.endpoints_with_request_schema == 1
    assert stats.auth_protected == 1
    assert stats.methods == {"GET": 1, "POST": 1}
    assert stats.status_codes == {"200": 2, "404": 1}
    assert "/api/orphan" in stats.gap_candidates


def test_render_report_produces_html_with_endpoints() -> None:
    api = _sample_api()
    html = render_report(api, [_sample_exchange("https://example.com/api/items/1")])
    assert "<html" in html.lower()
    assert "/api/items/{id}" in html
    assert "/api/items" in html
    assert "Coverage" in html or "coverage" in html.lower()


def test_save_report_writes_html(tmp_path: Path) -> None:
    api = _sample_api()
    out = tmp_path / "report.html"
    save_report(api, out, [])
    assert out.exists()
    assert "<!doctype html>" in out.read_text().lower()


def test_generate_js_client_emits_functions_for_each_op() -> None:
    api = _sample_api()
    spec = generate_openapi_spec(api)
    code = generate_js_client(spec)

    assert "export function createClient" in code
    assert "export default createClient" in code
    assert "encodeURIComponent(id)" in code
    # Both operations are reachable
    assert "method: 'GET'" in code
    assert "method: 'POST'" in code


def test_save_js_client_writes_mjs(tmp_path: Path) -> None:
    spec = generate_openapi_spec(_sample_api())
    out = tmp_path / "client.mjs"
    save_js_client(generate_js_client(spec), out)
    text = out.read_text()
    assert text.startswith("/**")
    assert "createClient" in text


def test_spec_yaml_roundtrip(tmp_path: Path) -> None:
    spec = generate_openapi_spec(_sample_api())
    out = tmp_path / "spec.yaml"
    save_spec(spec, out)
    loaded = load_spec(out)
    assert loaded["openapi"] == "3.1.0"
    assert "/api/items/{id}" in loaded["paths"]


def test_spec_json_default_format(tmp_path: Path) -> None:
    spec = generate_openapi_spec(_sample_api())
    out = tmp_path / "spec.json"
    save_spec(spec, out)
    loaded = load_spec(out)
    assert loaded == spec


def test_trace_save_and_load_roundtrip(tmp_path: Path) -> None:
    exchanges = [
        _sample_exchange("https://example.com/a"),
        _sample_exchange("https://example.com/b", status=500),
    ]
    out = tmp_path / "trace.json"
    save_trace(exchanges, out, site_url="https://example.com", target_domain="example.com")

    trace = load_trace(out)
    assert trace.site_url == "https://example.com"
    assert trace.target_domain == "example.com"
    assert len(trace.exchanges) == 2
    assert trace.exchanges[1].response.status == 500


def test_trace_load_accepts_bare_list(tmp_path: Path) -> None:
    out = tmp_path / "bare.json"
    ex = _sample_exchange("https://example.com/x")
    out.write_text("[" + ex.model_dump_json() + "]")
    trace = load_trace(out)
    assert len(trace.exchanges) == 1


def test_js_client_handles_no_params() -> None:
    api = DiscoveredAPI(
        site_url="x.com",
        base_url="https://x.com",
        endpoints=[EndpointInfo(method="GET", path_pattern="/ping", description="ping")],
    )
    spec = generate_openapi_spec(api)
    code = generate_js_client(spec)
    assert "async function" in code
    assert "/ping" in code


def test_coverage_with_no_exchanges() -> None:
    api = _sample_api()
    stats = compute_coverage(api, [])
    assert stats.api_requests == 0
    assert stats.gap_candidates == []
