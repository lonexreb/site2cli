"""Tests for the community registry — import/export of site specs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from site2cli.community.registry import CommunityRegistry
from site2cli.config import get_config, reset_config
from site2cli.models import SiteAction, SiteEntry, Tier
from site2cli.registry import SiteRegistry


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    config = get_config()
    registry = SiteRegistry(config.db_path)
    site = SiteEntry(
        domain="example.com",
        base_url="https://api.example.com",
        description="Test site",
        actions=[SiteAction(name="search", tier=Tier.API)],
    )
    registry.add_site(site)
    return registry, config


def test_export_site_creates_valid_json_bundle(setup, tmp_path):
    """export_site writes a valid JSON bundle with the expected structure."""
    registry, config = setup
    community = CommunityRegistry(registry)

    output_path = tmp_path / "example.com.site2cli.json"
    result_path = community.export_site("example.com", output_path=output_path)

    assert result_path == output_path
    assert output_path.exists()

    with open(output_path) as f:
        bundle = json.load(f)

    assert bundle["version"] == "1.0"
    assert "exported_at" in bundle
    assert "site" in bundle
    assert bundle["site"]["domain"] == "example.com"
    assert bundle["site"]["base_url"] == "https://api.example.com"
    assert bundle["site"]["description"] == "Test site"
    assert len(bundle["site"]["actions"]) == 1
    assert bundle["site"]["actions"][0]["name"] == "search"


def test_import_site_loads_bundle_and_registers_site(setup, tmp_path):
    """import_site reads a bundle file and adds the site to the registry."""
    registry, config = setup
    community = CommunityRegistry(registry)

    # Export first, then import into a fresh registry
    bundle_path = tmp_path / "example.com.site2cli.json"
    community.export_site("example.com", output_path=bundle_path)

    fresh_registry = SiteRegistry(tmp_path / "fresh.db")
    fresh_community = CommunityRegistry(fresh_registry)

    imported = fresh_community.import_site(bundle_path)

    assert imported.domain == "example.com"
    assert imported.base_url == "https://api.example.com"
    assert imported.description == "Test site"

    retrieved = fresh_registry.get_site("example.com")
    assert retrieved is not None
    assert retrieved.domain == "example.com"


def test_export_import_roundtrip_preserves_data(setup, tmp_path):
    """A full export → import cycle preserves all site metadata and actions."""
    registry, config = setup
    community = CommunityRegistry(registry)

    bundle_path = tmp_path / "roundtrip.site2cli.json"
    community.export_site("example.com", output_path=bundle_path)

    fresh_registry = SiteRegistry(tmp_path / "roundtrip.db")
    fresh_community = CommunityRegistry(fresh_registry)
    imported = fresh_community.import_site(bundle_path)

    original = registry.get_site("example.com")
    assert imported.domain == original.domain
    assert imported.base_url == original.base_url
    assert imported.description == original.description
    assert len(imported.actions) == len(original.actions)
    assert imported.actions[0].name == original.actions[0].name
    assert imported.actions[0].tier == original.actions[0].tier


def test_list_available_returns_empty_when_no_specs(setup):
    """list_available returns an empty list when no bundles have been exported."""
    registry, config = setup
    community = CommunityRegistry(registry)

    result = community.list_available()

    assert result == []


def test_list_available_returns_spec_info(setup, tmp_path):
    """list_available returns metadata for each exported bundle in the community dir."""
    registry, config = setup
    community = CommunityRegistry(registry)

    # Export into the community dir (default output_path)
    community.export_site("example.com")

    result = community.list_available()

    assert len(result) == 1
    entry = result[0]
    assert entry["domain"] == "example.com"
    assert entry["description"] == "Test site"
    assert entry["actions"] == 1
    assert "path" in entry
    assert entry["path"].endswith(".site2cli.json")
    assert "exported_at" in entry


def test_import_site_with_openapi_spec_included(setup, tmp_path):
    """import_site saves the embedded OpenAPI spec to the specs dir and links it."""
    registry, config = setup

    # Create a bundle manually that includes an OpenAPI spec
    openapi_spec = {
        "openapi": "3.1.0",
        "info": {"title": "Example API", "version": "1.0.0"},
        "paths": {
            "/search": {
                "get": {
                    "operationId": "search",
                    "summary": "Search endpoint",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    site_data = SiteEntry(
        domain="spec-site.com",
        base_url="https://api.spec-site.com",
        description="Site with OpenAPI spec",
        actions=[SiteAction(name="search", tier=Tier.API)],
    ).model_dump(mode="json")

    bundle = {
        "version": "1.0",
        "exported_at": "2026-01-01T00:00:00",
        "site": site_data,
        "openapi_spec": openapi_spec,
    }

    bundle_path = tmp_path / "spec-site.com.site2cli.json"
    with open(bundle_path, "w") as f:
        json.dump(bundle, f)

    community = CommunityRegistry(registry)
    imported = community.import_site(bundle_path)

    assert imported.domain == "spec-site.com"
    assert imported.openapi_spec_path is not None

    spec_path = Path(imported.openapi_spec_path)
    assert spec_path.exists()

    with open(spec_path) as f:
        saved_spec = json.load(f)
    assert saved_spec["openapi"] == "3.1.0"
    assert "/search" in saved_spec["paths"]
