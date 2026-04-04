"""robots.txt parser and URL filtering."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx


class RobotsChecker:
    """Parse and check robots.txt rules."""

    def __init__(self, domain: str, scheme: str = "https") -> None:
        self._domain = domain
        self._scheme = scheme
        self._rules: list[tuple[str, bool]] = []  # (path_pattern, allowed)
        self._crawl_delay: float | None = None
        self._sitemaps: list[str] = []
        self._loaded = False

    async def load(self) -> None:
        """Fetch and parse robots.txt from domain."""
        url = f"{self._scheme}://{self._domain}/robots.txt"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    self._parse(resp.text)
        except (httpx.HTTPError, Exception):
            pass  # Allow all on fetch failure
        self._loaded = True

    def _parse(self, text: str) -> None:
        """Parse robots.txt content."""
        in_our_section = False
        seen_any_section = False

        for raw_line in text.splitlines():
            line = raw_line.split("#")[0].strip()
            if not line:
                continue

            if line.lower().startswith("user-agent:"):
                agent = line.split(":", 1)[1].strip().lower()
                seen_any_section = True
                in_our_section = agent == "*" or "site2cli" in agent
                continue

            if line.lower().startswith("sitemap:"):
                self._sitemaps.append(line.split(":", 1)[1].strip())
                continue

            if not in_our_section and seen_any_section:
                continue

            if line.lower().startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    self._rules.append((path, False))
            elif line.lower().startswith("allow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    self._rules.append((path, True))
            elif line.lower().startswith("crawl-delay:"):
                try:
                    self._crawl_delay = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass

    def is_allowed(self, url: str) -> bool:
        """Check if crawling this URL is allowed."""
        if not self._rules:
            return True

        path = urlparse(url).path or "/"

        # Find the longest matching rule
        best_match = ""
        allowed = True

        for pattern, is_allowed in self._rules:
            # Convert robots.txt wildcards to regex
            regex_pattern = re.escape(pattern).replace(r"\*", ".*")
            if pattern.endswith("$"):
                regex_pattern = regex_pattern[:-2] + "$"

            if re.match(regex_pattern, path):
                if len(pattern) > len(best_match):
                    best_match = pattern
                    allowed = is_allowed

        return allowed

    @property
    def crawl_delay(self) -> float | None:
        return self._crawl_delay

    @property
    def sitemaps(self) -> list[str]:
        return self._sitemaps
