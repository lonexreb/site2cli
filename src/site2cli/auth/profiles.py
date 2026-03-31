"""Chrome/Firefox profile import for authenticated browser sessions."""

from __future__ import annotations

import platform
import shutil
from pathlib import Path

from site2cli.config import get_config


class ProfileManager:
    """Manages browser profile imports for authenticated discovery."""

    def __init__(self) -> None:
        self._config = get_config()
        self._profiles_dir = self._config.profiles_dir
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

    def _chrome_data_dir(self) -> Path | None:
        """Return the Chrome user-data directory for the current platform."""
        system = platform.system()
        if system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
        elif system == "Linux":
            return Path.home() / ".config" / "google-chrome"
        elif system == "Windows":
            return Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
        return None

    def detect_chrome_profiles(self) -> list[Path]:
        """Detect available Chrome profile directories for the current platform."""
        base = self._chrome_data_dir()
        if base is None or not base.exists():
            return []
        profiles = []
        # Default profile
        default = base / "Default"
        if default.exists():
            profiles.append(default)
        # Numbered profiles
        for p in sorted(base.iterdir()):
            if p.name.startswith("Profile ") and p.is_dir():
                profiles.append(p)
        return profiles

    def detect_firefox_profiles(self) -> list[Path]:
        """Detect available Firefox profile directories."""
        system = platform.system()
        base: Path | None = None
        if system == "Darwin":
            base = Path.home() / "Library" / "Application Support" / "Firefox" / "Profiles"
        elif system == "Linux":
            base = Path.home() / ".mozilla" / "firefox"
        elif system == "Windows":
            base = Path.home() / "AppData" / "Roaming" / "Mozilla" / "Firefox" / "Profiles"
        if base is None or not base.exists():
            return []
        return [p for p in sorted(base.iterdir()) if p.is_dir()]

    def copy_profile(self, source: Path, name: str) -> Path:
        """Copy a browser profile to the site2cli profiles directory.

        Args:
            source: Path to the source profile directory.
            name: Name for the imported profile.

        Returns:
            Path to the copied profile.
        """
        dest = self._profiles_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        # Copy selectively — skip large caches
        skip_dirs = {"Cache", "Code Cache", "GPUCache", "Service Worker", "ShaderCache"}
        dest.mkdir(parents=True)
        for item in source.iterdir():
            if item.name in skip_dirs:
                continue
            if item.is_dir():
                shutil.copytree(item, dest / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest / item.name)
        return dest

    def list_profiles(self) -> list[str]:
        """List imported profile names."""
        if not self._profiles_dir.exists():
            return []
        return sorted(
            p.name for p in self._profiles_dir.iterdir() if p.is_dir()
        )

    def get_profile_path(self, name: str) -> Path | None:
        """Get the path to an imported profile."""
        path = self._profiles_dir / name
        return path if path.exists() else None

    def remove_profile(self, name: str) -> bool:
        """Remove an imported profile."""
        path = self._profiles_dir / name
        if path.exists():
            shutil.rmtree(path)
            return True
        return False
