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
) -> AsyncIterator[tuple[Browser, BrowserContext, Page]]:
    """Create a browser context with cookies, profile, and session support.

    This replaces all inline browser launch code across the codebase.

    Args:
        profile: Name of an imported browser profile to use (persistent context).
        session_manager: Optional SessionManager to reuse sessions.
        session_name: Session name for session_manager lookup.
        inject_cookies_for: Domain to inject stored cookies for.

    Yields:
        Tuple of (browser, context, page).
    """
    config = get_config()

    # If session_manager can provide an existing session, use it
    if session_manager and session_name:
        existing = session_manager.get(session_name)
        if existing:
            browser, context = existing
            page = await context.new_page()
            yield browser, context, page
            return

    from playwright.async_api import async_playwright

    pw_cm = async_playwright()
    pw: Playwright = await pw_cm.__aenter__()
    browser: Browser | None = None

    try:
        if profile:
            # Profile mode: launch_persistent_context with user data dir
            from site2cli.auth.profiles import ProfileManager

            pm = ProfileManager()
            profile_path = pm.get_profile_path(profile)
            if not profile_path:
                raise ValueError(f"Profile '{profile}' not found. Import one first.")
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                headless=config.browser.headless,
                viewport={"width": 1920, "height": 1080},
                user_agent=_DEFAULT_UA if config.browser.stealth else None,
            )
            browser = None  # persistent context owns the browser
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            # Normal mode: launch + new_context
            browser = await pw.chromium.launch(headless=config.browser.headless)
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

        # Register with session manager if requested
        if session_manager and session_name:
            session_manager.register(session_name, browser, context)

        yield browser, context, page  # type: ignore[arg-type]
    finally:
        if not (session_manager and session_name):
            # Only close if not managed by a session
            if browser:
                await browser.close()
            elif profile:
                await context.close()  # type: ignore[possibly-undefined]
        await pw_cm.__aexit__(None, None, None)
