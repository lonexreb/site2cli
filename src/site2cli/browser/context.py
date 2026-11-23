"""Shared browser context factory — single entry point for all browser launches."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

from site2cli.config import get_config

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@asynccontextmanager
async def create_browser_context(
    *,
    profile: str | None = None,
    session_manager: Any | None = None,
    session_name: str | None = None,
    inject_cookies_for: str | None = None,
    proxy: dict | None = None,
) -> AsyncIterator[tuple[Browser, BrowserContext, Page]]:
    """Create a browser context with cookies, profile, and session support.

    This replaces all inline browser launch code across the codebase.

    Args:
        profile: Name of an imported browser profile to use (persistent context).
        session_manager: Optional SessionManager to reuse sessions.
        session_name: Session name for session_manager lookup.
        inject_cookies_for: Domain to inject stored cookies for.
        proxy: Playwright proxy dict; overrides the configured proxy.

    Yields:
        Tuple of (browser, context, page).
    """
    config = get_config()

    from site2cli.browser.session import current_session, get_session_manager

    session_name = session_name or current_session.get() or config.browser.session
    if session_name and session_manager is None:
        session_manager = get_session_manager()
    managed = bool(session_manager and session_name)

    if managed:
        existing = session_manager.get(session_name, profile)
        if existing:
            browser, context = existing
            page = await context.new_page()
            try:
                yield browser, context, page
            finally:
                await _close_temp_page(context, page)
            return

    from playwright.async_api import async_playwright

    pw: Playwright = await async_playwright().start()
    browser: Browser | None = None
    context: BrowserContext | None = None
    registered = False

    try:
        # Resolve proxy settings (explicit argument wins over config)
        proxy_config = proxy if proxy is not None else config.proxy.get_playwright_proxy()

        if profile:
            # Profile mode: launch_persistent_context with user data dir
            from site2cli.auth.profiles import ProfileManager

            pm = ProfileManager()
            profile_path = pm.get_profile_path(profile)
            if not profile_path:
                raise ValueError(f"Profile '{profile}' not found. Import one first.")
            launch_kwargs: dict[str, Any] = {
                "user_data_dir": str(profile_path),
                "headless": config.browser.headless,
                "viewport": {"width": 1920, "height": 1080},
                "user_agent": _DEFAULT_UA if config.browser.stealth else None,
            }
            if proxy_config:
                launch_kwargs["proxy"] = proxy_config
            context = await pw.chromium.launch_persistent_context(**launch_kwargs)
            browser = None  # persistent context owns the browser
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            # Normal mode: launch + new_context
            launch_kwargs = {"headless": config.browser.headless}
            if proxy_config:
                launch_kwargs["proxy"] = proxy_config
            browser = await pw.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=_DEFAULT_UA if config.browser.stealth else None,
            )
            page = await context.new_page()

        # Inject stored cookies if requested
        if inject_cookies_for:
            try:
                from site2cli.auth.cookies import CookieManager

                cm = CookieManager()
                cookies = cm.get_playwright_cookies(inject_cookies_for)
                if cookies:
                    await context.add_cookies(cookies)
            except Exception:
                pass

        if managed:
            # The session manager now owns the driver, browser and context.
            session_manager.register(session_name, browser, context, pw, profile)
            registered = True

        yield browser, context, page  # type: ignore[misc]
    finally:
        if registered:
            await _close_temp_page(context, page)  # type: ignore[arg-type]
        else:
            if browser:
                await browser.close()
            elif context:
                await context.close()
            await pw.stop()


async def _close_temp_page(context: BrowserContext, page: Page) -> None:
    """Close a per-call page in a long-lived session so pages don't pile up.

    The last page is left open: closing every page of a persistent profile
    context can take the browser down with it.
    """
    try:
        if len(context.pages) > 1:
            await page.close()
    except Exception:
        pass  # the browser is already gone; the next get() reports it
