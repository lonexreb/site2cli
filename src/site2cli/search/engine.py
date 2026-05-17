"""Web search engines for site2cli search command."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str = ""
    content: str = ""  # Populated after scraping
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
        }
        if self.content:
            d["content"] = self.content
        if self.metadata:
            d.update(self.metadata)
        return d


async def search_duckduckgo(
    query: str,
    max_results: int = 10,
) -> list[SearchResult]:
    """Search using DuckDuckGo (no API key required).

    Args:
        query: Search query string.
        max_results: Maximum number of results.

    Returns:
        List of SearchResult objects.

    Raises:
        ImportError: If duckduckgo-search is not installed.
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        raise ImportError(
            "Web search requires duckduckgo-search. "
            "Install with: pip install site2cli[search]"
        )

    results: list[SearchResult] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                snippet=r.get("body", ""),
            ))

    return results


async def search_and_scrape(
    query: str,
    max_results: int = 5,
    output_format: str = "markdown",
    main_content_only: bool = True,
    proxy: str | None = None,
) -> list[SearchResult]:
    """Search the web, then scrape and convert top results.

    Args:
        query: Search query string.
        max_results: Number of results to scrape.
        output_format: Content format (markdown, text).
        main_content_only: Extract main content only.
        proxy: Proxy URL for requests.

    Returns:
        List of SearchResult with content populated.
    """
    results = await search_duckduckgo(query, max_results=max_results)

    from site2cli.content.converter import fetch_and_convert

    for result in results:
        try:
            converted = fetch_and_convert(
                result.url,
                output_format=output_format,
                main_content_only=main_content_only,
                proxy=proxy,
            )
            result.content = converted.get("content", "")
            result.metadata["status_code"] = converted.get(
                "status_code", 0
            )
        except Exception:
            result.content = ""

    return results


async def search_and_extract(
    query: str,
    prompt: str | None = None,
    schema: str | dict | None = None,
    max_results: int = 5,
    proxy: str | None = None,
) -> list[dict]:
    """Search, scrape, and extract structured data from results.

    Args:
        query: Search query string.
        prompt: Extraction prompt.
        schema: JSON Schema for extraction.
        max_results: Number of results to process.
        proxy: Proxy URL.

    Returns:
        List of extraction results.
    """
    results = await search_duckduckgo(query, max_results=max_results)

    from site2cli.extract.extractor import extract

    extractions: list[dict] = []
    for result in results:
        try:
            extraction = await extract(
                result.url,
                prompt=prompt,
                schema=schema,
                proxy=proxy,
            )
            extractions.append({
                "url": result.url,
                "title": result.title,
                "success": extraction.success,
                "data": extraction.data,
                "error": extraction.error,
            })
        except Exception as e:
            extractions.append({
                "url": result.url,
                "title": result.title,
                "success": False,
                "data": None,
                "error": str(e),
            })

    return extractions
