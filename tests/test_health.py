"""Tests for the HealthMonitor."""

from __future__ import annotations

import httpx
import pytest

from site2cli.health.monitor import HealthMonitor
from site2cli.models import (
    AuthType,
    EndpointInfo,
    HealthStatus,
    SiteAction,
    SiteEntry,
    Tier,
)
from site2cli.registry import SiteRegistry

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class MockAsyncClient:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def head(self, url, **kwargs):
        return MockResponse(self.status_code)

    async def options(self, url, **kwargs):
        return MockResponse(self.status_code)


class MockAsyncClientTimeout:
    """Always raises TimeoutException on any request method."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def head(self, url, **kwargs):
        raise httpx.TimeoutException("timed out")

    async def options(self, url, **kwargs):
        raise httpx.TimeoutException("timed out")


class MockAsyncClientConnectionError:
    """Always raises a generic Exception on any request method."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def head(self, url, **kwargs):
        raise Exception("connection refused")

    async def options(self, url, **kwargs):
        raise Exception("connection refused")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path):
    db_path = tmp_path / "health_test.db"
    reg = SiteRegistry(db_path)
    yield reg
    reg.close()


@pytest.fixture
def monitor(registry):
    return HealthMonitor(registry)


@pytest.fixture
def site_with_get_endpoint():
    return SiteEntry(
        domain="api.example.com",
        base_url="https://api.example.com",
        description="Example API",
        auth_type=AuthType.NONE,
        actions=[
            SiteAction(
                name="list_items",
                description="List items",
                tier=Tier.API,
                endpoint=EndpointInfo(
                    method="GET",
                    path_pattern="/items",
                ),
            ),
        ],
    )


@pytest.fixture
def site_with_post_endpoint():
    return SiteEntry(
        domain="api.example.com",
        base_url="https://api.example.com",
        description="Example API",
        auth_type=AuthType.NONE,
        actions=[
            SiteAction(
                name="create_item",
                description="Create an item",
                tier=Tier.API,
                endpoint=EndpointInfo(
                    method="POST",
                    path_pattern="/items",
                ),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_check_site_nonexistent_domain(monitor):
    """check_site returns an empty dict when the domain is not registered."""
    result = await monitor.check_site("notregistered.com")
    assert result == {}


async def test_check_endpoint_healthy_for_2xx(
    registry, monitor, site_with_get_endpoint, monkeypatch,
):
    """_check_endpoint returns HEALTHY when the response status code is < 400."""
    registry.add_site(site_with_get_endpoint)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockAsyncClient(status_code=200))

    result = await monitor.check_site("api.example.com")
    assert result["list_items"] == HealthStatus.HEALTHY


async def test_check_endpoint_degraded_for_4xx(
    registry, monitor, site_with_get_endpoint, monkeypatch,
):
    """_check_endpoint returns DEGRADED when status code is in the 400-499 range."""
    registry.add_site(site_with_get_endpoint)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockAsyncClient(status_code=404))

    result = await monitor.check_site("api.example.com")
    assert result["list_items"] == HealthStatus.DEGRADED


async def test_check_endpoint_broken_for_5xx(
    registry, monitor, site_with_get_endpoint, monkeypatch,
):
    """_check_endpoint returns BROKEN when the response status code is >= 500."""
    registry.add_site(site_with_get_endpoint)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockAsyncClient(status_code=503))

    result = await monitor.check_site("api.example.com")
    assert result["list_items"] == HealthStatus.BROKEN


async def test_check_endpoint_degraded_on_timeout(
    registry, monitor, site_with_get_endpoint, monkeypatch,
):
    """_check_endpoint returns DEGRADED when an httpx.TimeoutException is raised."""
    registry.add_site(site_with_get_endpoint)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockAsyncClientTimeout())

    result = await monitor.check_site("api.example.com")
    assert result["list_items"] == HealthStatus.DEGRADED


async def test_check_endpoint_broken_on_connection_error(
    registry, monitor, site_with_get_endpoint, monkeypatch,
):
    """_check_endpoint returns BROKEN when a generic exception (e.g. connection error) is raised."""
    registry.add_site(site_with_get_endpoint)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockAsyncClientConnectionError())

    result = await monitor.check_site("api.example.com")
    assert result["list_items"] == HealthStatus.BROKEN


async def test_check_site_updates_health_in_registry(
    registry, monitor, site_with_get_endpoint, monkeypatch,
):
    """check_site persists the computed health status back into the registry."""
    registry.add_site(site_with_get_endpoint)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockAsyncClient(status_code=200))

    await monitor.check_site("api.example.com")

    retrieved = registry.get_site("api.example.com")
    action = next(a for a in retrieved.actions if a.name == "list_items")
    assert action.health == HealthStatus.HEALTHY
    assert action.last_checked is not None


async def test_action_without_endpoint_gets_unknown_status(registry, monitor):
    """An action that has no endpoint defined receives UNKNOWN health status."""
    site = SiteEntry(
        domain="browser.example.com",
        base_url="https://browser.example.com",
        description="Browser-only site",
        auth_type=AuthType.NONE,
        actions=[
            SiteAction(
                name="do_something",
                description="A browser action with no known endpoint",
                tier=Tier.BROWSER,
                endpoint=None,
            ),
        ],
    )
    registry.add_site(site)

    result = await monitor.check_site("browser.example.com")
    assert result["do_something"] == HealthStatus.UNKNOWN
