"""Configuration management for site2cli."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


def _default_data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "site2cli"
    new_dir = Path.home() / ".site2cli"
    # Fallback: migrate from old ~/.webcli if it exists
    old_dir = Path.home() / ".webcli"
    if not new_dir.exists() and old_dir.exists():
        old_dir.rename(new_dir)
    return new_dir


class LLMConfig(BaseModel):
    """LLM configuration for API discovery and analysis."""

    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: str | None = None
    max_tokens: int = 4096

    def get_api_key(self) -> str:
        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError(
                "No API key configured. Set ANTHROPIC_API_KEY"
                " or use `site2cli config set llm.api_key`"
            )
        return key


class BrowserConfig(BaseModel):
    """Browser automation configuration."""

    headless: bool = True
    timeout_ms: int = 30_000
    stealth: bool = True
    user_data_dir: str | None = None


class Config(BaseModel):
    """Top-level site2cli configuration."""

    data_dir: Path = Field(default_factory=_default_data_dir)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "registry.db"

    @property
    def specs_dir(self) -> Path:
        return self.data_dir / "specs"

    @property
    def clients_dir(self) -> Path:
        return self.data_dir / "clients"

    @property
    def workflows_dir(self) -> Path:
        return self.data_dir / "workflows"

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.yaml"

    def ensure_dirs(self) -> None:
        for d in [self.data_dir, self.specs_dir, self.clients_dir, self.workflows_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        import yaml

        self.ensure_dirs()
        with open(self.config_path, "w") as f:
            yaml.dump(self.model_dump(mode="json"), f, default_flow_style=False)

    @classmethod
    def load(cls) -> Config:
        import yaml

        default = cls()
        if default.config_path.exists():
            with open(default.config_path) as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        return default


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.load()
        _config.ensure_dirs()
    return _config


def reset_config() -> None:
    global _config
    _config = None
