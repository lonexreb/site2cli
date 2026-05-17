"""Tests for content chunking strategies."""

from site2cli.content.chunker import (
    Chunk,
    chunk_fixed,
    chunk_heading,
    chunk_sentence,
    chunk_text,
)


class TestChunkFixed:
    def test_empty_text(self):
        assert chunk_fixed("") == []

    def test_whitespace_only(self):
        assert chunk_fixed("   \n   ") == []

    def test_single_chunk(self):
        chunks = chunk_fixed("Hello world", chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0].text == "Hello world"
        assert chunks[0].index == 0
        assert chunks[0].total == 1

    def test_multiple_chunks(self):
        text = "A" * 500 + " " + "B" * 500
        chunks = chunk_fixed(text, chunk_size=300, overlap=0)
        assert len(chunks) > 1

    def test_overlap(self):
        text = "word " * 200  # 1000 chars
        chunks = chunk_fixed(text, chunk_size=400, overlap=100)
        assert len(chunks) > 2

    def test_metadata(self):
        chunks = chunk_fixed(
            "Hello world", chunk_size=100,
            url="https://example.com", title="Test",
        )
        assert chunks[0].url == "https://example.com"
        assert chunks[0].title == "Test"

    def test_sentence_boundary_break(self):
        text = "First sentence. Second sentence. Third sentence."
        chunks = chunk_fixed(text, chunk_size=35, overlap=0)
        # Should try to break at sentence boundary
        assert len(chunks) >= 2

    def test_indices_set(self):
        text = "x " * 500
        chunks = chunk_fixed(text, chunk_size=100, overlap=0)
        for i, c in enumerate(chunks):
            assert c.index == i
            assert c.total == len(chunks)


class TestChunkSentence:
    def test_empty_text(self):
        assert chunk_sentence("") == []

    def test_single_sentence(self):
        chunks = chunk_sentence("Hello world.", max_chunk_size=100)
        assert len(chunks) == 1

    def test_groups_sentences(self):
        text = "Short. Short. Short. Short. Short."
        chunks = chunk_sentence(text, max_chunk_size=25)
        assert len(chunks) > 1

    def test_long_sentence(self):
        text = "A" * 200 + "."
        chunks = chunk_sentence(text, max_chunk_size=100)
        # Long sentence stays as one chunk
        assert len(chunks) == 1

    def test_multiple_sentence_types(self):
        text = "Question? Exclamation! Statement."
        chunks = chunk_sentence(text, max_chunk_size=1000)
        assert len(chunks) == 1
        assert "Question?" in chunks[0].text

    def test_metadata(self):
        chunks = chunk_sentence(
            "Hello. World.", max_chunk_size=1000,
            url="https://example.com",
        )
        assert chunks[0].url == "https://example.com"


class TestChunkHeading:
    def test_empty_text(self):
        assert chunk_heading("") == []

    def test_no_headings(self):
        chunks = chunk_heading("Just plain text\nwith lines")
        assert len(chunks) == 1

    def test_splits_at_headings(self):
        text = "# Section 1\nContent 1\n# Section 2\nContent 2"
        chunks = chunk_heading(text)
        assert len(chunks) == 2
        assert chunks[0].section == "Section 1"
        assert chunks[1].section == "Section 2"

    def test_nested_headings(self):
        text = "# Main\nIntro\n## Sub\nDetail\n## Sub2\nMore"
        chunks = chunk_heading(text)
        assert len(chunks) >= 2

    def test_large_section_split(self):
        text = "# Big Section\n" + "word " * 500
        chunks = chunk_heading(text, max_chunk_size=200)
        assert len(chunks) > 1
        for c in chunks:
            assert c.section == "Big Section"

    def test_section_metadata(self):
        text = "# My Title\nSome content here"
        chunks = chunk_heading(text)
        assert chunks[0].section == "My Title"

    def test_preserves_heading_in_content(self):
        text = "# Title\nBody text"
        chunks = chunk_heading(text)
        assert "# Title" in chunks[0].text


class TestChunkText:
    def test_fixed_strategy(self):
        chunks = chunk_text("Hello world", strategy="fixed", chunk_size=100)
        assert len(chunks) == 1

    def test_sentence_strategy(self):
        chunks = chunk_text("A. B. C.", strategy="sentence", chunk_size=100)
        assert len(chunks) == 1

    def test_heading_strategy(self):
        text = "# A\nContent\n# B\nContent"
        chunks = chunk_text(text, strategy="heading")
        assert len(chunks) == 2

    def test_default_is_fixed(self):
        chunks = chunk_text("Hello", strategy="unknown_strategy")
        assert len(chunks) == 1  # Falls through to fixed


class TestChunkModel:
    def test_to_dict(self):
        c = Chunk(
            text="Hello", index=0, total=1,
            url="https://example.com", title="Test",
            section="Intro",
        )
        d = c.to_dict()
        assert d["text"] == "Hello"
        assert d["url"] == "https://example.com"
        assert d["section"] == "Intro"
        assert d["index"] == 0

    def test_to_dict_with_metadata(self):
        c = Chunk(
            text="Hello", metadata={"source": "web"},
        )
        d = c.to_dict()
        assert d["source"] == "web"
