"""Tests for ProfileManager (src/site2cli/auth/profiles.py)."""

from __future__ import annotations

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from site2cli.auth.profiles import ProfileManager
from site2cli.config import reset_config


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate data dirs so ProfileManager uses tmp_path."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    yield tmp_path
    reset_config()


@pytest.fixture()
def pm(isolated_env: Path) -> ProfileManager:
    return ProfileManager()


# ── detect_chrome_profiles ──────────────────────────────────────────


def test_detect_chrome_profiles_empty_when_no_chrome(
    pm: ProfileManager, monkeypatch: pytest.MonkeyPatch
):
    """Returns empty list when Chrome data dir does not exist."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    # No Chrome dir created -> should return []
    assert pm.detect_chrome_profiles() == []


def test_detect_chrome_profiles_finds_default(
    pm: ProfileManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Detects the Default Chrome profile directory."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    chrome_dir = tmp_path / "google-chrome"
    default_profile = chrome_dir / "Default"
    default_profile.mkdir(parents=True)
    (default_profile / "Preferences").write_text("{}")

    with patch.object(pm, "_chrome_data_dir", return_value=chrome_dir):
        profiles = pm.detect_chrome_profiles()

    assert len(profiles) >= 1
    assert any(p.name == "Default" for p in profiles)


def test_detect_chrome_profiles_finds_numbered(
    pm: ProfileManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Detects numbered Chrome profiles (Profile 1, Profile 2, etc.)."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    chrome_dir = tmp_path / "google-chrome"
    for name in ("Default", "Profile 1", "Profile 2"):
        p = chrome_dir / name
        p.mkdir(parents=True)
        (p / "Preferences").write_text("{}")

    with patch.object(pm, "_chrome_data_dir", return_value=chrome_dir):
        profiles = pm.detect_chrome_profiles()

    names = {p.name for p in profiles}
    assert "Default" in names
    assert "Profile 1" in names
    assert "Profile 2" in names


# ── detect_firefox_profiles ─────────────────────────────────────────


def test_detect_firefox_profiles_empty_when_no_firefox(
    pm: ProfileManager, monkeypatch: pytest.MonkeyPatch
):
    """Returns empty list when Firefox profiles dir does not exist."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert pm.detect_firefox_profiles() == []


# ── copy_profile ────────────────────────────────────────────────────


def test_copy_profile_copies_files_skips_cache(pm: ProfileManager, tmp_path: Path):
    """Copies profile dir but skips Cache subdirectories."""
    source = tmp_path / "source_profile"
    source.mkdir()
    (source / "Preferences").write_text('{"key": "value"}')
    (source / "Cookies").write_text("cookie_data")
    cache_dir = source / "Cache"
    cache_dir.mkdir()
    (cache_dir / "big_file").write_text("cached_content")

    dest = pm.copy_profile(source, "my-profile")

    assert dest.exists()
    assert (dest / "Preferences").exists()
    assert (dest / "Cookies").exists()
    # Cache should be skipped
    assert not (dest / "Cache").exists()


def test_copy_profile_overwrites_existing(pm: ProfileManager, tmp_path: Path):
    """Overwriting an existing profile replaces files."""
    source = tmp_path / "source_profile"
    source.mkdir()
    (source / "Preferences").write_text('{"version": 1}')

    # First copy
    dest = pm.copy_profile(source, "overwrite-test")
    assert (dest / "Preferences").read_text() == '{"version": 1}'

    # Update source and re-copy
    (source / "Preferences").write_text('{"version": 2}')
    dest2 = pm.copy_profile(source, "overwrite-test")
    assert dest == dest2
    assert (dest2 / "Preferences").read_text() == '{"version": 2}'


# ── list_profiles ───────────────────────────────────────────────────


def test_list_profiles_empty(pm: ProfileManager):
    """Returns empty list when no profiles have been imported."""
    assert pm.list_profiles() == []


def test_list_profiles_returns_imported(pm: ProfileManager, tmp_path: Path):
    """Returns names of imported profiles."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "Preferences").write_text("{}")

    pm.copy_profile(source, "alpha")
    pm.copy_profile(source, "beta")

    names = pm.list_profiles()
    assert "alpha" in names
    assert "beta" in names
    assert len(names) == 2


# ── get_profile_path ────────────────────────────────────────────────


def test_get_profile_path_existing(pm: ProfileManager, tmp_path: Path):
    """Returns the path for an existing imported profile."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "Preferences").write_text("{}")

    expected = pm.copy_profile(source, "my-profile")
    result = pm.get_profile_path("my-profile")
    assert result is not None
    assert result == expected


def test_get_profile_path_missing(pm: ProfileManager):
    """Returns None when the profile does not exist."""
    assert pm.get_profile_path("nonexistent") is None


# ── remove_profile ──────────────────────────────────────────────────


def test_remove_profile_existing(pm: ProfileManager, tmp_path: Path):
    """Removes an imported profile directory and returns True."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "Preferences").write_text("{}")

    pm.copy_profile(source, "to-delete")
    assert "to-delete" in pm.list_profiles()

    result = pm.remove_profile("to-delete")
    assert result is True
    assert "to-delete" not in pm.list_profiles()


def test_remove_profile_missing(pm: ProfileManager):
    """Returns False when trying to remove a profile that doesn't exist."""
    assert pm.remove_profile("ghost") is False
