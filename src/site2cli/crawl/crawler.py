"""Full site crawler with BFS, resume, and streaming."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections import deque
from datetime import datetime
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx

from site2cli.crawl.links import extract_links, is_same_domain, normalize_url
from site2cli.crawl.robots import RobotsChecker
from site2cli.models import CrawlJob, CrawlPage, CrawlStatus


class SiteCrawler:
    """Async BFS site crawler."""

    def __init__(
        self,
        start_url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        output_format: str = "markdown",
        main_content_only: bool = True,
        respect_robots: bool = True,
        sitemap_only: bool = False,
        delay_ms: int = 100,
        concurrent: int = 5,
        proxy: str | None = None,
        user_agent: str = "site2cli/0.6.0",
        job_id: str | None = None,
        visited: set[str] | None = None,
    ) -> None:
        self.start_url = normalize_url(start_url) or start_url
        parsed = urlparse(self.start_url)
        self.domain = parsed.hostname or ""
        self.scheme = parsed.scheme or "https"
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.output_format = output_format
        self.main_content_only = main_content_only
        self.respect_robots = respect_robots
        self.sitemap_only = sitemap_only
        self.delay_ms = delay_ms
        self.concurrent = concurrent
        self.proxy = proxy
        self.user_agent = user_agent
        self.job_id = job_id or str(uuid.uuid4())
        self._visited: set[str] = visited or set()
        self._robots: RobotsChecker | None = None
        self._semaphore = asyncio.Semaphore(concurrent)
        self.pages_crawled = 0

    def get_job(self) -> CrawlJob:
        return CrawlJob(
            id=self.job_id,
            start_url=self.start_url,
            domain=self.domain,
            max_depth=self.max_depth,
            max_pages=self.max_pages,
            status=CrawlStatus.RUNNING,
            pages_crawled=self.pages_crawled,
            output_format=self.output_format,
            main_content_only=self.main_content_only,
            respect_robots=self.respect_robots,
        )

    async def crawl(self) -> AsyncIterator[CrawlPage]:
        """Crawl the site using BFS, yielding pages as they're crawled."""
        # Load robots.txt
        if self.respect_robots:
            self._robots = RobotsChecker(self.domain, self.scheme)
            await self._robots.load()

        # BFS queue: (url, depth)
        queue: deque[tuple[str, int]] = deque()
        queue.append((self.start_url, 0))

        while queue and self.pages_crawled < self.max_pages:
            url, depth = queue.popleft()

            normalized = normalize_url(url)
            if not normalized or normalized in self._visited:
                continue
            if depth > self.max_depth:
                continue
            if not is_same_domain(normalized, self.domain):
                continue
            if self._robots and not self._robots.is_allowed(normalized):
                continue

            self._visited.add(normalized)

            if self.sitemap_only:
                self.pages_crawled += 1
                yield CrawlPage(url=normalized, depth=depth)
                # Still discover links for sitemap
                try:
                    html = await self._fetch_html(normalized)
                    if html:
                        links = extract_links(html, normalized)
                        for link in links:
                            nl = normalize_url(link)
                            if nl and nl not in self._visited and is_same_domain(nl, self.domain):
                                queue.append((nl, depth + 1))
                except Exception:
                    pass
                continue

            # Fetch and process
            page = await self._fetch_page(normalized, depth)
            self.pages_crawled += 1
            yield page

            # Discover links from this page
            if page.error is None and depth < self.max_depth:
                try:
                    html = await self._fetch_html(normalized)
                    if html:
                        links = extract_links(html, normalized)
                        page.links_found = len(links)
                        for link in links:
                            nl = normalize_url(link)
                            if nl and nl not in self._visited and is_same_domain(nl, self.domain):
                                queue.append((nl, depth + 1))
                except Exception:
                    pass

            if self.delay_ms > 0:
                await asyncio.sleep(self.delay_ms / 1000)

    async def _fetch_html(self, url: str) -> str | None:
        """Fetch raw HTML from a URL."""
        try:
            async with self._semaphore:
                kwargs: dict = {
                    "follow_redirects": True,
                    "timeout": 15,
                    "headers": {"User-Agent": self.user_agent},
                }
                if self.proxy:
                    kwargs["proxy"] = self.proxy
                async with httpx.AsyncClient(**kwargs) as client:
                    resp = await client.get(url)
                    ct = resp.headers.get("content-type", "")
                    if "text/html" in ct or "application/xhtml" in ct:
                        return resp.text
        except Exception:
            pass
        return None

    async def _fetch_page(self, url: str, depth: int) -> CrawlPage:
        """Fetch a page and convert its content."""
        try:
            async with self._semaphore:
                kwargs: dict = {
                    "follow_redirects": True,
                    "timeout": 15,
                    "headers": {"User-Agent": self.user_agent},
                }
                if self.proxy:
                    kwargs["proxy"] = self.proxy
                async with httpx.AsyncClient(**kwargs) as client:
                    resp = await client.get(url)

            ct = resp.headers.get("content-type", "")
            html = resp.text if ("text/html" in ct or "application/xhtml" in ct) else ""
            content_hash = hashlib.sha256(html.encode()).hexdigest() if html else ""

            # Extract title
            title = ""
            if html:
                import re
                m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                if m:
                    title = m.group(1).strip()

            # Convert content
            content = ""
            if html and self.output_format != "html":
                from site2cli.content.converter import convert_page, extract_main_content

                src = extract_main_content(html) if self.main_content_only else html
                is_md = self.output_format in ("markdown", "jsonl")
                fmt = "markdown" if is_md else self.output_format
                content = convert_page(src, output_format=fmt)
            elif html:
                from site2cli.content.converter import extract_main_content
                content = extract_main_content(html) if self.main_content_only else html

            return CrawlPage(
                url=url,
                depth=depth,
                status_code=resp.status_code,
                content_type=ct.split(";")[0].strip(),
                title=title,
                content=content,
                content_hash=content_hash,
                crawled_at=datetime.utcnow(),
            )

        except Exception as e:
            return CrawlPage(
                url=url,
                depth=depth,
                error=str(e),
                crawled_at=datetime.utcnow(),
            )
