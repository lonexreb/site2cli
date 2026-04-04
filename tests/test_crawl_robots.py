"""Tests for robots.txt parser."""

import pytest

from site2cli.crawl.robots import RobotsChecker


class TestRobotsParser:
    def _make_checker(self, text: str) -> RobotsChecker:
        checker = RobotsChecker("example.com")
        checker._parse(text)
        checker._loaded = True
        return checker

    def test_empty_file(self):
        checker = self._make_checker("")
        assert checker.is_allowed("https://example.com/anything") is True

    def test_disallow_all(self):
        checker = self._make_checker("User-agent: *\nDisallow: /")
        assert checker.is_allowed("https://example.com/page") is False
        assert checker.is_allowed("https://example.com/") is False

    def test_disallow_path(self):
        checker = self._make_checker("User-agent: *\nDisallow: /private/")
        assert checker.is_allowed("https://example.com/private/secret") is False
        assert checker.is_allowed("https://example.com/public/page") is True

    def test_allow_override(self):
        checker = self._make_checker(
            "User-agent: *\nDisallow: /private/\nAllow: /private/public"
        )
        assert checker.is_allowed("https://example.com/private/public") is True
        assert checker.is_allowed("https://example.com/private/secret") is False

    def test_wildcard_pattern(self):
        checker = self._make_checker("User-agent: *\nDisallow: /admin*")
        assert checker.is_allowed("https://example.com/admin") is False
        assert checker.is_allowed("https://example.com/admin/dashboard") is False
        assert checker.is_allowed("https://example.com/about") is True

    def test_crawl_delay(self):
        checker = self._make_checker("User-agent: *\nCrawl-delay: 5")
        assert checker.crawl_delay == 5.0

    def test_crawl_delay_float(self):
        checker = self._make_checker("User-agent: *\nCrawl-delay: 0.5")
        assert checker.crawl_delay == 0.5

    def test_no_crawl_delay(self):
        checker = self._make_checker("User-agent: *\nDisallow: /private/")
        assert checker.crawl_delay is None

    def test_sitemap_extraction(self):
        checker = self._make_checker(
            "User-agent: *\nDisallow: /\nSitemap: https://example.com/sitemap.xml"
        )
        assert "https://example.com/sitemap.xml" in checker.sitemaps

    def test_multiple_sitemaps(self):
        checker = self._make_checker(
            "Sitemap: https://example.com/sitemap1.xml\n"
            "Sitemap: https://example.com/sitemap2.xml"
        )
        assert len(checker.sitemaps) == 2

    def test_comments_ignored(self):
        checker = self._make_checker(
            "# This is a comment\nUser-agent: *\nDisallow: /secret # hidden"
        )
        assert checker.is_allowed("https://example.com/secret") is False
        assert checker.is_allowed("https://example.com/public") is True

    def test_case_insensitive_directives(self):
        checker = self._make_checker("user-agent: *\ndisallow: /private/")
        assert checker.is_allowed("https://example.com/private/page") is False

    @pytest.mark.asyncio
    async def test_load_nonexistent(self):
        """Nonexistent robots.txt allows all."""
        from unittest.mock import AsyncMock, patch

        import httpx

        checker = RobotsChecker("nonexistent-domain-12345.com")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("No connection"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("site2cli.crawl.robots.httpx.AsyncClient", return_value=mock_client):
            await checker.load()

        assert checker.is_allowed("https://nonexistent-domain-12345.com/anything") is True
