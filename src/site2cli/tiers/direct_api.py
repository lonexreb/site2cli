"""Tier 3: Direct API calls using generated clients."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx

from site2cli.auth.manager import AuthManager
from site2cli.config import get_config
from site2cli.models import EndpointInfo, SiteEntry


class DirectAPIExecutor:
    """Tier 3 executor: uses generated API clients or direct HTTP calls."""

    def __init__(self) -> None:
        self._config = get_config()
        self._auth = AuthManager()

    async def execute(
        self,
        site: SiteEntry,
        endpoint: EndpointInfo,
        params: dict,
    ) -> dict:
        """Execute a direct API call.

        Args:
            site: The site entry with base URL and auth info.
            endpoint: The endpoint to call.
            params: Parameters for the call.

        Returns:
            Dict with the API response.
        """
        # Try to use generated client first
        if site.client_module_path:
            result = self._execute_with_client(site, endpoint, params)
            if result is not None:
                return result

        # Fall back to direct HTTP
        return await self._execute_http(site, endpoint, params)

    def _execute_with_client(
        self, site: SiteEntry, endpoint: EndpointInfo, params: dict
    ) -> dict | None:
        """Try to execute using a generated Python client."""
        client_path = Path(site.client_module_path) if site.client_module_path else None
        if not client_path or not client_path.exists():
            return None

        try:
            spec = importlib.util.spec_from_file_location("generated_client", client_path)
            if not spec or not spec.loader:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the client class
            client_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and attr_name.endswith("Client"):
                    client_class = attr
                    break

            if not client_class:
                return None

            headers = self._auth.get_auth_headers(site.domain, site.auth_type)
            cookies = self._auth.get_auth_cookies(site.domain)

            with client_class(
                base_url=site.base_url,
                headers=headers,
                cookies=cookies,
            ) as client:
                # Find the method matching the endpoint
                method_name = endpoint.description.replace(" ", "_").lower()
                if hasattr(client, method_name):
                    method = getattr(client, method_name)
                    return method(**params)

        except Exception:
            return None
        return None

    async def _execute_http(
        self, site: SiteEntry, endpoint: EndpointInfo, params: dict
    ) -> dict:
        """Execute a direct HTTP request."""
        url = site.base_url.rstrip("/") + endpoint.path_pattern

        # Separate params by location
        query_params = {}
        body_params = {}
        for p in endpoint.parameters:
            if p.name in params:
                if p.location == "path":
                    url = url.replace(f"{{{p.name}}}", str(params[p.name]))
                elif p.location == "query":
                    query_params[p.name] = params[p.name]
                elif p.location == "body":
                    body_params[p.name] = params[p.name]

        headers = self._auth.get_auth_headers(site.domain, site.auth_type)
        cookies = self._auth.get_auth_cookies(site.domain)

        client_kwargs: dict = {
            "headers": headers,
            "cookies": cookies,
            "timeout": 30,
        }
        proxy_url = self._config.proxy.get_httpx_proxy()
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.request(
                endpoint.method,
                url,
                params=query_params or None,
                json=body_params or None,
            )

        try:
            data = response.json()
        except Exception:
            data = {"text": response.text, "status_code": response.status_code}

        return {
            "status_code": response.status_code,
            "data": data,
            "headers": dict(response.headers),
        }
