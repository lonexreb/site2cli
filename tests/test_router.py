"""Tests for Router.execute() behavior.

Covers the main execution paths in the Router class:
  - Unknown domain/action fallback to browser
  - Tier selection and fallback on failure
  - Success/failure recording
  - Param passing
  - _maybe_promote integration

Note: _find_action, _tier_fallback_order, and _maybe_promote unit tests
live in test_tier_promotion.py. This file focuses on Router.execute().
"""

from __future__ import annotations

import pytest

from site2cli.models import EndpointInfo, SiteAction, SiteEntry, Tier
from site2cli.registry import SiteRegistry
from site2cli.router import Router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path):
    reg = SiteRegistry(tmp_path / "test.db")
    yield reg
    reg.close()


def _make_api_site(domain: str = "api.example.com") -> SiteEntry:
    return SiteEntry(
        domain=domain,
        base_url=f"https://{domain}",
        actions=[
            SiteAction(
                name="get_data",
                tier=Tier.API,
                endpoint=EndpointInfo(method="GET", path_pattern="/data"),
            )
        ],
    )


def _make_workflow_site(
    domain: str = "workflow.example.com", workflow_id: str = "wf-001",
) -> SiteEntry:
    return SiteEntry(
        domain=domain,
        base_url=f"https://{domain}",
        actions=[
            SiteAction(
                name="do_thing",
                tier=Tier.WORKFLOW,
                workflow_id=workflow_id,
            )
        ],
    )


def _make_browser_site(domain: str = "browser.example.com") -> SiteEntry:
    return SiteEntry(
        domain=domain,
        base_url=f"https://{domain}",
        actions=[
            SiteAction(name="browse_action", tier=Tier.BROWSER)
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExecuteUnknownDomain:
    """execute() should fall back to browser for unregistered domains."""

    @pytest.mark.asyncio
    async def test_unknown_domain_calls_fallback_browser(self, registry):
        router = Router(registry)
        expected = {"result": "explored", "steps_taken": 0, "history": []}

        async def mock_execute_action(url, action, params):
            return expected

        router._browser.execute_action = mock_execute_action

        result = await router.execute("unknown.example.com", "search", {"q": "test"})
        assert result == expected

    @pytest.mark.asyncio
    async def test_fallback_browser_receives_correct_url(self, registry):
        router = Router(registry)
        received_url = {}

        async def mock_execute_action(url, action, params):
            received_url["url"] = url
            return {"ok": True}

        router._browser.execute_action = mock_execute_action

        await router.execute("mysite.io", "find", {})
        assert received_url["url"] == "https://mysite.io"


class TestExecuteUnknownAction:
    """execute() should fall back to browser when action is not registered."""

    @pytest.mark.asyncio
    async def test_unknown_action_calls_fallback_browser(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)
        expected = {"fallback": True}

        async def mock_execute_action(url, action, params):
            return expected

        router._browser.execute_action = mock_execute_action

        result = await router.execute("api.example.com", "nonexistent_action", {})
        assert result == expected


class TestExecuteAPITier:
    """execute() should route to DirectAPIExecutor for API-tier actions."""

    @pytest.mark.asyncio
    async def test_api_tier_calls_direct_api_executor(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)
        api_result = {"data": "api_result"}

        async def mock_api_execute(site_entry, endpoint, params):
            return api_result

        router._direct_api.execute = mock_api_execute

        result = await router.execute("api.example.com", "get_data", {"key": "val"})
        assert result == api_result

    @pytest.mark.asyncio
    async def test_api_tier_passes_params_to_executor(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)
        captured = {}

        async def mock_api_execute(site_entry, endpoint, params):
            captured["params"] = params
            return {"ok": True}

        router._direct_api.execute = mock_api_execute

        await router.execute("api.example.com", "get_data", {"x": 1, "y": 2})
        assert captured["params"] == {"x": 1, "y": 2}


class TestExecuteWorkflowTier:
    """execute() should route to WorkflowPlayer for WORKFLOW-tier actions."""

    @pytest.mark.asyncio
    async def test_workflow_tier_calls_workflow_player(self, registry, tmp_path):
        # WorkflowPlayer.replay is only called if the workflow file exists on disk.
        # We bypass _execute_tier entirely by mocking it at the router level.
        site = _make_workflow_site()
        registry.add_site(site)
        router = Router(registry)
        workflow_result = {"steps_executed": 3, "steps_total": 3}

        async def mock_execute_tier(site_entry, action, tier, params):
            if tier == Tier.WORKFLOW:
                return workflow_result
            raise ValueError("unexpected tier")

        router._execute_tier = mock_execute_tier

        result = await router.execute("workflow.example.com", "do_thing", {})
        assert result == workflow_result

    @pytest.mark.asyncio
    async def test_workflow_tier_passes_params(self, registry):
        site = _make_workflow_site()
        registry.add_site(site)
        router = Router(registry)
        captured = {}

        async def mock_execute_tier(site_entry, action, tier, params):
            captured["params"] = params
            return {"ok": True}

        router._execute_tier = mock_execute_tier

        await router.execute("workflow.example.com", "do_thing", {"a": "b"})
        assert captured["params"] == {"a": "b"}


class TestExecuteBrowserTier:
    """execute() should route to BrowserExplorer for BROWSER-tier actions."""

    @pytest.mark.asyncio
    async def test_browser_tier_calls_browser_explorer(self, registry):
        site = _make_browser_site()
        registry.add_site(site)
        router = Router(registry)
        browser_result = {"result": {}, "steps_taken": 1, "history": []}

        async def mock_execute_action(url, action, params):
            return browser_result

        router._browser.execute_action = mock_execute_action

        result = await router.execute("browser.example.com", "browse_action", {})
        assert result == browser_result


class TestFallbackOnException:
    """execute() should fall back to lower tiers when a tier raises."""

    @pytest.mark.asyncio
    async def test_api_failure_falls_back_to_lower_tier(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)
        fallback_result = {"data": "from_browser"}
        call_order = []

        async def mock_execute_tier(site_entry, action, tier, params):
            call_order.append(tier)
            if tier == Tier.API:
                raise RuntimeError("API is down")
            return fallback_result

        router._execute_tier = mock_execute_tier

        result = await router.execute("api.example.com", "get_data", {})
        assert result == fallback_result
        assert Tier.API in call_order
        # A lower tier was tried after API failed
        assert len(call_order) > 1

    @pytest.mark.asyncio
    async def test_all_tiers_fail_returns_error_dict(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)

        async def mock_execute_tier(site_entry, action, tier, params):
            raise RuntimeError(f"{tier} failed")

        router._execute_tier = mock_execute_tier

        result = await router.execute("api.example.com", "get_data", {})
        assert "error" in result
        assert "api.example.com" in result["error"]
        assert "get_data" in result["error"]


class TestSuccessAndFailureRecording:
    """execute() should record success/failure counts via registry."""

    @pytest.mark.asyncio
    async def test_records_success_on_successful_execution(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)

        async def mock_execute_tier(site_entry, action, tier, params):
            return {"ok": True}

        router._execute_tier = mock_execute_tier

        await router.execute("api.example.com", "get_data", {})

        refreshed = registry.get_site("api.example.com")
        action = next(a for a in refreshed.actions if a.name == "get_data")
        assert action.success_count == 1
        assert action.failure_count == 0

    @pytest.mark.asyncio
    async def test_records_failure_when_tier_raises(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)

        call_count = {"n": 0}

        async def mock_execute_tier(site_entry, action, tier, params):
            call_count["n"] += 1
            raise RuntimeError("always fails")

        router._execute_tier = mock_execute_tier

        await router.execute("api.example.com", "get_data", {})

        refreshed = registry.get_site("api.example.com")
        action = next(a for a in refreshed.actions if a.name == "get_data")
        # One failure recorded per tier attempt; at least one attempt was made
        assert action.failure_count >= 1
        assert action.success_count == 0


class TestEmptyParams:
    """execute() should handle an empty params dict without error."""

    @pytest.mark.asyncio
    async def test_execute_with_empty_params(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)

        async def mock_execute_tier(site_entry, action, tier, params):
            assert params == {}
            return {"result": "empty_params_ok"}

        router._execute_tier = mock_execute_tier

        result = await router.execute("api.example.com", "get_data", {})
        assert result == {"result": "empty_params_ok"}


class TestMaybePromoteOnSuccess:
    """execute() should call _maybe_promote after a successful execution."""

    @pytest.mark.asyncio
    async def test_maybe_promote_called_on_success(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)
        promote_calls = []

        original_promote = router._maybe_promote

        def capturing_promote(domain, action):
            promote_calls.append((domain, action.name))
            return original_promote(domain, action)

        router._maybe_promote = capturing_promote

        async def mock_execute_tier(site_entry, action, tier, params):
            return {"ok": True}

        router._execute_tier = mock_execute_tier

        await router.execute("api.example.com", "get_data", {})

        assert len(promote_calls) == 1
        assert promote_calls[0] == ("api.example.com", "get_data")

    @pytest.mark.asyncio
    async def test_maybe_promote_not_called_on_all_tiers_failing(self, registry):
        site = _make_api_site()
        registry.add_site(site)
        router = Router(registry)
        promote_calls = []

        def capturing_promote(domain, action):
            promote_calls.append(domain)

        router._maybe_promote = capturing_promote

        async def mock_execute_tier(site_entry, action, tier, params):
            raise RuntimeError("fail")

        router._execute_tier = mock_execute_tier

        await router.execute("api.example.com", "get_data", {})

        assert promote_calls == []
