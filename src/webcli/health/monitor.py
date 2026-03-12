"""API health checking for discovered endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

from webcli.auth.manager import AuthManager
from webcli.models import EndpointInfo, HealthStatus, SiteEntry
from webcli.registry import SiteRegistry


class HealthMonitor:
    """Monitors the health of discovered API endpoints."""

    def __init__(self, registry: SiteRegistry) -> None:
        self._registry = registry
        self._auth = AuthManager()

    async def check_site(self, domain: str) -> dict[str, HealthStatus]:
        """Check health of all actions for a site.

        Returns:
            Dict mapping action name to health status.
        """
        site = self._registry.get_site(domain)
        if not site:
            return {}

        results = {}
        for action in site.actions:
            if action.endpoint:
                status = await self._check_endpoint(site, action.endpoint)
            else:
                status = HealthStatus.UNKNOWN
            self._registry.update_health(domain, action.name, status)
            results[action.name] = status

        return results

    async def check_all_sites(self) -> dict[str, dict[str, HealthStatus]]:
        """Check health of all registered sites."""
        sites = self._registry.list_sites()
        results = {}
        for site in sites:
            results[site.domain] = await self.check_site(site.domain)
        return results

    async def _check_endpoint(
        self, site: SiteEntry, endpoint: EndpointInfo
    ) -> HealthStatus:
        """Check if a single endpoint is responsive."""
        url = site.base_url.rstrip("/") + endpoint.path_pattern

        # Replace path parameters with dummy values for health check
        url = url.replace("/{id}", "/1")

        headers = self._auth.get_auth_headers(site.domain, site.auth_type)

        try:
            async with httpx.AsyncClient(
                headers=headers, timeout=10, follow_redirects=True
            ) as client:
                # Use HEAD for GET endpoints, otherwise try OPTIONS
                if endpoint.method.upper() == "GET":
                    response = await client.head(url)
                else:
                    response = await client.options(url)

                if response.status_code < 400:
                    return HealthStatus.HEALTHY
                elif response.status_code < 500:
                    return HealthStatus.DEGRADED
                else:
                    return HealthStatus.BROKEN
        except httpx.TimeoutException:
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.BROKEN
