"""Content chunking strategies for RAG pipelines."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A single chunk of content with metadata."""

    text: str
    index: int = 0
    total: int = 0
    url: str = ""
    title: str = ""
    section: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "index": self.index,
            "total": self.total,
            "url": self.url,
            "title": self.title,
            "section": self.section,
            **self.metadata,
        }


def chunk_fixed(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
    url: str = "",
    title: str = "",
) -> list[Chunk]:
    """Split text into fixed-size chunks with overlap.

    Args:
        text: Text to chunk.
        chunk_size: Maximum characters per chunk.
        overlap: Characters of overlap between chunks.
        url: Source URL for metadata.
        title: Source title for metadata.

    Returns:
        List of Chunk objects.
    """
    if not text.strip():
        return []

    # Clamp overlap so start always advances (avoids infinite loop when
    # callers pass overlap >= chunk_size, e.g. chunk_heading sub-splits).
    safe_overlap = min(overlap, max(chunk_size - 1, 0))

    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        # Try to break at a sentence boundary
        if end < len(text):
            # Look for sentence end within the last 20% of the chunk
            search_start = max(start, end - chunk_size // 5)
            last_period = text.rfind(". ", search_start, end)
            last_newline = text.rfind("\n", search_start, end)
            break_point = max(last_period, last_newline)
            if break_point > start:
                end = break_point + 1

        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(Chunk(
                text=chunk_text, url=url, title=title,
            ))

        if end >= len(text):
            break
        start = max(end - safe_overlap, start + 1)

    # Set indices
    for i, chunk in enumerate(chunks):
        chunk.index = i
        chunk.total = len(chunks)

    return chunks


def chunk_sentence(
    text: str,
    max_chunk_size: int = 1000,
    url: str = "",
    title: str = "",
) -> list[Chunk]:
    """Split text into chunks at sentence boundaries.

    Groups sentences until max_chunk_size is reached.
    """
    if not text.strip():
        return []

    # Split on sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks: list[Chunk] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if current_len + len(sentence) > max_chunk_size and current:
            chunks.append(Chunk(
                text=" ".join(current), url=url, title=title,
            ))
            current = []
            current_len = 0

        current.append(sentence)
        current_len += len(sentence) + 1

    if current:
        chunks.append(Chunk(
            text=" ".join(current), url=url, title=title,
        ))

    for i, chunk in enumerate(chunks):
        chunk.index = i
        chunk.total = len(chunks)

    return chunks


def chunk_heading(
    text: str,
    max_chunk_size: int = 2000,
    url: str = "",
    title: str = "",
) -> list[Chunk]:
    """Split markdown text at heading boundaries.

    Each heading starts a new chunk. If a section exceeds
    max_chunk_size, it is further split by fixed chunking.
    """
    if not text.strip():
        return []

    # Split on markdown headings
    sections: list[tuple[str, str]] = []  # (heading, content)
    current_heading = ""
    current_lines: list[str] = []

    for line in text.splitlines():
        if re.match(r"^#{1,6}\s+", line):
            if current_lines:
                sections.append((
                    current_heading,
                    "\n".join(current_lines).strip(),
                ))
            current_heading = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((
            current_heading,
            "\n".join(current_lines).strip(),
        ))

    chunks: list[Chunk] = []
    for heading, content in sections:
        full_text = f"{heading}\n{content}".strip() if heading else content
        if not full_text:
            continue

        if len(full_text) <= max_chunk_size:
            chunks.append(Chunk(
                text=full_text, url=url, title=title,
                section=heading.lstrip("# ").strip(),
            ))
        else:
            # Large section — sub-chunk by fixed size
            sub_chunks = chunk_fixed(
                full_text, chunk_size=max_chunk_size,
                overlap=200, url=url, title=title,
            )
            for sc in sub_chunks:
                sc.section = heading.lstrip("# ").strip()
            chunks.extend(sub_chunks)

    for i, chunk in enumerate(chunks):
        chunk.index = i
        chunk.total = len(chunks)

    return chunks


def chunk_text(
    text: str,
    strategy: str = "fixed",
    chunk_size: int = 1000,
    overlap: int = 200,
    url: str = "",
    title: str = "",
) -> list[Chunk]:
    """Chunk text using the specified strategy.

    Args:
        text: Text to chunk.
        strategy: One of "fixed", "sentence", "heading".
        chunk_size: Target chunk size in characters.
        overlap: Overlap for fixed strategy.
        url: Source URL for metadata.
        title: Source title for metadata.

    Returns:
        List of Chunk objects.
    """
    if strategy == "sentence":
        return chunk_sentence(
            text, max_chunk_size=chunk_size, url=url, title=title,
        )
    elif strategy == "heading":
        return chunk_heading(
            text, max_chunk_size=chunk_size, url=url, title=title,
        )
    else:
        return chunk_fixed(
            text, chunk_size=chunk_size, overlap=overlap,
            url=url, title=title,
        )
