"""Offline trace I/O for browser network captures.

A "trace" is a portable JSON file containing a list of CapturedExchange
records. Traces can be saved during live capture and replayed later by
the discover pipeline without re-running the browser, which mirrors the
browser-to-api skill's offline workflow.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from site2cli.models import CapturedExchange


class Trace(BaseModel):
    """A saved trace of captured network exchanges."""

    version: int = 1
    site_url: str = ""
    target_domain: str | None = None
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    exchanges: list[CapturedExchange] = Field(default_factory=list)


def save_trace(
    exchanges: list[CapturedExchange],
    output_path: Path,
    *,
    site_url: str = "",
    target_domain: str | None = None,
) -> Path:
    trace = Trace(
        site_url=site_url,
        target_domain=target_domain,
        exchanges=exchanges,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def load_trace(input_path: Path) -> Trace:
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        # Bare list of exchanges
        return Trace(exchanges=[CapturedExchange.model_validate(e) for e in data])
    return Trace.model_validate(data)
