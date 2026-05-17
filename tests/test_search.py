"""Tests for web search functionality."""

from unittest.mock import MagicMock, patch

import pytest

from site2cli.search.engine import SearchResult


class TestSearchResult:
    def test_defaults(self):
        r = SearchResult(title="Test", url="https://example.com")
        assert r.snippet == ""
        assert r.content == ""
        assert r.metadata == {}

    def test_to_dict_minimal(self):
        r = SearchResult(title="Test", url="https://example.com")
        d = r.to_dict()
        assert d["title"] == "Test"
        assert d["url"] == "https://example.com"
        assert "content" not in d  # Empty content excluded

    def test_to_dict_with_content(self):
        r = SearchResult(
            title="Test", url="https://example.com",
            content="Hello world",
        )
        d = r.to_dict()
        assert d["content"] == "Hello world"

    def test_to_dict_with_metadata(self):
        r = SearchResult(
            title="Test", url="https://example.com",
            metadata={"status_code": 200},
        )
        d = r.to_dict()
        assert d["status_code"] == 200

    def test_snippet(self):
        r = SearchResult(
            title="Test", url="https://example.com",
            snippet="A short description",
        )
        assert r.snippet == "A short description"


class TestSearchDuckDuckGo:
    @pytest.mark.asyncio
    async def test_import_error(self):
        """Verify helpful error when duckduckgo-search not installed."""
        with patch.dict("sys.modules", {"duckduckgo_search": None}):
            from site2cli.search.engine import search_duckduckgo

            with pytest.raises(ImportError, match="duckduckgo-search"):
                await search_duckduckgo("test query")

    @pytest.mark.asyncio
    async def test_returns_results(self):
        """Test with mocked DuckDuckGo."""
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=None)
        mock_ddgs.text = MagicMock(return_value=[
            {"title": "Result 1", "href": "https://a.com", "body": "Snippet 1"},
            {"title": "Result 2", "href": "https://b.com", "body": "Snippet 2"},
        ])

        mock_module = MagicMock()
        mock_module.DDGS = MagicMock(return_value=mock_ddgs)

        with patch.dict("sys.modules", {"duckduckgo_search": mock_module}):
            import importlib

            from site2cli.search import engine
            importlib.reload(engine)

            results = await engine.search_duckduckgo("test", max_results=2)

        assert len(results) == 2
        assert results[0].title == "Result 1"
        assert results[0].url == "https://a.com"
        assert results[1].snippet == "Snippet 2"


class TestSearchCLI:
    def test_cli_help(self):
        from typer.testing import CliRunner

        from site2cli.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0
        assert "search" in result.output.lower()
        assert "--scrape" in result.output
        assert "--extract" in result.output

    def test_cli_missing_query(self):
        from typer.testing import CliRunner

        from site2cli.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["search"])
        assert result.exit_code != 0
