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


# --- OAuth models ---


class OAuthProviderConfig(BaseModel):
    """Configuration for an OAuth device flow provider."""

    name: str  # e.g., "github", "google", "custom"
    client_id: str
    device_authorization_endpoint: str
    token_endpoint: str
    scopes: list[str] = Field(default_factory=list)
    audience: str | None = None


class OAuthTokenData(BaseModel):
    """Stored OAuth token data with expiry tracking."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: float | None = None  # Unix timestamp
    scope: str | None = None
    provider_name: str = ""


class DeviceCodeResponse(BaseModel):
    """Response from device authorization endpoint (RFC 8628 Section 3.2)."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None = None
    expires_in: int = 900
    interval: int = 5


# --- Orchestration models ---


class DataMapping(BaseModel):
    """Maps output from a previous step to input of the next step."""

    source_path: str  # e.g., "$result.data[0].id" or "$steps.step1.result.price"
    target_param: str  # Parameter name in the next step


class OrchestrationStep(BaseModel):
    """A single step in a multi-site orchestration pipeline."""

    step_id: str
    domain: str
    action: str
    params: dict = Field(default_factory=dict)
    data_mappings: list[DataMapping] = Field(default_factory=list)
    description: str = ""
    on_error: str = "fail"  # "fail", "skip", "retry"
    retries: int = 0
    condition: str | None = None


class OrchestrationPipeline(BaseModel):
    """A complete multi-site orchestration definition."""

    id: str
    name: str
    description: str = ""
    steps: list[OrchestrationStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    run_count: int = 0
    last_run: datetime | None = None


class StepResult(BaseModel):
    """Result of executing a single orchestration step."""

    step_id: str
    domain: str
    action: str
    success: bool
    result: dict = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0


class OrchestrationResult(BaseModel):
    """Result of executing a complete orchestration pipeline."""

    pipeline_id: str
    pipeline_name: str
    success: bool
    step_results: list[StepResult] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    started_at: datetime = Field(default_factory=datetime.utcnow)


# --- Crawl models ---


class CrawlStatus(str, enum.Enum):
    """Status of a crawl job."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class CrawlPage(BaseModel):
    """A single crawled page."""

    url: str
    depth: int = 0
    status_code: int = 0
    content_type: str = ""
    title: str = ""
    content: str = ""
    content_hash: str = ""
    links_found: int = 0
    crawled_at: datetime = Field(default_factory=datetime.utcnow)
    error: str | None = None


class CrawlJob(BaseModel):
    """State of a crawl session, persisted for resume."""

    id: str
    start_url: str
    domain: str
    max_depth: int = 3
    max_pages: int = 100
    status: CrawlStatus = CrawlStatus.PENDING
    pages_crawled: int = 0
    pages_total: int = 0
    output_format: str = "markdown"
    main_content_only: bool = True
    respect_robots: bool = True
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    error: str | None = None


# --- Monitor models ---


class MonitorWatch(BaseModel):
    """A monitored URL configuration."""

    id: str
    url: str
    interval_seconds: int = 3600
    webhook_url: str | None = None
    output_format: str = "diff"
    main_content_only: bool = True
    active: bool = True
    last_checked: datetime | None = None
    last_changed: datetime | None = None
    check_count: int = 0
    change_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MonitorSnapshot(BaseModel):
    """A point-in-time snapshot of a URL's content."""

    id: str
    watch_id: str
    url: str
    content_hash: str
    content_text: str = ""
    status_code: int = 0
    captured_at: datetime = Field(default_factory=datetime.utcnow)


class DiffLine(BaseModel):
    """A single line of diff output."""

    operation: str  # "add", "remove", "unchanged"
    line_number: int = 0
    content: str = ""


class MonitorDiff(BaseModel):
    """Diff result between two snapshots."""

    watch_id: str
    url: str
    changed: bool
    old_snapshot_id: str | None = None
    new_snapshot_id: str | None = None
    added_lines: int = 0
    removed_lines: int = 0
    diff_lines: list[DiffLine] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.utcnow)


# --- Screenshot models ---


class ScreenshotResult(BaseModel):
    """Result of a screenshot capture."""

    url: str
    path: str
    width: int = 0
    height: int = 0
    format: str = "png"
    full_page: bool = True
    selector: str | None = None
    captured_at: datetime = Field(default_factory=datetime.utcnow)
