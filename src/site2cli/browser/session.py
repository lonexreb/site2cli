"""Browser session persistence — keep browser alive across related calls."""

from __future__ import annotations

import atexit
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext


class SessionManager:
    """Manages named browser sessions for reuse across calls."""

    def __init__(self) -> None:
        self._sessions: dict[str, tuple[Browser | None, BrowserContext]] = {}
        atexit.register(self._sync_close_all)

    def register(
        self, name: str, browser: Browser | None, context: BrowserContext
    ) -> None:
        """Register a browser session."""
        self._sessions[name] = (browser, context)

    def get(self, name: str) -> tuple[Any, Any] | None:
        """Get an existing session by name, or None."""
        return self._sessions.get(name)

    def list(self) -> list[str]:
        """List active session names."""
        return list(self._sessions.keys())

    async def close(self, name: str) -> None:
        """Close and remove a named session."""
        session = self._sessions.pop(name, None)
        if session:
            browser, context = session
            try:
                await context.close()
            except Exception:
                pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def close_all(self) -> None:
        """Close all sessions."""
        names = list(self._sessions.keys())
        for name in names:
            await self.close(name)

    def _sync_close_all(self) -> None:
        """Synchronous cleanup for atexit."""
        if not self._sessions:
            return
        try:
            import asyncio

            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.close_all())
            loop.close()
        except Exception:
            pass


# Module-level singleton
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get the singleton SessionManager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
