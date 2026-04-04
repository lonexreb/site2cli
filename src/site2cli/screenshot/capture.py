"""Screenshot capture using Playwright."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from site2cli.models import ScreenshotResult


async def take_screenshot(
    url: str,
    output: str | None = None,
    selector: str | None = None,
    full_page: bool = True,
    fmt: str = "png",
    quality: int | None = None,
    width: int = 1920,
    height: int = 1080,
    wait: str | None = None,
    proxy: dict | None = None,
    profile: str | None = None,
    session: str | None = None,
) -> ScreenshotResult:
    """Capture a screenshot of a web page.

    Args:
        url: URL to capture.
        output: Output file path. Auto-generated if None.
        selector: CSS selector for element screenshot.
        full_page: Capture full scrollable page vs viewport only.
        fmt: Image format (png or jpeg).
        quality: JPEG quality (1-100).
        width: Viewport width.
        height: Viewport height.
        wait: Wait condition before capture.
        proxy: Playwright proxy dict.
        profile: Browser profile name.
        session: Session name.

    Returns:
        ScreenshotResult with path and metadata.
    """
    from site2cli.browser.context import create_browser_context

    if output is None:
        domain = urlparse(url).netloc.replace(":", "_")
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output = f"{domain}_{ts}.{fmt}"

    screenshot_kwargs: dict = {
        "path": output,
        "full_page": full_page and selector is None,
        "type": fmt,
    }
    if fmt == "jpeg" and quality is not None:
        screenshot_kwargs["quality"] = quality

    async with create_browser_context(
        proxy=proxy, profile=profile, session=session
    ) as (browser, context, page):
        page.set_default_timeout(30_000)
        await page.set_viewport_size({"width": width, "height": height})
        await page.goto(url, wait_until="networkidle")

        if wait:
            await _apply_wait(page, wait)

        if selector:
            element = await page.query_selector(selector)
            if element is None:
                raise ValueError(f"Selector not found: {selector}")
            await element.screenshot(**screenshot_kwargs)
        else:
            await page.screenshot(**screenshot_kwargs)

    out_path = Path(output)
    return ScreenshotResult(
        url=url,
        path=str(out_path.resolve()),
        width=width,
        height=height,
        format=fmt,
        full_page=full_page and selector is None,
        selector=selector,
    )


async def _apply_wait(page: object, wait: str) -> None:
    """Apply a wait condition before screenshot."""
    if wait == "network-idle":
        await page.wait_for_load_state("networkidle")  # type: ignore[attr-defined]
    elif wait.startswith("exists:"):
        sel = wait[7:]
        await page.wait_for_selector(sel)  # type: ignore[attr-defined]
    elif wait.startswith("visible:"):
        sel = wait[8:]
        await page.wait_for_selector(sel, state="visible")  # type: ignore[attr-defined]
    else:
        # Treat as milliseconds delay
        import asyncio

        try:
            ms = int(wait)
            await asyncio.sleep(ms / 1000)
        except ValueError:
            pass
