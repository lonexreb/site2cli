"""The reliability benchmark (issue #31) must stay green on its local fixture."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).parent.parent / "experiments" / "experiment_16_reliability_benchmark.py"


@pytest.mark.asyncio
async def test_benchmark_cases_all_verified_or_untested():
    spec = importlib.util.spec_from_file_location("reliability_benchmark", _PATH)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module  # dataclasses needs the module registered
    spec.loader.exec_module(module)

    report = await module.run_benchmark(repeats=1)

    statuses = {c["id"]: c["status"] for c in report["cases"]}
    assert "failed" not in statuses.values(), statuses
    http = [c for c in report["cases"] if c["transport"] == "http"]
    assert all(c["status"] == "verified" for c in http)
    assert sum(a["duplicate_side_effects"] for c in report["cases"] for a in c["attempts"]) == 0
    markdown = module.render_markdown(report)
    assert "synthetic" in markdown and "| Scenario |" in markdown
