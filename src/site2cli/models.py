"""Pydantic models for site2cli data structures."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class Tier(str, enum.Enum):
    """Execution tier for a site action."""

    BROWSER = "browser"  # Tier 1: LLM-driven browser automation
    WORKFLOW = "workflow"  # Tier 2: Cached/recorded workflow replay
    API = "api"  # Tier 3: Direct API call


class AuthType(str, enum.Enum):
    """Authentication method."""

    NONE = "none"
    COOKIE = "cookie"
    API_KEY = "api_key"
    OAUTH = "oauth"
    SESSION = "session"


class HealthStatus(str, enum.Enum):
    """Health status of a discovered API."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BROKEN = "broken"
    UNKNOWN = "unknown"


# --- Network capture models ---


class CapturedHeader(BaseModel):
    name: str
    value: str


class CapturedRequest(BaseModel):
    """A single captured HTTP request/response pair."""

    method: str
    url: str
    headers: list[CapturedHeader] = Field(default_factory=list)
    body: str | None = None
    content_type: str | None = None
    timestamp: float = 0.0


class CapturedResponse(BaseModel):
    """Captured HTTP response."""

    status: int
    headers: list[CapturedHeader] = Field(default_factory=list)
    body: str | None = None
    content_type: str | None = None


class CapturedExchange(BaseModel):
    """A request-response pair."""

    request: CapturedRequest
    response: CapturedResponse
    duration_ms: float = 0.0


# --- API Discovery models ---


class ParameterInfo(BaseModel):
    """Discovered API parameter."""

    name: str
    location: str = "query"  # query, path, header, body
    param_type: str = "string"
    required: bool = False
    description: str = ""
    example: str | None = None


class EndpointInfo(BaseModel):
    """A discovered API endpoint."""

    method: str
    path_pattern: str  # e.g., /api/search/{query}
    parameters: list[ParameterInfo] = Field(default_factory=list)
    description: str = ""
    request_content_type: str | None = None
    response_content_type: str | None = None
    request_schema: dict | None = None
    response_schema: dict | None = None
    example_request: dict | None = None
    example_response: dict | list | None = None
    auth_required: bool = False


class DiscoveredAPI(BaseModel):
    """Complete discovered API for a site."""

    site_url: str
    base_url: str
    endpoints: list[EndpointInfo] = Field(default_factory=list)
    auth_type: AuthType = AuthType.NONE
    description: str = ""
    openapi_spec: dict | None = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)


# --- Site Registry models ---


class SiteAction(BaseModel):
    """A specific action available on a site."""

    name: str  # e.g., "search_flights"
    description: str = ""
    tier: Tier = Tier.BROWSER
    endpoint: EndpointInfo | None = None
    workflow_id: str | None = None  # Reference to cached workflow
    success_count: int = 0
    failure_count: int = 0
    last_used: datetime | None = None
    last_checked: datetime | None = None
    health: HealthStatus = HealthStatus.UNKNOWN


class SiteEntry(BaseModel):
    """Registry entry for a discovered site."""

    domain: str
    base_url: str
    description: str = ""
    actions: list[SiteAction] = Field(default_factory=list)
    auth_type: AuthType = AuthType.NONE
    openapi_spec_path: str | None = None
    client_module_path: str | None = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    health: HealthStatus = HealthStatus.UNKNOWN


# --- Workflow models ---


class WorkflowStep(BaseModel):
    """A single step in a recorded workflow."""

    action: str  # click, fill, navigate, wait, extract
    selector: str | None = None
    value: str | None = None
    url: str | None = None
    description: str = ""
    parameterized: bool = False  # If True, value is a template like "{departure_city}"


class RecordedWorkflow(BaseModel):
    """A recorded browser workflow that can be replayed."""

    id: str
    site_domain: str
    action_name: str
    steps: list[WorkflowStep] = Field(default_factory=list)
    parameters: list[ParameterInfo] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    replay_count: int = 0
    success_count: int = 0


# --- MCP Tool models ---


class MCPToolSchema(BaseModel):
    """Schema for a generated MCP tool."""

    name: str
    description: str
    input_schema: dict
    site_domain: str
    action_name: str
    tier: Tier
