"""PDF parsing and text extraction."""

from __future__ import annotations

from pathlib import Path


def pdf_to_text(source: str | Path) -> str:
    """Extract text from a PDF file or URL.

    Args:
        source: Local file path or URL to a PDF.

    Returns:
        Extracted text content.

    Raises:
        ImportError: If pdfplumber is not installed.
        FileNotFoundError: If local file doesn't exist.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "PDF parsing requires pdfplumber. "
            "Install with: pip install site2cli[rag]"
        )

    path = _resolve_source(source)

    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)

    return "\n\n".join(pages)


def pdf_to_markdown(source: str | Path) -> str:
    """Extract text from a PDF and format as markdown.

    Each page becomes a section. Tables are preserved where possible.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "PDF parsing requires pdfplumber. "
            "Install with: pip install site2cli[rag]"
        )

    path = _resolve_source(source)

    sections: list[str] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            parts: list[str] = []
            parts.append(f"## Page {i}")

            # Extract tables
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    if not table:
                        continue
                    # Convert to markdown table
                    header = table[0]
                    md_header = "| " + " | ".join(
                        str(c or "") for c in header
                    ) + " |"
                    md_sep = "| " + " | ".join(
                        "---" for _ in header
                    ) + " |"
                    rows = []
                    for row in table[1:]:
                        rows.append(
                            "| " + " | ".join(
                                str(c or "") for c in row
                            ) + " |"
                        )
                    parts.append(
                        md_header + "\n" + md_sep + "\n" +
                        "\n".join(rows)
                    )

            # Extract remaining text
            text = page.extract_text()
            if text:
                parts.append(text)

            sections.append("\n\n".join(parts))

    return "\n\n".join(sections)


def pdf_page_count(source: str | Path) -> int:
    """Get the number of pages in a PDF."""
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "PDF parsing requires pdfplumber. "
            "Install with: pip install site2cli[rag]"
        )

    path = _resolve_source(source)
    with pdfplumber.open(path) as pdf:
        return len(pdf.pages)


def _resolve_source(source: str | Path) -> Path:
    """Resolve a source to a local file path, downloading if URL."""
    path = Path(source) if isinstance(source, str) else source

    if str(source).startswith(("http://", "https://")):
        import tempfile

        import httpx

        resp = httpx.get(str(source), follow_redirects=True, timeout=30)
        resp.raise_for_status()

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(resp.content)
        tmp.close()
        return Path(tmp.name)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    return path
