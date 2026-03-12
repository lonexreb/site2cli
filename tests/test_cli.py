"""Tests for CLI commands."""

from typer.testing import CliRunner

from webcli.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "WebCLI v" in result.output


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "webcli" in result.output.lower()


def test_sites_list_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from webcli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["sites", "list"])
    assert result.exit_code == 0
    assert "No sites discovered" in result.output


def test_sites_show_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from webcli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["sites", "show", "nonexistent.com"])
    assert result.exit_code == 1


def test_config_show(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from webcli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "data_dir" in result.output
