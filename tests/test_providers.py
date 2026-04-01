"""Tests for OAuth provider configuration."""

from __future__ import annotations

import pytest

from site2cli.auth.providers import (
    KNOWN_PROVIDERS,
    get_provider_config,
    load_custom_provider,
    save_custom_provider,
)
from site2cli.config import reset_config
from site2cli.models import OAuthProviderConfig


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    yield
    reset_config()


def test_get_github_provider():
    config = get_provider_config("github", "my-client-id")
    assert config.name == "github"
    assert config.client_id == "my-client-id"
    assert "github.com" in config.device_authorization_endpoint
    assert "github.com" in config.token_endpoint


def test_get_google_provider():
    config = get_provider_config("google", "google-client-id")
    assert config.name == "google"
    assert "googleapis.com" in config.token_endpoint


def test_get_microsoft_provider():
    config = get_provider_config("microsoft", "ms-client-id")
    assert config.name == "microsoft"
    assert "microsoftonline.com" in config.token_endpoint


def test_get_provider_with_custom_scopes():
    config = get_provider_config("github", "cid", scopes=["read:user"])
    assert config.scopes == ["read:user"]


def test_get_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider_config("unknown_provider", "cid")


def test_save_and_load_custom_provider():
    provider = OAuthProviderConfig(
        name="custom",
        client_id="custom-cid",
        device_authorization_endpoint="https://example.com/device",
        token_endpoint="https://example.com/token",
        scopes=["read", "write"],
    )
    save_custom_provider("example.com", provider)
    loaded = load_custom_provider("example.com")
    assert loaded is not None
    assert loaded.client_id == "custom-cid"
    assert loaded.scopes == ["read", "write"]


def test_load_custom_provider_missing():
    assert load_custom_provider("nonexistent.com") is None


def test_known_providers_have_required_fields():
    for name, template in KNOWN_PROVIDERS.items():
        assert "device_authorization_endpoint" in template
        assert "token_endpoint" in template
        assert "name" in template
