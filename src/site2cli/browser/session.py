"""Browser session persistence — keep browser alive across related calls."""

from __future__ import annotations

import asyncio
import atexit
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright

# The session selected for the current task (a daemon request or a CLI
# command). The browser context factory reads it, so every tier and discovery
# honour the selection without threading a parameter through each of them.
current_session: ContextVar[str | None] = ContextVar("site2cli_session", default=None)


class SessionError(RuntimeError):
    """A named session cannot be used as requested."""


@dataclass
class _Session:
    browser: Browser | None
    context: BrowserContext
    # The Playwright driver. Owned here so the session outlives the call
    # that created it; stopping it kills every browser it launched.
    playwright: Playwright | None = None
    profile: str | None = None


class SessionManager:
    """Owns named browser sessions: driver, browser, context and cleanup."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        atexit.register(self._sync_close_all)

    def register(
        self,
        name: str,
        browser: Browser | None,
        context: BrowserContext,
        playwright: Playwright | None = None,
        profile: str | None = None,
    ) -> None:
        """Register a browser session and take ownership of its resources."""
        self._sessions[name] = _Session(browser, context, playwright, profile)

    def lock(self, name: str) -> asyncio.Lock:
        """Lock held while a session is looked up or created.

        Without it two concurrent requests for a new session would each launch
        a browser and the second would overwrite (and leak) the first.
        """
        return self._locks.setdefault(name, asyncio.Lock())

    def get(self, name: str, profile: str | None = None) -> tuple[Any, Any] | None:
        """Get a session by name, or None if there is none.

        Raises SessionError if it was created with a different profile.
        """
        session = self._sessions.get(name)
        if session is None:
            return None
        if profile and profile != session.profile:
            raise SessionError(
                f"Session '{name}' uses profile {session.profile!r}, not {profile!r}. "
                f"Close it with: site2cli session close {name}"
            )
        return session.browser, session.context

    def list(self) -> list[str]:
        """List active session names."""
        return list(self._sessions.keys())

    async def close(self, name: str) -> None:
        """Close and remove a named session."""
        # Popped first, so each resource is released exactly once.
        session = self._sessions.pop(name, None)
        if session is None:
            return
        for resource, release in (
            (session.context, "close"),
            (session.browser, "close"),
            (session.playwright, "stop"),
        ):
            if resource is None:
                continue
            try:
                await getattr(resource, release)()
            except Exception:
                pass  # already closed or disconnected

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
