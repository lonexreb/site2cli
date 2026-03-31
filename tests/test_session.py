"""Tests for SessionManager (src/site2cli/browser/session.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from site2cli.browser.session import SessionManager, get_session_manager


def _make_mock_browser_context() -> tuple[AsyncMock, AsyncMock]:
    """Return (mock_browser, mock_context) with async close methods."""
    browser = AsyncMock()
    context = AsyncMock()
    return browser, context


@pytest.fixture()
def sm() -> SessionManager:
    return SessionManager()


# ── list ────────────────────────────────────────────────────────────


def test_list_empty(sm: SessionManager):
    """list() returns empty list initially."""
    assert sm.list() == []


# ── register + list ─────────────────────────────────────────────────


def test_register_and_list(sm: SessionManager):
    """Registered session appears in list()."""
    browser, context = _make_mock_browser_context()
    sm.register("site-a", browser, context)
    assert "site-a" in sm.list()


# ── register + get ──────────────────────────────────────────────────


def test_register_and_get(sm: SessionManager):
    """get() returns the (browser, context) tuple for a registered session."""
    browser, context = _make_mock_browser_context()
    sm.register("site-b", browser, context)

    result = sm.get("site-b")
    assert result is not None
    ret_browser, ret_context = result
    assert ret_browser is browser
    assert ret_context is context


# ── get unknown ─────────────────────────────────────────────────────


def test_get_unknown(sm: SessionManager):
    """get() returns None for an unregistered session name."""
    assert sm.get("unknown") is None


# ── close ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_removes_session(sm: SessionManager):
    """close() calls close on context/browser and removes the session."""
    browser, context = _make_mock_browser_context()
    sm.register("to-close", browser, context)

    await sm.close("to-close")

    assert sm.get("to-close") is None
    assert "to-close" not in sm.list()
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()


# ── close_all ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_all(sm: SessionManager):
    """close_all() removes every registered session."""
    for name in ("s1", "s2", "s3"):
        browser, context = _make_mock_browser_context()
        sm.register(name, browser, context)

    assert len(sm.list()) == 3

    await sm.close_all()

    assert sm.list() == []


# ── singleton ───────────────────────────────────────────────────────


def test_get_session_manager_singleton():
    """get_session_manager() always returns the same instance."""
    a = get_session_manager()
    b = get_session_manager()
    assert a is b


# ── close handles already-closed context ────────────────────────────


@pytest.mark.asyncio
async def test_close_handles_already_closed(sm: SessionManager):
    """close() does not raise if context.close() raises (already closed)."""
    browser, context = _make_mock_browser_context()
    context.close.side_effect = RuntimeError("already closed")
    sm.register("flaky", browser, context)

    # Should not raise
    await sm.close("flaky")
    assert sm.get("flaky") is None


# ── register multiple sessions ──────────────────────────────────────


def test_register_multiple(sm: SessionManager):
    """Multiple sessions can be registered and listed."""
    names = ["alpha", "beta", "gamma"]
    for name in names:
        browser, context = _make_mock_browser_context()
        sm.register(name, browser, context)

    listed = sm.list()
    assert len(listed) == 3
    for name in names:
        assert name in listed


# ── close non-existent is safe ──────────────────────────────────────


@pytest.mark.asyncio
async def test_close_nonexistent_is_safe(sm: SessionManager):
    """Closing a session that was never registered does not raise."""
    await sm.close("does-not-exist")  # should be a no-op
