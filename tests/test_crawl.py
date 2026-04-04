"""Tests for site crawler — link extraction, BFS, robots, formats."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from site2cli.crawl.links import extract_links, is_same_domain, normalize_url
from site2cli.models import CrawlJob, CrawlPage, CrawlStatus

# --- Link Extraction Tests ---


class TestExtractLinks:
    def test_absolute_urls(self):
        html = '<a href="https://example.com/page1">Link</a><a href="https://example.com/page2">Link</a>'
        links = extract_links(html, "https://example.com")
        assert "https://example.com/page1" in links
        assert "https://example.com/page2" in links

    def test_relative_urls(self):
        html = '<a href="/about">About</a><a href="contact">Contact</a>'
        links = extract_links(html, "https://example.com/")
        assert "https://example.com/about" in links
        assert "https://example.com/contact" in links

    def test_deduplication(self):
        html = '<a href="/page">A</a><a href="/page">B</a><a href="/page">C</a>'
        links = extract_links(html, "https://example.com")
        assert len(links) == 1

    def test_filters_non_http(self):
        html = '''
        <a href="mailto:test@example.com">Email</a>
        <a href="javascript:void(0)">JS</a>
        <a href="tel:+1234567890">Phone</a>
        <a href="https://example.com/page">Real</a>
        '''
        links = extract_links(html, "https://example.com")
        assert len(links) == 1
        assert "https://example.com/page" in links

    def test_strips_fragments(self):
        html = '<a href="/page#section">Link</a>'
        links = extract_links(html, "https://example.com")
        assert "https://example.com/page" in links

    def test_filters_static_assets(self):
        html = '''
        <a href="/image.png">Img</a>
        <a href="/style.css">CSS</a>
        <a href="/script.js">JS</a>
        <a href="/page">Page</a>
        '''
        links = extract_links(html, "https://example.com")
        assert len(links) == 1
        assert "https://example.com/page" in links

    def test_empty_href(self):
        html = '<a href="">Empty</a><a href="#">Hash</a>'
        links = extract_links(html, "https://example.com")
        assert len(links) == 0

    def test_mixed_quotes(self):
        html = """<a href='/single'>A</a><a href="/double">B</a>"""
        links = extract_links(html, "https://example.com")
        assert len(links) == 2


class TestNormalizeUrl:
    def test_strips_fragment(self):
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_strips_trailing_slash(self):
        assert normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_keeps_root_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_lowercase_host(self):
        assert normalize_url("https://EXAMPLE.COM/page") == "https://example.com/page"

    def test_strips_default_port_http(self):
        assert normalize_url("http://example.com:80/page") == "http://example.com/page"

    def test_strips_default_port_https(self):
        assert normalize_url("https://example.com:443/page") == "https://example.com/page"

    def test_keeps_non_default_port(self):
        assert normalize_url("https://example.com:8080/page") == "https://example.com:8080/page"

    def test_non_http_returns_empty(self):
        assert normalize_url("ftp://example.com/file") == ""


class TestIsSameDomain:
    def test_exact_match(self):
        assert is_same_domain("https://example.com/page", "example.com") is True

    def test_subdomain(self):
        assert is_same_domain("https://blog.example.com/post", "example.com") is True

    def test_different_domain(self):
        assert is_same_domain("https://other.com/page", "example.com") is False

    def test_case_insensitive(self):
        assert is_same_domain("https://EXAMPLE.COM/page", "example.com") is True


# --- CrawlPage Model Tests ---


class TestCrawlModels:
    def test_crawl_page_defaults(self):
        p = CrawlPage(url="https://example.com")
        assert p.depth == 0
        assert p.status_code == 0
        assert p.error is None
        assert isinstance(p.crawled_at, datetime)

    def test_crawl_page_with_error(self):
        p = CrawlPage(url="https://example.com", error="Connection refused")
        assert p.error == "Connection refused"

    def test_crawl_job_defaults(self):
        j = CrawlJob(id="test-id", start_url="https://example.com", domain="example.com")
        assert j.max_depth == 3
        assert j.max_pages == 100
        assert j.status == CrawlStatus.PENDING
        assert j.respect_robots is True

    def test_crawl_status_values(self):
        assert CrawlStatus.PENDING == "pending"
        assert CrawlStatus.RUNNING == "running"
        assert CrawlStatus.COMPLETED == "completed"
        assert CrawlStatus.FAILED == "failed"

    def test_crawl_job_serialization(self):
        j = CrawlJob(id="test", start_url="https://example.com", domain="example.com")
        data = j.model_dump(mode="json")
        assert data["id"] == "test"
        assert data["status"] == "pending"


# --- Crawler Tests (mocked httpx) ---


class TestSiteCrawler:
    def test_crawler_init(self):
        from site2cli.crawl.crawler import SiteCrawler

        c = SiteCrawler("https://example.com", max_depth=2, max_pages=10)
        assert c.domain == "example.com"
        assert c.max_depth == 2
        assert c.max_pages == 10

    def test_crawler_job(self):
        from site2cli.crawl.crawler import SiteCrawler

        c = SiteCrawler("https://example.com")
        job = c.get_job()
        assert job.domain == "example.com"
        assert job.status == CrawlStatus.RUNNING

    @pytest.mark.asyncio
    async def test_crawl_single_page(self):
        from site2cli.crawl.crawler import SiteCrawler

        c = SiteCrawler("https://example.com", max_depth=0, max_pages=1)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = "<html><head><title>Test</title></head><body>Hello</body></html>"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("site2cli.crawl.crawler.httpx.AsyncClient", return_value=mock_client):
            pages = []
            async for page in c.crawl():
                pages.append(page)

        assert len(pages) == 1
        assert pages[0].url == "https://example.com/"
        assert pages[0].status_code == 200

    @pytest.mark.asyncio
    async def test_crawl_respects_max_pages(self):
        from site2cli.crawl.crawler import SiteCrawler

        c = SiteCrawler(
            "https://example.com", max_depth=5, max_pages=3,
            delay_ms=0, sitemap_only=True, respect_robots=False,
        )

        html = """<html><body>
        <a href="/page1">1</a><a href="/page2">2</a>
        <a href="/page3">3</a><a href="/page4">4</a>
        <a href="/page5">5</a>
        </body></html>"""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = html

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("site2cli.crawl.crawler.httpx.AsyncClient", return_value=mock_client):
            pages = []
            async for page in c.crawl():
                pages.append(page)

        assert len(pages) <= 3

    @pytest.mark.asyncio
    async def test_crawl_deduplication(self):
        from site2cli.crawl.crawler import SiteCrawler

        visited = {"https://example.com/already-seen"}
        c = SiteCrawler(
            "https://example.com/already-seen",
            max_depth=0, max_pages=10, visited=visited,
            respect_robots=False, delay_ms=0,
        )

        pages = []
        async for page in c.crawl():
            pages.append(page)

        assert len(pages) == 0  # Already visited


# --- CLI Tests ---


class TestCrawlCLI:
    def test_cli_help(self):
        from typer.testing import CliRunner

        from site2cli.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["crawl", "--help"])
        assert result.exit_code == 0
        assert "crawl" in result.output.lower()
