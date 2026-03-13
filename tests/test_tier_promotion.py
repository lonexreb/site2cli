"""Test tier promotion and router fallback logic.

Verification test #6 from PLAN.md:
  Verify auto-promotion from Tier 1 → 3
"""

import pytest

from site2cli.models import (
    EndpointInfo,
    ParameterInfo,
    SiteAction,
    SiteEntry,
    Tier,
)
from site2cli.registry import SiteRegistry
from site2cli.router import Router, _find_action, _tier_fallback_order


class TestTierFallbackOrder:
    def test_fallback_from_api(self):
        order = _tier_fallback_order(Tier.API)
        assert order == [Tier.API, Tier.WORKFLOW, Tier.BROWSER]

    def test_fallback_from_workflow(self):
        order = _tier_fallback_order(Tier.WORKFLOW)
        assert order == [Tier.WORKFLOW, Tier.BROWSER, Tier.API]

    def test_fallback_from_browser(self):
        order = _tier_fallback_order(Tier.BROWSER)
        assert order == [Tier.BROWSER, Tier.API, Tier.WORKFLOW]


class TestFindAction:
    def test_find_existing(self):
        site = SiteEntry(
            domain="test.com",
            base_url="https://test.com",
            actions=[
                SiteAction(name="search", tier=Tier.API),
                SiteAction(name="create", tier=Tier.BROWSER),
            ],
        )
        action = _find_action(site, "search")
        assert action is not None
        assert action.name == "search"

    def test_find_missing(self):
        site = SiteEntry(
            domain="test.com",
            base_url="https://test.com",
            actions=[SiteAction(name="search", tier=Tier.API)],
        )
        assert _find_action(site, "nonexistent") is None


class TestTierPromotion:
    """Test that actions auto-promote after consistent success."""

    @pytest.fixture
    def registry(self, tmp_path):
        reg = SiteRegistry(tmp_path / "test.db")
        yield reg
        reg.close()

    @pytest.fixture
    def site_with_browser_action(self, registry):
        site = SiteEntry(
            domain="example.com",
            base_url="https://example.com",
            actions=[
                SiteAction(
                    name="search",
                    tier=Tier.BROWSER,
                    endpoint=EndpointInfo(
                        method="GET",
                        path_pattern="/api/search",
                        parameters=[ParameterInfo(name="q", location="query", required=True)],
                    ),
                ),
            ],
        )
        registry.add_site(site)
        return site

    def test_no_promotion_without_enough_successes(self, registry, site_with_browser_action):
        """Action should NOT promote with fewer than 5 successes."""
        router = Router(registry)

        # Record 4 successes (not enough)
        for _ in range(4):
            registry.record_action_result("example.com", "search", success=True)

        # Manually call promotion check
        site = registry.get_site("example.com")
        action = _find_action(site, "search")
        router._maybe_promote("example.com", action)

        # Should still be BROWSER
        site = registry.get_site("example.com")
        action = _find_action(site, "search")
        assert action.tier == Tier.BROWSER

    def test_promotion_after_5_successes(self, registry, site_with_browser_action):
        """Action SHOULD promote after 5 consecutive successes."""
        router = Router(registry)

        # Record 5 successes
        for _ in range(5):
            registry.record_action_result("example.com", "search", success=True)

        # Check promotion
        site = registry.get_site("example.com")
        action = _find_action(site, "search")
        router._maybe_promote("example.com", action)

        # Should be promoted to WORKFLOW
        site = registry.get_site("example.com")
        action = _find_action(site, "search")
        assert action.tier == Tier.WORKFLOW

    def test_no_promotion_with_failures(self, registry, site_with_browser_action):
        """Action should NOT promote if there are failures."""
        router = Router(registry)

        # Record successes + a failure
        for _ in range(5):
            registry.record_action_result("example.com", "search", success=True)
        registry.record_action_result("example.com", "search", success=False)

        site = registry.get_site("example.com")
        action = _find_action(site, "search")
        router._maybe_promote("example.com", action)

        # Should stay at BROWSER (failure_count > 0)
        site = registry.get_site("example.com")
        action = _find_action(site, "search")
        assert action.tier == Tier.BROWSER

    def test_api_tier_does_not_promote(self, registry):
        """Actions already at API tier should not promote further."""
        site = SiteEntry(
            domain="test.com",
            base_url="https://test.com",
            actions=[SiteAction(name="get", tier=Tier.API, success_count=100)],
        )
        registry.add_site(site)
        router = Router(registry)

        site = registry.get_site("test.com")
        action = _find_action(site, "get")
        router._maybe_promote("test.com", action)

        site = registry.get_site("test.com")
        action = _find_action(site, "get")
        assert action.tier == Tier.API
