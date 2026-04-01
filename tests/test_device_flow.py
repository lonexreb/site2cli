"""Tests for OAuth device flow (RFC 8628) handler."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from site2cli.auth.device_flow import DeviceFlowError, DeviceFlowHandler
from site2cli.models import DeviceCodeResponse, OAuthProviderConfig, OAuthTokenData


@pytest.fixture()
def github_provider() -> OAuthProviderConfig:
    return OAuthProviderConfig(
        name="github",
        client_id="test-client-id",
        device_authorization_endpoint="https://github.com/login/device/code",
        token_endpoint="https://github.com/login/oauth/access_token",
        scopes=["repo", "read:user"],
    )


@pytest.fixture()
def handler(github_provider) -> DeviceFlowHandler:
    return DeviceFlowHandler(github_provider)


def _mock_httpx_response(json_data, status_code=200):
    """Create a mock httpx response with sync .json() method."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


def _patch_httpx_post(responses):
    """Patch httpx.AsyncClient as context manager with sequential responses."""
    if not isinstance(responses, list):
        responses = [responses]
    idx = {"i": 0}

    async def mock_post(*args, **kwargs):
        r = responses[min(idx["i"], len(responses) - 1)]
        idx["i"] += 1
        return r

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    return patch("site2cli.auth.device_flow.httpx.AsyncClient", return_value=mock_client)


# --- Model tests ---


def test_device_code_response_all_fields():
    resp = DeviceCodeResponse(
        device_code="DC123", user_code="ABCD-1234",
        verification_uri="https://github.com/login/device",
        verification_uri_complete="https://github.com/login/device?user_code=ABCD-1234",
        expires_in=900, interval=5,
    )
    assert resp.user_code == "ABCD-1234"
    assert resp.verification_uri_complete is not None


def test_device_code_response_defaults():
    resp = DeviceCodeResponse(
        device_code="DC123", user_code="ABCD",
        verification_uri="https://example.com/device",
    )
    assert resp.expires_in == 900
    assert resp.interval == 5


def test_oauth_token_data_minimal():
    token = OAuthTokenData(access_token="at_123")
    assert token.token_type == "Bearer"
    assert token.refresh_token is None


def test_oauth_token_data_full():
    token = OAuthTokenData(
        access_token="at_123", refresh_token="rt_456",
        expires_at=time.time() + 3600, scope="repo", provider_name="github",
    )
    assert token.refresh_token == "rt_456"


# --- request_device_code ---


@pytest.mark.asyncio
async def test_request_device_code_success(handler):
    resp = _mock_httpx_response({
        "device_code": "dc_test", "user_code": "ABCD-1234",
        "verification_uri": "https://github.com/login/device",
        "expires_in": 600, "interval": 10,
    })
    with _patch_httpx_post(resp):
        result = await handler.request_device_code()
    assert result.device_code == "dc_test"
    assert result.user_code == "ABCD-1234"
    assert result.interval == 10


# --- poll_for_token ---


@pytest.mark.asyncio
async def test_poll_immediate_success(handler):
    resp = _mock_httpx_response({
        "access_token": "gho_abc123", "token_type": "bearer", "scope": "repo",
    })
    with _patch_httpx_post(resp), patch("asyncio.sleep", new_callable=AsyncMock):
        token = await handler.poll_for_token("dc_test", interval=0, expires_in=30)
    assert token.access_token == "gho_abc123"
    assert token.scope == "repo"


@pytest.mark.asyncio
async def test_poll_pending_then_success(handler):
    pending = _mock_httpx_response({"error": "authorization_pending"})
    success = _mock_httpx_response({"access_token": "gho_final", "token_type": "bearer"})
    with _patch_httpx_post([pending, pending, success]), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        token = await handler.poll_for_token("dc_test", interval=0, expires_in=30)
    assert token.access_token == "gho_final"


@pytest.mark.asyncio
async def test_poll_slow_down(handler):
    slow = _mock_httpx_response({"error": "slow_down"})
    success = _mock_httpx_response({"access_token": "gho_ok", "token_type": "bearer"})
    sleep_vals = []
    orig_sleep = AsyncMock(side_effect=lambda s: sleep_vals.append(s))
    with _patch_httpx_post([slow, success]), patch("asyncio.sleep", orig_sleep):
        token = await handler.poll_for_token("dc_test", interval=5, expires_in=60)
    assert token.access_token == "gho_ok"
    assert any(v >= 10 for v in sleep_vals)


@pytest.mark.asyncio
async def test_poll_expired_raises(handler):
    resp = _mock_httpx_response({"error": "expired_token"})
    with _patch_httpx_post(resp), patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(DeviceFlowError, match="expired"):
            await handler.poll_for_token("dc_test", interval=0, expires_in=30)


@pytest.mark.asyncio
async def test_poll_denied_raises(handler):
    resp = _mock_httpx_response({"error": "access_denied"})
    with _patch_httpx_post(resp), patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(DeviceFlowError, match="denied"):
            await handler.poll_for_token("dc_test", interval=0, expires_in=30)


@pytest.mark.asyncio
async def test_poll_with_expires_in(handler):
    resp = _mock_httpx_response({
        "access_token": "gho_xyz", "token_type": "bearer", "expires_in": 3600,
    })
    with _patch_httpx_post(resp), patch("asyncio.sleep", new_callable=AsyncMock):
        token = await handler.poll_for_token("dc_test", interval=0, expires_in=30)
    assert token.expires_at is not None
    assert token.expires_at > time.time()


# --- refresh_token ---


@pytest.mark.asyncio
async def test_refresh_success(handler):
    resp = _mock_httpx_response({
        "access_token": "gho_refreshed", "refresh_token": "ghr_new",
        "token_type": "bearer", "expires_in": 3600,
    })
    with _patch_httpx_post(resp):
        token = await handler.refresh_token("ghr_old")
    assert token.access_token == "gho_refreshed"
    assert token.refresh_token == "ghr_new"


@pytest.mark.asyncio
async def test_refresh_preserves_old_refresh(handler):
    resp = _mock_httpx_response({"access_token": "gho_new", "token_type": "bearer"})
    with _patch_httpx_post(resp):
        token = await handler.refresh_token("ghr_old")
    assert token.refresh_token == "ghr_old"


# --- headers ---


def test_request_headers_include_json_accept(handler):
    assert handler._request_headers()["Accept"] == "application/json"
