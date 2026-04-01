"""OAuth 2.0 Device Authorization Grant (RFC 8628) handler."""

from __future__ import annotations

import asyncio
import time

import httpx

from site2cli.models import DeviceCodeResponse, OAuthProviderConfig, OAuthTokenData


class DeviceFlowError(Exception):
    """Error during device flow authentication."""


class DeviceFlowHandler:
    """RFC 8628 OAuth 2.0 Device Authorization Grant handler."""

    def __init__(self, provider: OAuthProviderConfig) -> None:
        self._provider = provider

    def _request_headers(self) -> dict[str, str]:
        """Provider-specific request headers."""
        headers = {"Accept": "application/json"}
        return headers

    async def request_device_code(self) -> DeviceCodeResponse:
        """Request a device code from the authorization endpoint."""
        body = {"client_id": self._provider.client_id}
        if self._provider.scopes:
            body["scope"] = " ".join(self._provider.scopes)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._provider.device_authorization_endpoint,
                data=body,
                headers=self._request_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        return DeviceCodeResponse(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data.get("verification_uri", data.get("verification_url", "")),
            verification_uri_complete=data.get("verification_uri_complete"),
            expires_in=data.get("expires_in", 900),
            interval=data.get("interval", 5),
        )

    async def poll_for_token(
        self,
        device_code: str,
        interval: int = 5,
        expires_in: int = 900,
    ) -> OAuthTokenData:
        """Poll the token endpoint until the user authorizes or the code expires."""
        deadline = time.time() + expires_in
        current_interval = interval

        async with httpx.AsyncClient(timeout=30) as client:
            while time.time() < deadline:
                await asyncio.sleep(current_interval)

                body = {
                    "client_id": self._provider.client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                }
                resp = await client.post(
                    self._provider.token_endpoint,
                    data=body,
                    headers=self._request_headers(),
                )

                data = resp.json()

                # Check for error responses (RFC 8628 Section 3.5)
                error = data.get("error")
                if error == "authorization_pending":
                    continue
                elif error == "slow_down":
                    current_interval += 5
                    continue
                elif error == "expired_token":
                    raise DeviceFlowError("Device code expired. Please try again.")
                elif error == "access_denied":
                    raise DeviceFlowError("Authorization denied by user.")
                elif error:
                    raise DeviceFlowError(f"OAuth error: {error}")

                # Success — token returned
                if "access_token" in data:
                    expires_at = None
                    if "expires_in" in data:
                        expires_at = time.time() + data["expires_in"]
                    return OAuthTokenData(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token"),
                        token_type=data.get("token_type", "Bearer"),
                        expires_at=expires_at,
                        scope=data.get("scope"),
                        provider_name=self._provider.name,
                    )

        raise DeviceFlowError("Device code expired (timeout). Please try again.")

    async def refresh_token(self, refresh_token: str) -> OAuthTokenData:
        """Use a refresh token to get a new access token."""
        body = {
            "client_id": self._provider.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._provider.token_endpoint,
                data=body,
                headers=self._request_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        expires_at = None
        if "expires_in" in data:
            expires_at = time.time() + data["expires_in"]

        return OAuthTokenData(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            token_type=data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scope=data.get("scope"),
            provider_name=self._provider.name,
        )

    async def run_device_flow(self) -> OAuthTokenData:
        """Full device flow: request code, return it for display, poll for token."""
        device_resp = await self.request_device_code()
        return device_resp, await self.poll_for_token(
            device_resp.device_code,
            device_resp.interval,
            device_resp.expires_in,
        )
