"""Authentication flow management."""

from __future__ import annotations

from typing import Any

import keyring

from site2cli.auth.cookies import CookieManager
from site2cli.config import get_config
from site2cli.models import AuthType, OAuthTokenData

KEYRING_SERVICE = "site2cli"
_OLD_KEYRING_SERVICE = "webcli"


class AuthManager:
    """Manages authentication credentials for discovered sites."""

    def __init__(self) -> None:
        self._config = get_config()
        self._credentials_dir = self._config.data_dir / "auth"
        self._credentials_dir.mkdir(parents=True, exist_ok=True)
        self._cookie_mgr = CookieManager()

    def store_api_key(self, domain: str, api_key: str) -> None:
        """Store an API key securely using system keyring."""
        keyring.set_password(KEYRING_SERVICE, f"{domain}:api_key", api_key)

    def get_api_key(self, domain: str) -> str | None:
        """Retrieve a stored API key."""
        key = keyring.get_password(KEYRING_SERVICE, f"{domain}:api_key")
        if key is None:
            key = keyring.get_password(_OLD_KEYRING_SERVICE, f"{domain}:api_key")
        return key

    def store_cookies(
        self, domain: str, cookies: dict[str, str] | list[dict[str, Any]]
    ) -> None:
        """Store cookies for a domain. Accepts both old flat and Playwright formats."""
        if isinstance(cookies, dict):
            # Old flat format — migrate to Playwright format
            pw_cookies = CookieManager._migrate_flat_dict(cookies, domain)
            self._cookie_mgr.set_all(domain, pw_cookies)
        else:
            self._cookie_mgr.set_all(domain, cookies)

    def get_cookies(self, domain: str) -> list[dict[str, Any]] | None:
        """Retrieve stored cookies in Playwright-compatible format."""
        cookies = self._cookie_mgr.list(domain)
        return cookies if cookies else None

    def get_playwright_cookies(self, domain: str) -> list[dict[str, Any]]:
        """Get cookies ready for Playwright context.add_cookies()."""
        return self._cookie_mgr.get_playwright_cookies(domain)

    def store_token(self, domain: str, token: str, token_type: str = "bearer") -> None:
        """Store an OAuth/bearer token."""
        keyring.set_password(KEYRING_SERVICE, f"{domain}:token:{token_type}", token)

    def get_token(self, domain: str, token_type: str = "bearer") -> str | None:
        """Retrieve a stored token."""
        token = keyring.get_password(KEYRING_SERVICE, f"{domain}:token:{token_type}")
        if token is None:
            token = keyring.get_password(
                _OLD_KEYRING_SERVICE, f"{domain}:token:{token_type}"
            )
        return token

    def get_auth_headers(self, domain: str, auth_type: AuthType) -> dict[str, str]:
        """Get authentication headers for a domain based on auth type."""
        if auth_type == AuthType.API_KEY:
            key = self.get_api_key(domain)
            if key:
                return {"X-API-Key": key}
        elif auth_type == AuthType.OAUTH:
            token = self.get_token(domain)
            if token:
                return {"Authorization": f"Bearer {token}"}
        return {}

    def get_auth_cookies(self, domain: str) -> list[dict[str, Any]]:
        """Get authentication cookies for a domain."""
        return self.get_cookies(domain) or []

    def extract_browser_cookies(self, domain: str) -> list[dict[str, Any]] | None:
        """Extract cookies from the user's real browser for a domain."""
        try:
            import browser_cookie3

            pw_cookies: list[dict[str, Any]] = []
            # Try Chrome first, then Firefox
            for loader in [browser_cookie3.chrome, browser_cookie3.firefox]:
                try:
                    jar = loader(domain_name=f".{domain}")
                    for cookie in jar:
                        pw_cookies.append({
                            "name": cookie.name,
                            "value": cookie.value,
                            "domain": cookie.domain or f".{domain}",
                            "path": cookie.path or "/",
                            "secure": bool(cookie.secure),
                            "httpOnly": bool(
                                getattr(cookie, "has_nonstandard_attr", lambda _: False)(
                                    "HttpOnly"
                                )
                            ),
                            "sameSite": "Lax",
                            "expires": cookie.expires or -1,
                        })
                    if pw_cookies:
                        self._cookie_mgr.set_all(domain, pw_cookies)
                        return pw_cookies
                except Exception:
                    continue
        except ImportError:
            pass
        return None

    # --- OAuth token management ---

    def store_oauth_token(self, domain: str, token_data: OAuthTokenData) -> None:
        """Store OAuth tokens (access in keyring, metadata in JSON)."""

        keyring.set_password(
            KEYRING_SERVICE, f"{domain}:token:bearer", token_data.access_token
        )
        if token_data.refresh_token:
            keyring.set_password(
                KEYRING_SERVICE, f"{domain}:token:refresh", token_data.refresh_token
            )
        # Metadata to JSON
        import json

        meta = {
            "expires_at": token_data.expires_at,
            "scope": token_data.scope,
            "provider_name": token_data.provider_name,
            "token_type": token_data.token_type,
        }
        meta_path = self._credentials_dir / f"{domain}.oauth_meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    def get_oauth_token(self, domain: str) -> OAuthTokenData | None:
        """Reconstruct OAuthTokenData from keyring + metadata."""
        import json

        from site2cli.models import OAuthTokenData

        access_token = self.get_token(domain, "bearer")
        if not access_token:
            return None
        refresh_token = self.get_token(domain, "refresh")
        meta_path = self._credentials_dir / f"{domain}.oauth_meta.json"
        meta: dict = {}
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
        return OAuthTokenData(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=meta.get("token_type", "Bearer"),
            expires_at=meta.get("expires_at"),
            scope=meta.get("scope"),
            provider_name=meta.get("provider_name", ""),
        )

    def is_token_expired(self, domain: str) -> bool:
        """Check if the stored OAuth token has expired (with 60s buffer)."""
        import time

        token_data = self.get_oauth_token(domain)
        if not token_data or token_data.expires_at is None:
            return False
        return time.time() >= (token_data.expires_at - 60)

    async def ensure_valid_token(self, domain: str) -> str | None:
        """Return a valid access token, refreshing if expired."""
        token_data = self.get_oauth_token(domain)
        if not token_data:
            return None
        if not self.is_token_expired(domain):
            return token_data.access_token
        # Try refresh
        if token_data.refresh_token and token_data.provider_name:
            try:
                from site2cli.auth.device_flow import DeviceFlowHandler
                from site2cli.auth.providers import (
                    load_custom_provider,
                )

                provider = load_custom_provider(domain)
                if provider:
                    handler = DeviceFlowHandler(provider)
                    new_token = await handler.refresh_token(token_data.refresh_token)
                    new_token.provider_name = token_data.provider_name
                    self.store_oauth_token(domain, new_token)
                    return new_token.access_token
            except Exception:
                pass
        return token_data.access_token  # return expired token as fallback

    async def get_auth_headers_async(
        self, domain: str, auth_type: AuthType
    ) -> dict[str, str]:
        """Async auth headers with automatic OAuth token refresh."""
        if auth_type == AuthType.OAUTH:
            token = await self.ensure_valid_token(domain)
            if token:
                return {"Authorization": f"Bearer {token}"}
        return self.get_auth_headers(domain, auth_type)

    def clear_auth(self, domain: str) -> None:
        """Remove all stored credentials for a domain."""
        for suffix in ["api_key", "token:bearer", "token:refresh"]:
            try:
                keyring.delete_password(KEYRING_SERVICE, f"{domain}:{suffix}")
            except keyring.errors.PasswordDeleteError:
                pass
        cookie_file = self._credentials_dir / f"{domain}.cookies.json"
        if cookie_file.exists():
            cookie_file.unlink()
        # Clean up OAuth metadata
        for pattern in [f"{domain}.oauth_meta.json", f"{domain}.oauth.json"]:
            meta_file = self._credentials_dir / pattern
            if meta_file.exists():
                meta_file.unlink()
