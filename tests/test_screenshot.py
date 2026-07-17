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


class TestCaptureKwargs:
    def test_capture_forwards_valid_context_kwargs(self):
        """take_screenshot's kwargs must bind to create_browser_context's signature.

        Regression test: v0.7.0 passed proxy=/session= which the factory
        rejected, making every `site2cli screenshot` invocation crash.
        """
        import inspect

        from site2cli.browser.context import create_browser_context

        sig = inspect.signature(create_browser_context)
        # These are exactly the kwargs screenshot/capture.py forwards.
        sig.bind(proxy=None, profile=None, session_manager=None, session_name=None)

    async def test_take_screenshot_with_stubbed_browser(self, tmp_path, monkeypatch):
        """End-to-end through take_screenshot with a stub context factory."""
        import inspect
        from contextlib import asynccontextmanager

        from site2cli.browser import context as ctx_mod
        from site2cli.screenshot.capture import take_screenshot

        real_sig = inspect.signature(ctx_mod.create_browser_context)
        out_file = tmp_path / "shot.png"

        class FakePage:
            def set_default_timeout(self, ms):
                pass

            async def set_viewport_size(self, size):
                pass

            async def goto(self, url, **kwargs):
                pass

            async def screenshot(self, **kwargs):
                from pathlib import Path

                Path(kwargs["path"]).write_bytes(b"\x89PNG fake")

        @asynccontextmanager
        async def fake_factory(*args, **kwargs):
            real_sig.bind(*args, **kwargs)  # reject kwargs the real factory rejects
            yield None, None, FakePage()

        monkeypatch.setattr(ctx_mod, "create_browser_context", fake_factory)

        result = await take_screenshot("http://example.com", output=str(out_file))
        assert out_file.exists()
        assert result.format == "png"
