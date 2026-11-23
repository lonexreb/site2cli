"""Tier router — picks the best available execution method for a site+action."""

from __future__ import annotations

import re

from site2cli.browser.session import SessionError
from site2cli.config import get_config
from site2cli.models import SiteAction, SiteEntry, Tier
from site2cli.outcome import (
    REJECTED,
    SAFE_METHODS,
    Outcome,
    TierUnavailableError,
    failure,
    outcome_of,
)
from site2cli.registry import SiteRegistry
from site2cli.tiers.browser_explorer import BrowserExplorer
from site2cli.tiers.cached_workflow import WorkflowPlayer, load_workflow
from site2cli.tiers.direct_api import DirectAPIExecutor


class Router:
    """Routes action execution to the best available tier."""

    def __init__(self, registry: SiteRegistry) -> None:
        self._registry = registry
        self._config = get_config()
        self._browser = BrowserExplorer(registry=registry)
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
            # A known site with an unknown action is a user error: fail fast
            # with the valid names instead of silently launching a browser.
            return {
                "error": f"Unknown action '{action_name}' for {domain}",
                "available_actions": [a.name for a in site.actions],
            }

        # Try the action's current tier, then fall back
        last: dict | None = None
        for tier in _tier_fallback_order(action.tier):
            try:
                result = await self._execute_tier(site, action, tier, params)
            except (TierUnavailableError, ImportError):
                # ImportError: an optional dependency (e.g. Playwright) is absent.
                continue  # Nothing was dispatched; not a failure of the action.
            except SessionError as exc:
                # Raised while acquiring the browser, before any page action.
                # Do not continue on another tier outside the chosen session.
                return failure(Outcome.FAILED, str(exc), dispatched=False)
            except Exception as exc:
                # The tier started work, so completion cannot be established.
                result = failure(
                    Outcome.UNKNOWN,
                    f"{domain}/{action.name}: {tier.name} tier raised "
                    f"{type(exc).__name__}: {exc}",
                    requires_review=True,
                )

            outcome = outcome_of(result)
            if outcome is Outcome.SUCCESS:
                self._registry.record_action_result(domain, action.name, success=True)
                self._maybe_promote(domain, action)
                return result

            self._registry.record_action_result(domain, action.name, success=False)
            last = _as_failure(result, outcome, tier)
            if not _may_try_next_tier(action, tier, outcome, last):
                return last

        return last or failure(
            Outcome.FAILED, f"All tiers failed for {domain}/{action_name}"
        )

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
                try:
                    workflow = load_workflow(workflow_path)
                except Exception as exc:
                    raise TierUnavailableError(f"Unreadable workflow: {exc}") from exc
                return await self._workflow_player.replay(
                    workflow, params, start_url=site.base_url
                )

        elif tier == Tier.BROWSER:
            return await self._browser.execute_action(
                site.base_url, action.name, params
            )

        raise TierUnavailableError(f"Cannot execute on tier {tier}")

    async def _fallback_browser(
        self, domain: str, action_name: str, params: dict
    ) -> dict:
        """Fall back to browser exploration for unknown sites."""
        url = f"https://{domain}"
        goal = f"{action_name}: {params}" if params else action_name
        result = await self._browser.execute_action(url, goal, params)
        return _as_failure(result, outcome_of(result), Tier.BROWSER)

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


def _normalize_action_name(name: str) -> str:
    """Normalize an action name for tolerant matching."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _find_action(site: SiteEntry, action_name: str) -> SiteAction | None:
    """Find an action by name in a site entry.

    Matches exactly first, then falls back to normalized comparison so
    operationId-style names (``get_api_products``) resolve against legacy
    registry entries (``GET_/api/products``) and vice versa.
    """
    for action in site.actions:
        if action.name == action_name:
            return action
    wanted = _normalize_action_name(action_name)
    matches = [a for a in site.actions if _normalize_action_name(a.name) == wanted]
    if len(matches) == 1:
        return matches[0]
    # Zero matches, or ambiguous (several actions normalize to the same
    # name): let the caller report the available actions.
    return None


def _tier_fallback_order(starting_tier: Tier) -> list[Tier]:
    """Get the order of tiers to try, starting from the given tier."""
    all_tiers = [Tier.API, Tier.WORKFLOW, Tier.BROWSER]
    idx = all_tiers.index(starting_tier)
    return all_tiers[idx:] + all_tiers[:idx]


def _as_failure(result: object, outcome: Outcome, tier: Tier) -> dict:
    """Make sure a non-success result says so in machine-readable form."""
    if outcome is Outcome.SUCCESS or not isinstance(result, dict):
        return result  # type: ignore[return-value]
    return {
        "error": f"{tier.name} tier did not complete the action",
        **result,
        "outcome": outcome.value,
        "tier": tier.name.lower(),
    }


def _may_try_next_tier(
    action: SiteAction, tier: Tier, outcome: Outcome, result: dict
) -> bool:
    """Whether another tier may attempt the action without risking a duplicate.

    Rate limits are never bypassed by switching tiers. Otherwise a retry is
    allowed when the request provably did not execute (one HTTP request that
    the server rejected, or a tier that says it dispatched nothing) or when
    the operation is a safe read. A browser or workflow run may have clicked
    and submitted before it hit a login wall, so its rejection proves nothing.
    """
    if outcome is Outcome.RATE_LIMITED:
        return False
    if result.get("dispatched") is False or (tier is Tier.API and outcome in REJECTED):
        return True
    return action.endpoint is not None and action.endpoint.method.upper() in SAFE_METHODS
