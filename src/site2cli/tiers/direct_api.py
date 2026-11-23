"""Tier 3: Direct API calls using generated clients."""

from __future__ import annotations

import contextlib
import importlib.util
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from site2cli.auth.manager import AuthManager
from site2cli.config import get_config
from site2cli.models import EndpointInfo, SiteEntry
from site2cli.outcome import Outcome, classify_exception, classify_response


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
        expects_json = _expects_json(endpoint)

        # Try to use generated client first
        call = self._load_client_call(site, endpoint, params)
        if call is not None:
            client, method = call
            # From here the request may reach the server: never fall through
            # to a second request, whatever happens.
            try:
                data = method(**params)
            except Exception as exc:
                return {**classify_exception(exc), "transport": "generated_client"}
            finally:
                with contextlib.suppress(Exception):
                    client.close()
            return {
                "outcome": Outcome.SUCCESS.value,
                "data": data,
                "transport": "generated_client",
            }

        return await self._execute_http(site, endpoint, params, expects_json)

    def _load_client_call(
        self, site: SiteEntry, endpoint: EndpointInfo, params: dict
    ) -> tuple[Any, Callable[..., Any]] | None:
        """Resolve the generated client method for an endpoint.

        Returns None when the client cannot be used. Nothing is dispatched
        here, so the caller may safely use raw HTTP instead.
        """
        client_path = Path(site.client_module_path) if site.client_module_path else None
        if not client_path or not client_path.exists():
            return None

        try:
            spec = importlib.util.spec_from_file_location("generated_client", client_path)
            if not spec or not spec.loader:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            client_class = next(
                (
                    attr
                    for name, attr in vars(module).items()
                    if isinstance(attr, type) and name.endswith("Client")
                ),
                None,
            )
            if not client_class:
                return None

            client = client_class(
                base_url=site.base_url,
                headers=self._auth.get_auth_headers(site.domain, site.auth_type),
                cookies=self._auth.get_httpx_cookies(site.domain),
            )
            method = getattr(client, endpoint.description.replace(" ", "_").lower(), None)
            if method is None:
                client.close()
                return None
            # Reject bad arguments now rather than after a request is built.
            inspect.signature(method).bind(**params)
            return client, method
        except Exception:
            return None

    async def _execute_http(
        self,
        site: SiteEntry,
        endpoint: EndpointInfo,
        params: dict,
        expects_json: bool = False,
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
        cookies = self._auth.get_httpx_cookies(site.domain)

        client_kwargs: dict = {
            "headers": headers,
            "cookies": cookies,
            "timeout": 30,
        }
        proxy_url = self._config.proxy.get_httpx_proxy()
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        async with httpx.AsyncClient(**client_kwargs) as client:
            try:
                response = await client.request(
                    endpoint.method,
                    url,
                    params=query_params or None,
                    json=body_params or None,
                )
            except httpx.HTTPError as exc:
                return {**classify_exception(exc), "transport": "http"}

        return {
            **classify_response(response, expects_json=expects_json),
            "transport": "http",
        }


def _expects_json(endpoint: EndpointInfo) -> bool:
    """Whether discovery recorded this endpoint as returning JSON."""
    if endpoint.response_content_type:
        return "json" in endpoint.response_content_type.lower()
    return endpoint.response_schema is not None or endpoint.example_response is not None
