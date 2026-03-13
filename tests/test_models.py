"""Tests for Pydantic models."""

from site2cli.models import (
    AuthType,
    CapturedExchange,
    CapturedRequest,
    CapturedResponse,
    EndpointInfo,
    MCPToolSchema,
    ParameterInfo,
    RecordedWorkflow,
    SiteAction,
    SiteEntry,
    Tier,
    WorkflowStep,
)


def test_captured_exchange():
    req = CapturedRequest(method="GET", url="https://api.example.com/users")
    resp = CapturedResponse(status=200, body='{"users": []}')
    exchange = CapturedExchange(request=req, response=resp, duration_ms=100)

    assert exchange.request.method == "GET"
    assert exchange.response.status == 200
    assert exchange.duration_ms == 100


def test_endpoint_info():
    param = ParameterInfo(name="q", location="query", param_type="string", required=True)
    endpoint = EndpointInfo(
        method="GET",
        path_pattern="/api/search",
        parameters=[param],
        description="Search endpoint",
    )

    assert endpoint.method == "GET"
    assert len(endpoint.parameters) == 1
    assert endpoint.parameters[0].name == "q"


def test_site_entry():
    action = SiteAction(
        name="search",
        description="Search for items",
        tier=Tier.API,
    )
    site = SiteEntry(
        domain="example.com",
        base_url="https://api.example.com",
        actions=[action],
    )

    assert site.domain == "example.com"
    assert len(site.actions) == 1
    assert site.actions[0].tier == Tier.API


def test_workflow():
    steps = [
        WorkflowStep(action="navigate", url="https://example.com"),
        WorkflowStep(action="fill", selector="#search", value="{query}", parameterized=True),
        WorkflowStep(action="click", selector="#submit"),
    ]
    workflow = RecordedWorkflow(
        id="test-123",
        site_domain="example.com",
        action_name="search",
        steps=steps,
        parameters=[ParameterInfo(name="query", param_type="string", required=True)],
    )

    assert len(workflow.steps) == 3
    assert workflow.steps[1].parameterized is True


def test_mcp_tool_schema():
    tool = MCPToolSchema(
        name="example_search",
        description="Search example.com",
        input_schema={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
        site_domain="example.com",
        action_name="search",
        tier=Tier.API,
    )

    assert tool.name == "example_search"
    assert "q" in tool.input_schema["properties"]


def test_tier_enum():
    assert Tier.BROWSER.value == "browser"
    assert Tier.WORKFLOW.value == "workflow"
    assert Tier.API.value == "api"


def test_auth_type_enum():
    assert AuthType.NONE.value == "none"
    assert AuthType.OAUTH.value == "oauth"


def test_serialization_roundtrip():
    site = SiteEntry(
        domain="test.com",
        base_url="https://test.com",
        actions=[
            SiteAction(name="get_data", tier=Tier.API),
        ],
    )
    json_str = site.model_dump_json()
    restored = SiteEntry.model_validate_json(json_str)
    assert restored.domain == site.domain
    assert restored.actions[0].name == "get_data"


# --- Additional model tests ---


def test_health_status_enum():
    from site2cli.models import HealthStatus
    assert HealthStatus.HEALTHY.value == "healthy"
    assert HealthStatus.DEGRADED.value == "degraded"
    assert HealthStatus.BROKEN.value == "broken"
    assert HealthStatus.UNKNOWN.value == "unknown"


def test_recorded_workflow_serialization():
    workflow = RecordedWorkflow(
        id="wf-1",
        site_domain="example.com",
        action_name="search",
        steps=[
            WorkflowStep(action="navigate", url="https://example.com"),
            WorkflowStep(action="click", selector="#btn"),
        ],
        parameters=[ParameterInfo(name="q", required=True)],
    )
    json_str = workflow.model_dump_json()
    restored = RecordedWorkflow.model_validate_json(json_str)
    assert restored.id == "wf-1"
    assert len(restored.steps) == 2
    assert len(restored.parameters) == 1


def test_captured_exchange_with_empty_bodies():
    req = CapturedRequest(method="GET", url="https://example.com/api")
    resp = CapturedResponse(status=204, body=None, content_type=None)
    exchange = CapturedExchange(request=req, response=resp)
    assert exchange.request.body is None
    assert exchange.response.body is None
    assert exchange.duration_ms == 0.0


def test_parameter_info_defaults():
    param = ParameterInfo(name="test_param")
    assert param.location == "query"
    assert param.param_type == "string"
    assert param.required is False
    assert param.description == ""
    assert param.example is None


def test_site_action_defaults():
    action = SiteAction(name="test_action")
    assert action.tier == Tier.BROWSER
    assert action.success_count == 0
    assert action.failure_count == 0
    assert action.last_used is None
    assert action.endpoint is None
    assert action.workflow_id is None


def test_discovered_api_defaults():
    from site2cli.models import DiscoveredAPI
    api = DiscoveredAPI(site_url="test.com", base_url="https://test.com")
    assert api.auth_type == AuthType.NONE
    assert api.endpoints == []
    assert api.description == ""
    assert api.discovered_at is not None


def test_captured_header():
    from site2cli.models import CapturedHeader
    h = CapturedHeader(name="Content-Type", value="application/json")
    assert h.name == "Content-Type"
    assert h.value == "application/json"
