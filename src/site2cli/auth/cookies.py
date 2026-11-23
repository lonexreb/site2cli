"""Playwright-compatible cookie management for authenticated discovery."""

from __future__ import annotations

import json
import time
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any

import httpx

from site2cli.config import get_config

# Playwright cookie fields
_COOKIE_FIELDS = {"name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires"}


class CookieManager:
    """Manages Playwright-compatible cookies per domain."""

    def __init__(self) -> None:
        self._config = get_config()
        self._cookie_dir = self._config.data_dir / "auth"
        self._cookie_dir.mkdir(parents=True, exist_ok=True)

    def _cookie_path(self, domain: str) -> Path:
        return self._cookie_dir / f"{domain}.cookies.json"

    def _normalize_cookie(self, cookie: dict[str, Any]) -> dict[str, Any]:
        """Ensure cookie dict has all Playwright-required fields."""
        return {
            "name": cookie.get("name", ""),
            "value": cookie.get("value", ""),
            "domain": cookie.get("domain", ""),
            "path": cookie.get("path", "/"),
            "secure": cookie.get("secure", False),
            "httpOnly": cookie.get("httpOnly", False),
            "sameSite": cookie.get("sameSite", "Lax"),
            "expires": cookie.get("expires", -1),
        }

    def list(self, domain: str) -> list[dict[str, Any]]:
        """List all cookies for a domain."""
        path = self._cookie_path(domain)
        if not path.exists():
            return []
        with open(path) as f:
            data = json.load(f)
        # Auto-migrate old flat dict format
        if isinstance(data, dict) and all(isinstance(v, str) for v in data.values()):
            cookies = self._migrate_flat_dict(data, domain)
            self._save(domain, cookies)
            return cookies
        return [self._normalize_cookie(c) for c in data]

    def get(self, domain: str, name: str) -> dict[str, Any] | None:
        """Get a single cookie by name."""
        for cookie in self.list(domain):
            if cookie["name"] == name:
                return cookie
        return None

    def set(
        self,
        domain: str,
        name: str,
        value: str,
        *,
        path: str = "/",
        secure: bool = False,
        http_only: bool = False,
        same_site: str = "Lax",
        expires: float = -1,
    ) -> None:
        """Set a single cookie for a domain."""
        cookies = self.list(domain)
        # Replace only the cookie with the same identity; the same name on
        # another path is a different cookie.
        cookies = [c for c in cookies if (c["name"], c["path"]) != (name, path)]
        cookies.append(self._normalize_cookie({
            "name": name,
            "value": value,
            "domain": domain if not domain.startswith(".") else domain,
            "path": path,
            "secure": secure,
            "httpOnly": http_only,
            "sameSite": same_site,
            "expires": expires,
        }))
        self._save(domain, cookies)

    def set_all(self, domain: str, cookies: list[dict[str, Any]]) -> None:
        """Replace all cookies for a domain."""
        self._save(domain, [self._normalize_cookie(c) for c in cookies])

    def clear(self, domain: str) -> None:
        """Remove all cookies for a domain."""
        path = self._cookie_path(domain)
        if path.exists():
            path.unlink()

    def export(self, domain: str) -> Path:
        """Export cookies to a JSON file in the current directory."""
        cookies = self.list(domain)
        out = Path.cwd() / f"{domain}.cookies.json"
        with open(out, "w") as f:
            json.dump(cookies, f, indent=2)
        return out

    def import_file(self, path: Path) -> tuple[str, int]:
        """Import cookies from a JSON file. Returns (domain, count)."""
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            raise ValueError("Cookie file must contain a non-empty list of cookie objects")
        # Infer domain from first cookie
        domain = data[0].get("domain", "").lstrip(".")
        if not domain:
            raise ValueError("Cookies must have a 'domain' field")
        cookies = [self._normalize_cookie(c) for c in data]
        self._save(domain, cookies)
        return domain, len(cookies)

    def get_playwright_cookies(self, domain: str) -> list[dict[str, Any]]:
        """Get cookies in Playwright-compatible format for context.add_cookies()."""
        return self.list(domain)

    def list_domains(self) -> list[str]:
        """List all domains that have stored cookies."""
        domains = []
        for path in self._cookie_dir.glob("*.cookies.json"):
            domain = path.name.replace(".cookies.json", "")
            domains.append(domain)
        return sorted(domains)

    def _save(self, domain: str, cookies: list[dict[str, Any]]) -> None:
        path = self._cookie_path(domain)
        with open(path, "w") as f:
            json.dump(cookies, f, indent=2)

    @staticmethod
    def _migrate_flat_dict(
        flat: dict[str, str], domain: str
    ) -> list[dict[str, Any]]:
        """Migrate old dict[str, str] cookie format to Playwright list[dict]."""
        return [
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "secure": False,
                "httpOnly": False,
                "sameSite": "Lax",
                "expires": -1,
            }
            for name, value in flat.items()
        ]


def to_httpx_cookies(cookies: list[dict[str, Any]] | dict[str, str] | None) -> httpx.Cookies:
    """Convert stored browser cookies to a scoped HTTPX cookie jar.

    Domain, path, secure and expiry are preserved, so each request only
    receives the cookies a browser would send. A legacy flat ``{name: value}``
    dict is accepted and stays unscoped, as it always was.

    ponytail: HTTPX rebuilds the jar with the stdlib default policy, which
    also sends a host-only cookie to subdomains of that host. Never to another
    site. Needs a custom transport-level cookie policy if that ever matters.
    """
    if isinstance(cookies, dict):
        return httpx.Cookies(cookies)
    jar = httpx.Cookies()
    now = time.time()
    for c in cookies or []:
        name, domain = c.get("name"), c.get("domain", "")
        if not name or not domain:
            continue
        expires = c.get("expires", -1)
        # Playwright uses -1 for session cookies.
        session = expires is None or expires < 0
        if not session and expires <= now:
            continue
        jar.jar.set_cookie(
            Cookie(
                version=0,
                name=name,
                value=c.get("value", ""),
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=domain.startswith("."),
                domain_initial_dot=domain.startswith("."),
                path=c.get("path") or "/",
                path_specified=True,
                secure=bool(c.get("secure", False)),
                expires=None if session else int(expires),
                discard=session,
                comment=None,
                comment_url=None,
                rest={},
            )
        )
    return jar
