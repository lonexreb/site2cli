"""CDP-based network traffic capture using Playwright."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

from site2cli.config import get_config
from site2cli.models import (
    CapturedExchange,
    CapturedHeader,
    CapturedRequest,
    CapturedResponse,
)


class TrafficCapture:
    """Captures network traffic from browser sessions using CDP."""

    def __init__(self, target_domain: str | None = None) -> None:
        self.target_domain = target_domain
        self.exchanges: list[CapturedExchange] = []
        self._pending: dict[str, tuple[CapturedRequest, float]] = {}
        self._config = get_config()

    def _should_capture(self, url: str) -> bool:
        """Filter to only capture relevant API-like requests."""
        parsed = urlparse(url)

        # Skip static assets
        skip_extensions = {
            ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
            ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map",
        }
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in skip_extensions):
            return False

        # If we have a target domain, filter to it
        if self.target_domain:
            target = self.target_domain.replace("www.", "")
            host = parsed.hostname or ""
            host = host.replace("www.", "")
            if target not in host:
                return False

        return True

    def _is_api_like(self, url: str, content_type: str | None) -> bool:
        """Check if a request looks like an API call."""
        if content_type and any(
            t in content_type for t in ["application/json", "application/xml", "text/xml"]
        ):
            return True
        parsed = urlparse(url)
        api_indicators = ["/api/", "/v1/", "/v2/", "/v3/", "/graphql", "/rest/", "/ajax/"]
        return any(ind in parsed.path.lower() for ind in api_indicators)

    def _ensure_playwright(self):
        try:
            from playwright.async_api import async_playwright
            return async_playwright
        except ImportError:
            raise ImportError(
                "Playwright is required for browser capture. "
                "Install it with: pip install site2cli[browser]"
            )

    async def capture_page_traffic(
        self,
        url: str,
        interaction_callback: callable | None = None,
        duration_seconds: int = 30,
    ) -> list[CapturedExchange]:
        """Launch browser, navigate to URL, capture traffic.

        Args:
            url: The URL to navigate to.
            interaction_callback: Optional async function(page) to interact with the page.
            duration_seconds: How long to wait for traffic if no callback.

        Returns:
            List of captured request/response exchanges.
        """
        config = self._config
        async_playwright = self._ensure_playwright()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=config.browser.headless)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            page = await context.new_page()

            # Set up CDP network interception
            client = await context.new_cdp_session(page)
            await client.send("Network.enable")

            request_data: dict[str, dict] = {}

            def on_request_will_be_sent(params: dict) -> None:
                req = params.get("request", {})
                url = req.get("url", "")
                if not self._should_capture(url):
                    return
                request_id = params.get("requestId", "")
                headers = [
                    CapturedHeader(name=k, value=v)
                    for k, v in req.get("headers", {}).items()
                ]
                body = params.get("request", {}).get("postData")
                ct = req.get("headers", {}).get("Content-Type") or req.get(
                    "headers", {}
                ).get("content-type")
                request_data[request_id] = {
                    "request": CapturedRequest(
                        method=req.get("method", "GET"),
                        url=url,
                        headers=headers,
                        body=body,
                        content_type=ct,
                        timestamp=params.get("timestamp", time.time()),
                    ),
                    "start_time": time.time(),
                }

            async def on_response_received(params: dict) -> None:
                request_id = params.get("requestId", "")
                if request_id not in request_data:
                    return
                response = params.get("response", {})
                resp_ct = response.get("headers", {}).get("content-type", "")

                # Only capture API-like responses
                req_info = request_data[request_id]
                if not self._is_api_like(req_info["request"].url, resp_ct):
                    return

                # Try to get response body
                body = None
                try:
                    result = await client.send(
                        "Network.getResponseBody", {"requestId": request_id}
                    )
                    body = result.get("body")
                except Exception:
                    pass

                resp_headers = [
                    CapturedHeader(name=k, value=v)
                    for k, v in response.get("headers", {}).items()
                ]
                captured_resp = CapturedResponse(
                    status=response.get("status", 0),
                    headers=resp_headers,
                    body=body,
                    content_type=resp_ct,
                )
                duration = (time.time() - req_info["start_time"]) * 1000
                self.exchanges.append(
                    CapturedExchange(
                        request=req_info["request"],
                        response=captured_resp,
                        duration_ms=duration,
                    )
                )

            client.on("Network.requestWillBeSent", on_request_will_be_sent)
            client.on(
                "Network.responseReceived",
                lambda p: asyncio.ensure_future(on_response_received(p)),
            )

            # Navigate
            await page.goto(url, wait_until="networkidle", timeout=config.browser.timeout_ms)

            if interaction_callback:
                await interaction_callback(page)
            else:
                # Wait for dynamic content and API calls
                await page.wait_for_timeout(min(duration_seconds * 1000, config.browser.timeout_ms))

            await browser.close()

        return self.exchanges

    def get_api_exchanges(self) -> list[CapturedExchange]:
        """Return only exchanges that look like API calls."""
        return [
            ex
            for ex in self.exchanges
            if self._is_api_like(ex.request.url, ex.response.content_type)
        ]

    def summarize(self) -> dict:
        """Return a summary of captured traffic."""
        api_exchanges = self.get_api_exchanges()
        endpoints: dict[str, int] = {}
        for ex in api_exchanges:
            parsed = urlparse(ex.request.url)
            key = f"{ex.request.method} {parsed.path}"
            endpoints[key] = endpoints.get(key, 0) + 1

        return {
            "total_requests": len(self.exchanges),
            "api_requests": len(api_exchanges),
            "unique_endpoints": len(endpoints),
            "endpoints": endpoints,
        }
