"""Authentication flow management."""

from __future__ import annotations

from typing import Any

import keyring

from site2cli.auth.cookies import CookieManager
from site2cli.config import get_config
from site2cli.models import AuthType

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
