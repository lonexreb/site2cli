"""Tests for CLI commands."""

from typer.testing import CliRunner

from site2cli.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "site2cli v" in result.output


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "site2cli" in result.output.lower()


def test_sites_list_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from site2cli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["sites", "list"])
    assert result.exit_code == 0
    assert "No sites discovered" in result.output


def test_sites_show_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from site2cli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["sites", "show", "nonexistent.com"])
    assert result.exit_code == 1


def test_config_show(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from site2cli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "data_dir" in result.output


# --- Additional CLI tests ---


def test_sites_remove_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from site2cli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["sites", "remove", "nonexistent.com"])
    assert "not found" in result.output.lower()


def test_setup_command(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from site2cli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 0
    assert "Setup complete" in result.output
    assert "Python" in result.output


def test_config_set(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from site2cli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["config", "set", "log_level", "DEBUG"])
    assert result.exit_code == 0
    assert "DEBUG" in result.output


def test_auth_subcommands_exist():
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    assert "login" in result.output
    assert "logout" in result.output


def test_mcp_subcommands_exist():
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "generate" in result.output
    assert "serve" in result.output


def test_health_subcommands_exist():
    result = runner.invoke(app, ["health", "--help"])
    assert result.exit_code == 0
    assert "check" in result.output
    assert "repair" in result.output


def test_community_subcommands_exist():
    result = runner.invoke(app, ["community", "--help"])
    assert result.exit_code == 0
    assert "export" in result.output
    assert "import" in result.output
    assert "list" in result.output


def test_community_list_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from site2cli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["community", "list"])
    assert result.exit_code == 0
    assert "No community specs" in result.output


def test_mcp_generate_unknown_site(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from site2cli.config import reset_config
    reset_config()

    result = runner.invoke(app, ["mcp", "generate", "nonexistent.com"])
    assert result.exit_code == 1


def test_discover_help():
    result = runner.invoke(app, ["discover", "--help"])
    assert result.exit_code == 0
    assert "URL" in result.output


def test_run_help():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "domain" in result.output.lower()
