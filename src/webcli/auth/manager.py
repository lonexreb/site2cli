"""Authentication flow management."""

from __future__ import annotations

import json
from pathlib import Path

import keyring

from webcli.config import get_config
from webcli.models import AuthType


KEYRING_SERVICE = "webcli"


class AuthManager:
    """Manages authentication credentials for discovered sites."""

    def __init__(self) -> None:
        self._config = get_config()
        self._credentials_dir = self._config.data_dir / "auth"
        self._credentials_dir.mkdir(parents=True, exist_ok=True)

    def store_api_key(self, domain: str, api_key: str) -> None:
        """Store an API key securely using system keyring."""
        keyring.set_password(KEYRING_SERVICE, f"{domain}:api_key", api_key)

    def get_api_key(self, domain: str) -> str | None:
        """Retrieve a stored API key."""
        return keyring.get_password(KEYRING_SERVICE, f"{domain}:api_key")

    def store_cookies(self, domain: str, cookies: dict[str, str]) -> None:
        """Store cookies for a domain."""
        cookie_file = self._credentials_dir / f"{domain}.cookies.json"
        with open(cookie_file, "w") as f:
            json.dump(cookies, f)

    def get_cookies(self, domain: str) -> dict[str, str] | None:
        """Retrieve stored cookies for a domain."""
        cookie_file = self._credentials_dir / f"{domain}.cookies.json"
        if cookie_file.exists():
            with open(cookie_file) as f:
                return json.load(f)
        return None

    def store_token(self, domain: str, token: str, token_type: str = "bearer") -> None:
        """Store an OAuth/bearer token."""
        keyring.set_password(KEYRING_SERVICE, f"{domain}:token:{token_type}", token)

    def get_token(self, domain: str, token_type: str = "bearer") -> str | None:
        """Retrieve a stored token."""
        return keyring.get_password(KEYRING_SERVICE, f"{domain}:token:{token_type}")

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

    def get_auth_cookies(self, domain: str) -> dict[str, str]:
        """Get authentication cookies for a domain."""
        return self.get_cookies(domain) or {}

    def extract_browser_cookies(self, domain: str) -> dict[str, str] | None:
        """Extract cookies from the user's real browser for a domain."""
        try:
            import browser_cookie3

            cookies = {}
            # Try Chrome first, then Firefox
            for loader in [browser_cookie3.chrome, browser_cookie3.firefox]:
                try:
                    jar = loader(domain_name=f".{domain}")
                    for cookie in jar:
                        cookies[cookie.name] = cookie.value
                    if cookies:
                        self.store_cookies(domain, cookies)
                        return cookies
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
