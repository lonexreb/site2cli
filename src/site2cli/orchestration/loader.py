"""Load and save orchestration pipeline definitions from YAML/JSON files."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from site2cli.models import OrchestrationPipeline


def load_pipeline(path: Path) -> OrchestrationPipeline:
    """Load a pipeline from a YAML or JSON file."""
    text = path.read_text()

    if path.suffix in (".yaml", ".yml"):
        import yaml

        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    # Auto-generate ID if not present
    if "id" not in data:
        data["id"] = str(uuid.uuid4())

    return OrchestrationPipeline.model_validate(data)


def save_pipeline(pipeline: OrchestrationPipeline, path: Path) -> None:
    """Save a pipeline to YAML or JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = pipeline.model_dump(mode="json")

    if path.suffix in (".yaml", ".yml"):
        import yaml

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    else:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
