"""Tests for the configuration module."""

from pathlib import Path

import pytest

from site2cli.config import (
    BrowserConfig,
    Config,
    LLMConfig,
    _default_data_dir,
    get_config,
    reset_config,
)


def test_default_data_dir_uses_home(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    result = _default_data_dir()
    assert result == Path.home() / ".site2cli"


def test_xdg_data_home_overrides_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    result = _default_data_dir()
    assert result == tmp_path / "site2cli"


def test_get_config_returns_singleton(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    cfg1 = get_config()
    cfg2 = get_config()
    assert cfg1 is cfg2
    reset_config()


def test_reset_config_clears_singleton(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    cfg1 = get_config()
    reset_config()
    cfg2 = get_config()
    assert cfg1 is not cfg2
    reset_config()


def test_ensure_dirs_creates_directories(tmp_path):
    cfg = Config(data_dir=tmp_path / "site2cli")
    cfg.ensure_dirs()
    assert cfg.data_dir.is_dir()
    assert cfg.specs_dir.is_dir()
    assert cfg.clients_dir.is_dir()
    assert cfg.workflows_dir.is_dir()


def test_yaml_save_load_roundtrip(monkeypatch, tmp_path):
    # Point XDG_DATA_HOME at tmp_path so both save and load use the same data_dir.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    cfg = Config(
        data_dir=tmp_path / "site2cli",
        log_level="DEBUG",
        llm=LLMConfig(model="claude-3-haiku-20240307", max_tokens=1024),
        browser=BrowserConfig(headless=False, timeout_ms=5000),
    )
    cfg.save()
    assert cfg.config_path.exists()

    # Config.load() resolves data_dir via _default_data_dir() → tmp_path/site2cli.
    loaded = Config.load()
    assert loaded.log_level == "DEBUG"
    assert loaded.llm.model == "claude-3-haiku-20240307"
    assert loaded.llm.max_tokens == 1024
    assert loaded.browser.headless is False
    assert loaded.browser.timeout_ms == 5000


def test_llm_get_api_key_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-from-env")
    llm = LLMConfig()
    assert llm.get_api_key() == "test-key-from-env"


def test_llm_get_api_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm = LLMConfig()
    with pytest.raises(ValueError, match="No API key configured"):
        llm.get_api_key()
