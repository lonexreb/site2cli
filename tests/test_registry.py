"""Tests for the SQLite site registry."""


import pytest

from site2cli.models import (
    AuthType,
    EndpointInfo,
    HealthStatus,
    ParameterInfo,
    SiteAction,
    SiteEntry,
    Tier,
)
from site2cli.registry import SiteRegistry


@pytest.fixture
def registry(tmp_path):
    db_path = tmp_path / "test_registry.db"
    reg = SiteRegistry(db_path)
    yield reg
    reg.close()


@pytest.fixture
def sample_site():
    return SiteEntry(
        domain="example.com",
        base_url="https://api.example.com",
        description="Test site",
        auth_type=AuthType.API_KEY,
        actions=[
            SiteAction(
                name="search",
                description="Search items",
                tier=Tier.API,
                endpoint=EndpointInfo(
                    method="GET",
                    path_pattern="/api/search",
                    parameters=[
                        ParameterInfo(name="q", location="query", required=True),
                    ],
                ),
            ),
            SiteAction(
                name="get_item",
                description="Get item by ID",
                tier=Tier.API,
            ),
        ],
    )


def test_add_and_get_site(registry, sample_site):
    registry.add_site(sample_site)
    retrieved = registry.get_site("example.com")

    assert retrieved is not None
    assert retrieved.domain == "example.com"
    assert retrieved.base_url == "https://api.example.com"
    assert retrieved.auth_type == AuthType.API_KEY
    assert len(retrieved.actions) == 2


def test_get_nonexistent_site(registry):
    assert registry.get_site("nonexistent.com") is None


def test_list_sites(registry, sample_site):
    registry.add_site(sample_site)

    other = SiteEntry(domain="other.com", base_url="https://other.com")
    registry.add_site(other)

    sites = registry.list_sites()
    assert len(sites) == 2
    domains = {s.domain for s in sites}
    assert domains == {"example.com", "other.com"}


def test_remove_site(registry, sample_site):
    registry.add_site(sample_site)
    assert registry.remove_site("example.com")
    assert registry.get_site("example.com") is None


def test_remove_nonexistent(registry):
    assert not registry.remove_site("nonexistent.com")


def test_update_action_tier(registry, sample_site):
    registry.add_site(sample_site)
    registry.update_action_tier("example.com", "search", Tier.WORKFLOW)

    site = registry.get_site("example.com")
    search = [a for a in site.actions if a.name == "search"][0]
    assert search.tier == Tier.WORKFLOW


def test_record_action_result(registry, sample_site):
    registry.add_site(sample_site)

    registry.record_action_result("example.com", "search", success=True)
    registry.record_action_result("example.com", "search", success=True)
    registry.record_action_result("example.com", "search", success=False)

    site = registry.get_site("example.com")
    search = [a for a in site.actions if a.name == "search"][0]
    assert search.success_count == 2
    assert search.failure_count == 1
    assert search.last_used is not None


def test_update_health(registry, sample_site):
    registry.add_site(sample_site)
    registry.update_health("example.com", "search", HealthStatus.HEALTHY)

    site = registry.get_site("example.com")
    search = [a for a in site.actions if a.name == "search"][0]
    assert search.health == HealthStatus.HEALTHY
    assert search.last_checked is not None


def test_upsert_site(registry, sample_site):
    registry.add_site(sample_site)
    sample_site.description = "Updated description"
    registry.add_site(sample_site)

    site = registry.get_site("example.com")
    assert site.description == "Updated description"


def test_action_with_endpoint(registry, sample_site):
    registry.add_site(sample_site)

    site = registry.get_site("example.com")
    search = [a for a in site.actions if a.name == "search"][0]
    assert search.endpoint is not None
    assert search.endpoint.method == "GET"
    assert search.endpoint.path_pattern == "/api/search"
    assert len(search.endpoint.parameters) == 1
