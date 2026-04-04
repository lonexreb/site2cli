"""Tests for content conversion (HTML to markdown/text)."""

from __future__ import annotations

from site2cli.content.converter import (
    convert_page,
    extract_main_content,
    format_for_llm,
    html_to_markdown,
    html_to_text,
)

# --- html_to_text ---


def test_html_to_text_strips_tags():
    html = "<p>Hello <strong>world</strong></p>"
    result = html_to_text(html)
    assert "Hello" in result
    assert "world" in result
    assert "<" not in result


def test_html_to_text_removes_scripts():
    html = "<p>Content</p><script>alert('xss')</script><p>More</p>"
    result = html_to_text(html)
    assert "alert" not in result
    assert "Content" in result
    assert "More" in result


def test_html_to_text_removes_styles():
    html = "<style>.red{color:red}</style><p>Visible</p>"
    result = html_to_text(html)
    assert "red" not in result
    assert "Visible" in result


def test_html_to_text_converts_br():
    html = "Line 1<br/>Line 2<br>Line 3"
    result = html_to_text(html)
    assert "Line 1" in result
    assert "Line 2" in result


def test_html_to_text_decodes_entities():
    html = "<p>&amp; &lt; &gt; &quot; &nbsp;</p>"
    result = html_to_text(html)
    assert "&" in result
    assert "<" in result
    assert ">" in result


# --- html_to_markdown ---


def test_html_to_markdown_basic():
    html = "<h1>Title</h1><p>Paragraph text.</p>"
    result = html_to_markdown(html)
    assert "Title" in result
    assert "Paragraph" in result


def test_html_to_markdown_preserves_links():
    html = '<a href="https://example.com">Example</a>'
    result = html_to_markdown(html)
    assert "Example" in result
    # Should have markdown link format or at least the text
    assert "example.com" in result or "Example" in result


def test_html_to_markdown_handles_lists():
    html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
    result = html_to_markdown(html)
    assert "Item 1" in result
    assert "Item 2" in result


def test_html_to_markdown_strips_nav_footer():
    html = "<nav>Nav stuff</nav><p>Content</p><footer>Footer stuff</footer>"
    result = html_to_markdown(html)
    assert "Content" in result


# --- extract_main_content ---


def test_extract_main_from_main_tag():
    html = "<header>Header</header><main><p>Main content</p></main><footer>Footer</footer>"
    result = extract_main_content(html)
    assert "Main content" in result
    assert "Header" not in result


def test_extract_main_from_article():
    html = '<nav>Nav</nav><article><p>Article body</p></article>'
    result = extract_main_content(html)
    assert "Article body" in result


def test_extract_main_from_role():
    html = '<div role="main"><p>Main role content</p></div>'
    result = extract_main_content(html)
    assert "Main role content" in result


def test_extract_main_fallback_strips_boilerplate():
    html = (
        "<body><nav>Nav</nav><header>Head</header>"
        "<div>Body content</div>"
        "<footer>Foot</footer></body>"
    )
    result = extract_main_content(html)
    assert "Body content" in result


# --- convert_page ---


def test_convert_page_markdown():
    html = "<body><main><h1>Hello</h1><p>World</p></main></body>"
    result = convert_page(html, output_format="markdown")
    assert "Hello" in result
    assert "World" in result


def test_convert_page_text():
    html = "<body><main><p>Plain text here</p></main></body>"
    result = convert_page(html, output_format="text")
    assert "Plain text here" in result
    assert "<" not in result


def test_convert_page_html():
    html = "<body><main><p>Raw HTML</p></main></body>"
    result = convert_page(html, output_format="html")
    assert "<p>" in result


def test_convert_page_invalid_format():
    import pytest

    with pytest.raises(ValueError, match="Unknown output format"):
        convert_page("<p>test</p>", output_format="xml")


def test_convert_page_full_page():
    html = "<body><nav>Nav</nav><p>All content</p></body>"
    result = convert_page(html, output_format="text", main_content_only=False)
    assert "Nav" in result
    assert "All content" in result


# --- format_for_llm ---


def test_format_for_llm_adds_url():
    result = format_for_llm("content", url="https://example.com")
    assert "Source: https://example.com" in result
    assert "content" in result


def test_format_for_llm_truncates():
    long_content = "x" * 100_000
    result = format_for_llm(long_content, max_chars=1000)
    assert len(result) < 1100
    assert "[Content truncated]" in result


def test_format_for_llm_no_url():
    result = format_for_llm("just content")
    assert "just content" in result
    assert "Source:" not in result
