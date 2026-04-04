"""Tests for screenshot capture."""

from datetime import datetime

from site2cli.models import ScreenshotResult


class TestScreenshotResult:
    def test_model_defaults(self):
        r = ScreenshotResult(url="https://example.com", path="/tmp/test.png")
        assert r.format == "png"
        assert r.full_page is True
        assert r.selector is None
        assert r.width == 0
        assert r.height == 0

    def test_model_with_selector(self):
        r = ScreenshotResult(
            url="https://example.com",
            path="/tmp/test.png",
            selector=".content",
            full_page=False,
        )
        assert r.selector == ".content"
        assert r.full_page is False

    def test_model_jpeg(self):
        r = ScreenshotResult(
            url="https://example.com",
            path="/tmp/test.jpg",
            format="jpeg",
        )
        assert r.format == "jpeg"

    def test_model_dimensions(self):
        r = ScreenshotResult(
            url="https://example.com",
            path="/tmp/test.png",
            width=1920,
            height=1080,
        )
        assert r.width == 1920
        assert r.height == 1080

    def test_model_captured_at(self):
        r = ScreenshotResult(url="https://example.com", path="/tmp/test.png")
        assert isinstance(r.captured_at, datetime)

    def test_model_serialization(self):
        r = ScreenshotResult(url="https://example.com", path="/tmp/test.png")
        data = r.model_dump(mode="json")
        assert data["url"] == "https://example.com"
        assert data["path"] == "/tmp/test.png"


class TestScreenshotCLI:
    def test_cli_help(self):
        from typer.testing import CliRunner

        from site2cli.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["screenshot", "--help"])
        assert result.exit_code == 0
        assert "screenshot" in result.output.lower()

    def test_cli_missing_url(self):
        from typer.testing import CliRunner

        from site2cli.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["screenshot"])
        assert result.exit_code != 0
