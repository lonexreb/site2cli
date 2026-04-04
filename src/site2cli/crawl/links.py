"""Link extraction and normalization from HTML."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse

# Match href attributes in anchor tags
_HREF_RE = re.compile(r'<a\s[^>]*?href=["\']([^"\']+)["\']', re.IGNORECASE)

# Schemes to skip
_SKIP_SCHEMES = {"mailto", "javascript", "tel", "data", "ftp"}

# File extensions to skip (static assets)
_SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".zip", ".tar", ".gz", ".mp3", ".mp4", ".avi", ".mov",
}


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract and normalize all links from HTML.

    Args:
        html: Raw HTML content.
        base_url: Base URL for resolving relative links.

    Returns:
        Deduplicated list of normalized absolute URLs.
    """
    seen: set[str] = set()
    links: list[str] = []

    for match in _HREF_RE.finditer(html):
        href = match.group(1).strip()
        if not href or href.startswith("#"):
            continue

        # Skip non-HTTP schemes
        if ":" in href.split("/")[0]:
            scheme = href.split(":")[0].lower()
            if scheme in _SKIP_SCHEMES:
                continue

        # Resolve relative URLs
        absolute = urljoin(base_url, href)
        normalized = normalize_url(absolute)
        if not normalized:
            continue

        # Skip static assets
        path = urlparse(normalized).path.lower()
        ext = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
        if ext in _SKIP_EXTENSIONS:
            continue

        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)

    return links


def normalize_url(url: str) -> str:
    """Normalize URL for deduplication.

    - Lowercase scheme and host
    - Strip fragment
    - Strip trailing slash (except root path)
    - Strip default ports
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ""

    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    host = host.lower()

    # Strip default ports
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    netloc = host
    if port:
        netloc = f"{host}:{port}"

    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))


def is_same_domain(url: str, domain: str) -> bool:
    """Check if URL belongs to the same domain (including subdomains)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    domain = domain.lower()
    return host == domain or host.endswith(f".{domain}")
