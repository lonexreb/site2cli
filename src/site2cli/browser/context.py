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
    headless: bool | None = None,
) -> AsyncIterator[tuple[Browser, BrowserContext, Page]]:
    """Create a browser context with cookies, profile, and session support.

    This replaces all inline browser launch code across the codebase.

    Args:
        profile: Name of an imported browser profile to use (persistent context).
        session_manager: Optional SessionManager to reuse sessions.
        session_name: Session name for session_manager lookup.
        inject_cookies_for: Domain to inject stored cookies for.
        proxy: Playwright proxy dict; overrides the configured proxy.
        headless: Overrides the configured headless setting for a new browser.

    Yields:
        Tuple of (browser, context, page).
    """
    from site2cli.browser.session import SessionError, current_session, get_session_manager

    # config.browser.session is deliberately not consulted: a session only
    # persists inside the daemon, which selects it per request.
    session_name = session_name or current_session.get()
    if session_name and session_manager is None:
        session_manager = get_session_manager()

    if not (session_manager and session_name):
        pw = await _start_playwright()
        browser = context = None
        try:
            browser, context, page = await _launch(pw, profile, proxy, headless, inject_cookies_for)
            yield browser, context, page  # type: ignore[misc]
        finally:
            if browser:
                await browser.close()
            elif context:
                await context.close()
            await pw.stop()
        return

    # Managed session: look up or create under the session's lock, but do not
    # hold the lock while the caller uses the page.
    async with session_manager.lock(session_name):
        existing = session_manager.get(session_name, profile)
        if existing:
            browser, context = existing
            try:
                if browser is not None and not browser.is_connected():
                    raise RuntimeError("browser disconnected")
                page = await context.new_page()
            except Exception as exc:
                # Releases the driver too, so a crashed browser leaks nothing.
                await session_manager.close(session_name)
                raise SessionError(
                    f"Session '{session_name}' lost its browser and was removed. "
                    "Run the command again to start a fresh session; "
                    "its login state is gone."
                ) from exc
        else:
            pw = await _start_playwright()
            try:
                browser, context, page = await _launch(
                    pw, profile, proxy, headless, inject_cookies_for
                )
            except BaseException:
                await pw.stop()
                raise
            # The session manager now owns the driver, browser and context.
            session_manager.register(session_name, browser, context, pw, profile)
    try:
        yield browser, context, page  # type: ignore[misc]
    finally:
        await _close_temp_page(context, page)


async def _start_playwright() -> Playwright:
    from playwright.async_api import async_playwright

    return await async_playwright().start()


async def _launch(
    pw: Playwright,
    profile: str | None,
    proxy: dict | None,
    headless: bool | None,
    inject_cookies_for: str | None,
) -> tuple[Browser | None, BrowserContext, Page]:
    """Launch a browser (or persistent profile) and open one page."""
    config = get_config()
    is_headless = config.browser.headless if headless is None else headless
    # Resolve proxy settings (explicit argument wins over config)
    proxy_config = proxy if proxy is not None else config.proxy.get_playwright_proxy()
    browser: Browser | None = None
    user_agent = _DEFAULT_UA if config.browser.stealth else None

    if profile:
        # Profile mode: launch_persistent_context with user data dir
        from site2cli.auth.profiles import ProfileManager

        profile_path = ProfileManager().get_profile_path(profile)
        if not profile_path:
            raise ValueError(f"Profile '{profile}' not found. Import one first.")
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(profile_path),
            "headless": is_headless,
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": user_agent,
        }
        if proxy_config:
            launch_kwargs["proxy"] = proxy_config
        # The persistent context owns its browser.
        context = await pw.chromium.launch_persistent_context(**launch_kwargs)
        page = context.pages[0] if context.pages else await context.new_page()
    else:
        launch_kwargs = {"headless": is_headless}
        if proxy_config:
            launch_kwargs["proxy"] = proxy_config
        browser = await pw.chromium.launch(**launch_kwargs)
        try:
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}, user_agent=user_agent
            )
            page = await context.new_page()
        except BaseException:
            await browser.close()
            raise

    if inject_cookies_for:
        try:
            from site2cli.auth.cookies import CookieManager

            cookies = CookieManager().get_playwright_cookies(inject_cookies_for)
            if cookies:
                await context.add_cookies(cookies)
        except Exception:
            pass
    return browser, context, page


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
