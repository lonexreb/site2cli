"""HTML to markdown/text conversion for LLM-ready output."""

from __future__ import annotations

import re
from typing import Any


def html_to_markdown(html: str) -> str:
    """Convert HTML to markdown using markdownify.

    Falls back to a basic regex-based converter if markdownify is not installed.
    """
    try:
        from markdownify import markdownify as md

        return md(
            html,
            heading_style="ATX",
            bullets="-",
            strip=["script", "style", "nav", "footer", "header", "aside"],
        ).strip()
    except ImportError:
        return _fallback_html_to_markdown(html)


def html_to_text(html: str) -> str:
    """Convert HTML to plain text, stripping all tags."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_main_content(html: str) -> str:
    """Extract the main content area from HTML, removing boilerplate.

    Looks for <main>, <article>, or role="main" elements. Falls back to <body>.
    """
    # Try to find main content containers
    for pattern in [
        r"<main[^>]*>(.*?)</main>",
        r'<article[^>]*>(.*?)</article>',
        r'<div[^>]*role="main"[^>]*>(.*?)</div>',
        r'<div[^>]*id="content"[^>]*>(.*?)</div>',
        r'<div[^>]*id="main"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
    ]:
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1)

    # Fallback: strip nav/header/footer from body
    body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    content = body_match.group(1) if body_match else html

    for tag in ["nav", "header", "footer", "aside", "script", "style"]:
        content = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>", "", content, flags=re.DOTALL | re.IGNORECASE
        )
    return content


def convert_page(
    html: str,
    output_format: str = "markdown",
    main_content_only: bool = True,
) -> str:
    """Convert an HTML page to the specified format.

    Args:
        html: Raw HTML string.
        output_format: One of "markdown", "text", "html".
        main_content_only: If True, extract main content area first.

    Returns:
        Converted content string.
    """
    content = extract_main_content(html) if main_content_only else html

    if output_format == "markdown":
        return html_to_markdown(content)
    elif output_format == "text":
        return html_to_text(content)
    elif output_format == "html":
        return content.strip()
    else:
        raise ValueError(f"Unknown output format: {output_format}. Use markdown, text, or html.")


def _fallback_html_to_markdown(html: str) -> str:
    """Basic regex-based HTML to markdown when markdownify is unavailable."""
    text = html

    # Remove script and style
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Headings
    for i in range(1, 7):
        text = re.sub(
            rf"<h{i}[^>]*>(.*?)</h{i}>",
            lambda m, level=i: f"\n{'#' * level} {m.group(1).strip()}\n",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

    # Bold and italic
    text = re.sub(r"<(strong|b)[^>]*>(.*?)</\1>", r"**\2**", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(em|i)[^>]*>(.*?)</\1>", r"*\2*", text, flags=re.DOTALL | re.IGNORECASE)

    # Links
    text = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        r"[\2](\1)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # List items
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", text, flags=re.DOTALL | re.IGNORECASE)

    # Code blocks
    text = re.sub(
        r"<pre[^>]*><code[^>]*>(.*?)</code></pre>",
        r"\n```\n\1\n```\n",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL | re.IGNORECASE)

    # Paragraphs and line breaks
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div)>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<hr\s*/?>", "\n---\n", text, flags=re.IGNORECASE)

    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)

    # Clean up entities
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_for_llm(content: str, url: str | None = None, max_chars: int = 50_000) -> str:
    """Format content for optimal LLM consumption.

    Adds URL context, truncates to fit token limits, and cleans whitespace.
    """
    parts = []
    if url:
        parts.append(f"Source: {url}\n")

    parts.append(content)
    result = "\n".join(parts)

    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n[Content truncated]"

    return result


def fetch_and_convert(
    url: str,
    output_format: str = "markdown",
    main_content_only: bool = True,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    proxy: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Fetch a URL and convert its content.

    Args:
        url: URL to fetch.
        output_format: Output format (markdown, text, html).
        main_content_only: Extract main content only.
        headers: Additional HTTP headers.
        cookies: Cookies to send.
        proxy: Proxy URL.
        timeout: Request timeout in seconds.

    Returns:
        Dict with content, url, status_code, and content_type.
    """
    import httpx

    client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy
    if headers:
        client_kwargs["headers"] = headers
    if cookies:
        client_kwargs["cookies"] = cookies

    with httpx.Client(**client_kwargs) as client:
        response = client.get(url)

    content_type = response.headers.get("content-type", "")

    if "json" in content_type:
        return {
            "content": response.text,
            "url": str(response.url),
            "status_code": response.status_code,
            "content_type": "json",
            "format": "json",
        }

    converted = convert_page(response.text, output_format, main_content_only)

    return {
        "content": converted,
        "url": str(response.url),
        "status_code": response.status_code,
        "content_type": content_type.split(";")[0].strip(),
        "format": output_format,
    }
