"""Tests for CookieManager (src/site2cli/auth/cookies.py).

Covers: list, get, set, set_all, clear, export, import_file,
get_playwright_cookies, list_domains, _migrate_flat_dict,
auto-migration, normalization, and CLI cookie commands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from site2cli.cli import app
from site2cli.config import reset_config

runner = CliRunner()

DOMAIN = "example.com"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate data directory via XDG_DATA_HOME and reset config."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    yield
    reset_config()


@pytest.fixture()
def manager():
    """Return a fresh CookieManager instance."""
    from site2cli.auth.cookies import CookieManager

    return CookieManager()


# ---------------------------------------------------------------------------
# 1. list() returns empty for unknown domain
# ---------------------------------------------------------------------------


def test_list_empty_for_unknown_domain(manager):
    assert manager.list("nonexistent.org") == []


# ---------------------------------------------------------------------------
# 2. set() and list() roundtrip
# ---------------------------------------------------------------------------


def test_set_and_list_roundtrip(manager):
    manager.set(DOMAIN, "session", "abc123")
    cookies = manager.list(DOMAIN)
    assert len(cookies) == 1
    cookie = cookies[0]
    assert cookie["name"] == "session"
    assert cookie["value"] == "abc123"
    assert cookie["domain"] == DOMAIN


# ---------------------------------------------------------------------------
# 3. set() overwrites existing cookie with same name
# ---------------------------------------------------------------------------


def test_set_overwrites_existing(manager):
    manager.set(DOMAIN, "token", "old_value")
    manager.set(DOMAIN, "token", "new_value")
    cookies = manager.list(DOMAIN)
    assert len(cookies) == 1
    assert cookies[0]["value"] == "new_value"


# ---------------------------------------------------------------------------
# 4. get() returns specific cookie
# ---------------------------------------------------------------------------


def test_get_returns_specific_cookie(manager):
    manager.set(DOMAIN, "alpha", "1")
    manager.set(DOMAIN, "beta", "2")
    cookie = manager.get(DOMAIN, "beta")
    assert cookie is not None
    assert cookie["name"] == "beta"
    assert cookie["value"] == "2"


# ---------------------------------------------------------------------------
# 5. get() returns None for missing cookie
# ---------------------------------------------------------------------------


def test_get_returns_none_for_missing(manager):
    manager.set(DOMAIN, "exists", "yes")
    assert manager.get(DOMAIN, "ghost") is None


# ---------------------------------------------------------------------------
# 6. set_all() replaces all cookies
# ---------------------------------------------------------------------------


def test_set_all_replaces_cookies(manager):
    manager.set(DOMAIN, "old1", "v1")
    manager.set(DOMAIN, "old2", "v2")

    new_cookies = [
        {"name": "new1", "value": "a", "domain": DOMAIN, "path": "/"},
        {"name": "new2", "value": "b", "domain": DOMAIN, "path": "/"},
        {"name": "new3", "value": "c", "domain": DOMAIN, "path": "/"},
    ]
    manager.set_all(DOMAIN, new_cookies)

    result = manager.list(DOMAIN)
    names = {c["name"] for c in result}
    assert names == {"new1", "new2", "new3"}
    assert len(result) == 3


# ---------------------------------------------------------------------------
# 7. clear() removes all cookies for domain
# ---------------------------------------------------------------------------


def test_clear_removes_all(manager):
    manager.set(DOMAIN, "a", "1")
    manager.set(DOMAIN, "b", "2")
    manager.clear(DOMAIN)
    assert manager.list(DOMAIN) == []


def test_clear_does_not_affect_other_domains(manager):
    manager.set("foo.com", "x", "1")
    manager.set("bar.com", "y", "2")
    manager.clear("foo.com")
    assert manager.list("foo.com") == []
    assert len(manager.list("bar.com")) == 1


# ---------------------------------------------------------------------------
# 8. export() writes valid JSON file
# ---------------------------------------------------------------------------


def test_export_writes_json(manager, tmp_path: Path):
    manager.set(DOMAIN, "sid", "xyz")
    export_path = manager.export(DOMAIN)
    assert export_path.exists()
    data = json.loads(export_path.read_text())
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "sid"
    assert data[0]["value"] == "xyz"


# ---------------------------------------------------------------------------
# 9. import_file() loads cookies and returns domain + count
# ---------------------------------------------------------------------------


def test_import_file_loads_cookies(manager, tmp_path: Path):
    cookies = [
        {"name": "a", "value": "1", "domain": DOMAIN, "path": "/"},
        {"name": "b", "value": "2", "domain": DOMAIN, "path": "/"},
    ]
    fpath = tmp_path / "cookies.json"
    fpath.write_text(json.dumps(cookies))

    domain, count = manager.import_file(fpath)
    assert domain == DOMAIN
    assert count == 2
    assert len(manager.list(DOMAIN)) == 2


# ---------------------------------------------------------------------------
# 10. import_file() raises ValueError for non-list data
# ---------------------------------------------------------------------------


def test_import_file_rejects_non_list(manager, tmp_path: Path):
    fpath = tmp_path / "bad.json"
    fpath.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ValueError, match="list"):
        manager.import_file(fpath)


# ---------------------------------------------------------------------------
# 11. import_file() raises ValueError for missing domain
# ---------------------------------------------------------------------------


def test_import_file_rejects_missing_domain(manager, tmp_path: Path):
    cookies = [{"name": "a", "value": "1", "path": "/"}]
    fpath = tmp_path / "nodomain.json"
    fpath.write_text(json.dumps(cookies))
    with pytest.raises(ValueError, match="domain"):
        manager.import_file(fpath)


# ---------------------------------------------------------------------------
# 12. get_playwright_cookies() returns same as list()
# ---------------------------------------------------------------------------


def test_get_playwright_cookies_matches_list(manager):
    manager.set(DOMAIN, "pw", "test", secure=True, http_only=True)
    assert manager.get_playwright_cookies(DOMAIN) == manager.list(DOMAIN)


# ---------------------------------------------------------------------------
# 13. list_domains() returns all domains with cookies
# ---------------------------------------------------------------------------


def test_list_domains(manager):
    manager.set("alpha.com", "k", "v")
    manager.set("beta.com", "k", "v")
    manager.set("gamma.com", "k", "v")
    domains = manager.list_domains()
    assert set(domains) == {"alpha.com", "beta.com", "gamma.com"}


def test_list_domains_empty(manager):
    assert manager.list_domains() == []


# ---------------------------------------------------------------------------
# 14. _migrate_flat_dict() converts old format
# ---------------------------------------------------------------------------


def test_migrate_flat_dict():
    from site2cli.auth.cookies import CookieManager

    flat = {"session": "abc", "token": "xyz"}
    result = CookieManager._migrate_flat_dict(flat, DOMAIN)
    assert isinstance(result, list)
    assert len(result) == 2
    names = {c["name"] for c in result}
    assert names == {"session", "token"}
    for c in result:
        assert c["domain"] == DOMAIN
        assert "path" in c
        assert "value" in c


# ---------------------------------------------------------------------------
# 15. Auto-migration on list() when old flat dict is stored
# ---------------------------------------------------------------------------


def test_auto_migration_flat_dict(manager):
    """Simulate old flat-dict storage and verify list() auto-migrates."""
    from site2cli.auth.cookies import CookieManager

    # Directly write old-format data to the backing store
    # The CookieManager stores cookies in a JSON file keyed by domain.
    # Old format: {"domain": {"name": "value", ...}}
    # New format: {"domain": [{"name": ..., "value": ..., ...}, ...]}
    store_path = manager._store_path if hasattr(manager, "_store_path") else None
    if store_path is None:
        pytest.skip("Cannot access internal _store_path for migration test")

    old_data = {DOMAIN: {"legacy_cookie": "old_val"}}
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(old_data))

    # Force a fresh manager to read from disk
    fresh = CookieManager()
    cookies = fresh.list(DOMAIN)
    assert len(cookies) >= 1
    assert any(c["name"] == "legacy_cookie" and c["value"] == "old_val" for c in cookies)


# ---------------------------------------------------------------------------
# 16. Cookie normalization adds default fields
# ---------------------------------------------------------------------------


def test_cookie_normalization_defaults(manager):
    manager.set(DOMAIN, "minimal", "val")
    cookie = manager.get(DOMAIN, "minimal")
    assert cookie is not None
    assert cookie.get("path") == "/"
    assert cookie.get("secure") is False or cookie.get("secure") == False  # noqa: E712
    assert cookie.get("httpOnly") is False or cookie.get("httpOnly") == False  # noqa: E712
    assert "sameSite" in cookie or "same_site" in cookie


def test_set_with_all_options(manager):
    manager.set(
        DOMAIN,
        "full",
        "val",
        path="/api",
        secure=True,
        http_only=True,
        same_site="Strict",
        expires=1700000000,
    )
    cookie = manager.get(DOMAIN, "full")
    assert cookie is not None
    assert cookie["path"] == "/api"
    assert cookie.get("secure") is True
    assert cookie.get("httpOnly") is True or cookie.get("http_only") is True


# ---------------------------------------------------------------------------
# 17. CLI commands via CliRunner (cookies list, set, clear)
# ---------------------------------------------------------------------------


def test_cli_cookies_list_empty():
    result = runner.invoke(app, ["cookies", "list", DOMAIN])
    assert result.exit_code == 0


def test_cli_cookies_set_and_list():
    result = runner.invoke(app, ["cookies", "set", DOMAIN, "cli_cookie", "cli_val"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["cookies", "list", DOMAIN])
    assert result.exit_code == 0
    assert "cli_cookie" in result.stdout


def test_cli_cookies_clear():
    runner.invoke(app, ["cookies", "set", DOMAIN, "temp", "val"])
    result = runner.invoke(app, ["cookies", "clear", DOMAIN])
    assert result.exit_code == 0

    result = runner.invoke(app, ["cookies", "list", DOMAIN])
    assert result.exit_code == 0
    assert "temp" not in result.stdout


# ---------------------------------------------------------------------------
# 18. Cookies export/import roundtrip
# ---------------------------------------------------------------------------


def test_export_import_roundtrip(manager, tmp_path: Path):
    manager.set(DOMAIN, "round1", "trip1")
    manager.set(DOMAIN, "round2", "trip2")

    export_path = manager.export(DOMAIN)
    assert export_path.exists()

    # Clear and reimport
    manager.clear(DOMAIN)
    assert manager.list(DOMAIN) == []

    domain, count = manager.import_file(export_path)
    assert domain == DOMAIN
    assert count == 2

    cookies = manager.list(DOMAIN)
    names = {c["name"] for c in cookies}
    assert names == {"round1", "round2"}
