"""Tests for PDF parsing (without pdfplumber dependency)."""

import sys

import pytest


def _force_pdfplumber_missing(monkeypatch) -> None:
    """Make `import pdfplumber` raise ImportError and force a fresh pdf import."""
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    # Drop any cached pdf module so the next import re-binds pdfplumber=None.
    monkeypatch.delitem(sys.modules, "site2cli.content.pdf", raising=False)


class TestPdfImportError:
    def test_pdf_to_text_requires_pdfplumber(self, monkeypatch):
        """Verify helpful error when pdfplumber not installed."""
        _force_pdfplumber_missing(monkeypatch)
        from site2cli.content import pdf

        with pytest.raises(ImportError, match="pdfplumber"):
            pdf.pdf_to_text("/nonexistent.pdf")

    def test_pdf_to_markdown_requires_pdfplumber(self, monkeypatch):
        _force_pdfplumber_missing(monkeypatch)
        from site2cli.content import pdf

        with pytest.raises(ImportError, match="pdfplumber"):
            pdf.pdf_to_markdown("/nonexistent.pdf")

    def test_pdf_page_count_requires_pdfplumber(self, monkeypatch):
        _force_pdfplumber_missing(monkeypatch)
        from site2cli.content import pdf

        with pytest.raises(ImportError, match="pdfplumber"):
            pdf.pdf_page_count("/nonexistent.pdf")


class TestPdfResolveSource:
    def test_file_not_found(self):
        from site2cli.content.pdf import _resolve_source

        with pytest.raises(FileNotFoundError):
            _resolve_source("/absolutely/nonexistent/file.pdf")

    def test_local_file(self, tmp_path):
        from site2cli.content.pdf import _resolve_source

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        result = _resolve_source(pdf_file)
        assert result == pdf_file


class TestPdfCLI:
    def test_chunk_command_help(self):
        from typer.testing import CliRunner

        from site2cli.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["chunk", "--help"])
        assert result.exit_code == 0
        assert "chunk" in result.output.lower()
        assert "pdf" in result.output.lower() or "file" in result.output.lower()
