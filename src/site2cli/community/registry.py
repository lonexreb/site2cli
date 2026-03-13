"""Community spec sharing — import/export site specs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from site2cli.config import get_config
from site2cli.discovery.spec_generator import load_spec, save_spec
from site2cli.models import SiteEntry
from site2cli.registry import SiteRegistry


class CommunityRegistry:
    """Manages import/export of community-contributed site specs."""

    def __init__(self, registry: SiteRegistry) -> None:
        self._registry = registry
        self._config = get_config()
        self._community_dir = self._config.data_dir / "community"
        self._community_dir.mkdir(parents=True, exist_ok=True)

    def export_site(self, domain: str, output_path: Path | None = None) -> Path:
        """Export a site's spec and metadata for sharing.

        Creates a JSON bundle containing:
        - Site metadata
        - OpenAPI spec
        - Action definitions
        """
        site = self._registry.get_site(domain)
        if not site:
            raise ValueError(f"Site {domain} not found in registry")

        bundle = {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "site": site.model_dump(mode="json"),
        }

        # Include OpenAPI spec if available
        if site.openapi_spec_path:
            spec_path = Path(site.openapi_spec_path)
            if spec_path.exists():
                bundle["openapi_spec"] = load_spec(spec_path)

        if output_path is None:
            output_path = self._community_dir / f"{domain}.site2cli.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(bundle, f, indent=2, default=str)

        return output_path

    def import_site(self, bundle_path: Path) -> SiteEntry:
        """Import a community-shared site spec.

        Args:
            bundle_path: Path to the .site2cli.json bundle.

        Returns:
            The imported SiteEntry.
        """
        with open(bundle_path) as f:
            bundle = json.load(f)

        site_data = bundle.get("site", {})
        site = SiteEntry.model_validate(site_data)

        # Save OpenAPI spec if included
        if "openapi_spec" in bundle:
            spec_path = self._config.specs_dir / f"{site.domain}.json"
            save_spec(bundle["openapi_spec"], spec_path)
            site.openapi_spec_path = str(spec_path)

        self._registry.add_site(site)
        return site

    def list_available(self) -> list[dict]:
        """List available community specs in the local community directory."""
        specs = []
        for path in self._community_dir.glob("*.site2cli.json"):
            try:
                with open(path) as f:
                    bundle = json.load(f)
                site_data = bundle.get("site", {})
                specs.append({
                    "domain": site_data.get("domain", "unknown"),
                    "description": site_data.get("description", ""),
                    "actions": len(site_data.get("actions", [])),
                    "path": str(path),
                    "exported_at": bundle.get("exported_at", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return specs
