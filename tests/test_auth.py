"""Tests for the AuthManager class in site2cli.auth.manager."""

from __future__ import annotations

import pytest

from site2cli.auth.manager import KEYRING_SERVICE, AuthManager
from site2cli.config import reset_config
from site2cli.models import AuthType


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect XDG_DATA_HOME to tmp_path so each test gets a fresh data dir."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    yield
    reset_config()


@pytest.fixture
def mock_keyring(monkeypatch):
    """Dict-backed keyring mock that replaces set/get/delete_password."""
    store = {}
    monkeypatch.setattr(
        "site2cli.auth.manager.keyring.set_password",
        lambda svc, key, val: store.__setitem__((svc, key), val),
    )
    monkeypatch.setattr(
        "site2cli.auth.manager.keyring.get_password",
        lambda svc, key: store.get((svc, key)),
    )
    monkeypatch.setattr(
        "site2cli.auth.manager.keyring.delete_password",
        lambda svc, key: store.pop((svc, key), None),
    )
    return store


@pytest.fixture
def manager():
    """Return a fresh AuthManager instance."""
    return AuthManager()


# ---------------------------------------------------------------------------
# 1. store_api_key / get_api_key roundtrip
# ---------------------------------------------------------------------------

def test_store_and_get_api_key(manager, mock_keyring):
    manager.store_api_key("example.com", "secret-key-123")
    result = manager.get_api_key("example.com")
    assert result == "secret-key-123"
    assert mock_keyring[(KEYRING_SERVICE, "example.com:api_key")] == "secret-key-123"


# ---------------------------------------------------------------------------
# 2. get_api_key returns None when not stored
# ---------------------------------------------------------------------------

def test_get_api_key_missing_returns_none(manager, mock_keyring):
    result = manager.get_api_key("unknown.com")
    assert result is None


# ---------------------------------------------------------------------------
# 3. store_cookies / get_cookies roundtrip (file-based)
# ---------------------------------------------------------------------------

def test_store_and_get_cookies(manager):
    cookies = {"session": "abc123", "csrftoken": "xyz"}
    manager.store_cookies("example.com", cookies)
    result = manager.get_cookies("example.com")
    assert result == cookies


# ---------------------------------------------------------------------------
# 4. get_cookies returns None when not stored
# ---------------------------------------------------------------------------

def test_get_cookies_missing_returns_none(manager):
    result = manager.get_cookies("nodata.com")
    assert result is None


# ---------------------------------------------------------------------------
# 5. store_token / get_token roundtrip
# ---------------------------------------------------------------------------

def test_store_and_get_token(manager, mock_keyring):
    manager.store_token("example.com", "tok-abc", token_type="bearer")
    result = manager.get_token("example.com", token_type="bearer")
    assert result == "tok-abc"
    assert mock_keyring[(KEYRING_SERVICE, "example.com:token:bearer")] == "tok-abc"


def test_store_and_get_token_custom_type(manager, mock_keyring):
    manager.store_token("example.com", "ref-xyz", token_type="refresh")
    result = manager.get_token("example.com", token_type="refresh")
    assert result == "ref-xyz"


# ---------------------------------------------------------------------------
# 6. get_auth_headers with API_KEY auth type
# ---------------------------------------------------------------------------

def test_get_auth_headers_api_key(manager, mock_keyring):
    manager.store_api_key("example.com", "my-api-key")
    headers = manager.get_auth_headers("example.com", AuthType.API_KEY)
    assert headers == {"X-API-Key": "my-api-key"}


# ---------------------------------------------------------------------------
# 7. get_auth_headers with OAUTH auth type
# ---------------------------------------------------------------------------

def test_get_auth_headers_oauth(manager, mock_keyring):
    manager.store_token("example.com", "oauth-token-99")
    headers = manager.get_auth_headers("example.com", AuthType.OAUTH)
    assert headers == {"Authorization": "Bearer oauth-token-99"}


# ---------------------------------------------------------------------------
# 8. get_auth_headers with NONE returns empty dict
# ---------------------------------------------------------------------------

def test_get_auth_headers_none_returns_empty(manager, mock_keyring):
    headers = manager.get_auth_headers("example.com", AuthType.NONE)
    assert headers == {}


# ---------------------------------------------------------------------------
# 9. clear_auth removes keyring credentials and cookie file
# ---------------------------------------------------------------------------

def test_clear_auth_removes_credentials_and_cookies(manager, mock_keyring):
    domain = "example.com"

    # Store various credential types
    manager.store_api_key(domain, "key-to-delete")
    manager.store_token(domain, "tok-to-delete", token_type="bearer")
    manager.store_cookies(domain, {"session": "del-me"})

    # Sanity-check they are stored
    assert manager.get_api_key(domain) == "key-to-delete"
    assert manager.get_token(domain) == "tok-to-delete"
    assert manager.get_cookies(domain) == {"session": "del-me"}

    manager.clear_auth(domain)

    assert manager.get_api_key(domain) is None
    assert manager.get_token(domain) is None
    assert manager.get_cookies(domain) is None


# ---------------------------------------------------------------------------
# 10. get_auth_cookies returns empty dict when no cookies are stored
# ---------------------------------------------------------------------------

def test_get_auth_cookies_empty_when_none_stored(manager):
    result = manager.get_auth_cookies("nowhere.com")
    assert result == {}
