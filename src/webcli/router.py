"""Tier router — picks the best available execution method for a site+action."""

from __future__ import annotations

import asyncio
from datetime import datetime

from webcli.config import get_config
from webcli.models import HealthStatus, SiteAction, SiteEntry, Tier
from webcli.registry import SiteRegistry
from webcli.tiers.browser_explorer import BrowserExplorer
from webcli.tiers.cached_workflow import WorkflowPlayer, load_workflow
from webcli.tiers.direct_api import DirectAPIExecutor


class Router:
    """Routes action execution to the best available tier."""

    def __init__(self, registry: SiteRegistry) -> None:
        self._registry = registry
        self._config = get_config()
        self._browser = BrowserExplorer()
        self._workflow_player = WorkflowPlayer()
        self._direct_api = DirectAPIExecutor()

    async def execute(
        self,
        domain: str,
        action_name: str,
        params: dict,
    ) -> dict:
        """Execute an action using the best available tier.

        Tries tiers in order: API (3) → Workflow (2) → Browser (1).
        Falls back to lower tiers on failure.
        """
        site = self._registry.get_site(domain)
        if not site:
            return await self._fallback_browser(domain, action_name, params)

        action = _find_action(site, action_name)
        if not action:
            return await self._fallback_browser(domain, action_name, params)

        # Try the action's current tier, then fall back
        tiers_to_try = _tier_fallback_order(action.tier)

        for tier in tiers_to_try:
            try:
                result = await self._execute_tier(site, action, tier, params)
                self._registry.record_action_result(domain, action_name, success=True)
                self._maybe_promote(domain, action)
                return result
            except Exception as e:
                self._registry.record_action_result(domain, action_name, success=False)
                continue

        return {"error": f"All tiers failed for {domain}/{action_name}"}

    async def _execute_tier(
        self,
        site: SiteEntry,
        action: SiteAction,
        tier: Tier,
        params: dict,
    ) -> dict:
        """Execute on a specific tier."""
        if tier == Tier.API and action.endpoint:
            return await self._direct_api.execute(site, action.endpoint, params)

        elif tier == Tier.WORKFLOW and action.workflow_id:
            workflow_path = self._config.workflows_dir / f"{action.workflow_id}.json"
            if workflow_path.exists():
                workflow = load_workflow(workflow_path)
                return await self._workflow_player.replay(
                    workflow, params, start_url=site.base_url
                )

        elif tier == Tier.BROWSER:
            return await self._browser.execute_action(
                site.base_url, action.name, params
            )

        raise ValueError(f"Cannot execute on tier {tier}")

    async def _fallback_browser(
        self, domain: str, action_name: str, params: dict
    ) -> dict:
        """Fall back to browser exploration for unknown sites."""
        url = f"https://{domain}"
        goal = f"{action_name}: {params}" if params else action_name
        return await self._browser.execute_action(url, goal, params)

    def _maybe_promote(self, domain: str, action: SiteAction) -> None:
        """Auto-promote action to a higher tier if it's consistently successful."""
        if action.tier == Tier.API:
            return  # Already at highest tier

        # Promote after 5 consecutive successes with 0 recent failures
        if action.success_count >= 5 and action.failure_count == 0:
            if action.tier == Tier.BROWSER:
                new_tier = Tier.WORKFLOW
            else:
                new_tier = Tier.API

            self._registry.update_action_tier(domain, action.name, new_tier)


def _find_action(site: SiteEntry, action_name: str) -> SiteAction | None:
    """Find an action by name in a site entry."""
    for action in site.actions:
        if action.name == action_name:
            return action
    return None


def _tier_fallback_order(starting_tier: Tier) -> list[Tier]:
    """Get the order of tiers to try, starting from the given tier."""
    all_tiers = [Tier.API, Tier.WORKFLOW, Tier.BROWSER]
    idx = all_tiers.index(starting_tier)
    return all_tiers[idx:] + all_tiers[:idx]
