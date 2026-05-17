"""HTML coverage report generator for discovered APIs.

Produces a self-contained HTML report visualising:
- Discovered endpoints (method, path, params, auth)
- Coverage stats (requests captured, unique endpoints, schemas inferred)
- Gaps: endpoints with no response schema or no observed examples
- Untemplated path candidates that would expand coverage if explored
"""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from site2cli.models import CapturedExchange, DiscoveredAPI


@dataclass(frozen=True)
class CoverageStats:
    total_requests: int
    api_requests: int
    unique_endpoints: int
    endpoints_with_response_schema: int
    endpoints_with_request_schema: int
    auth_protected: int
    methods: dict[str, int]
    status_codes: dict[str, int]
    gap_candidates: list[str]


def compute_coverage(
    api: DiscoveredAPI, exchanges: list[CapturedExchange] | None = None
) -> CoverageStats:
    exchanges = exchanges or []
    methods = Counter(ep.method for ep in api.endpoints)
    status_codes: Counter[str] = Counter()
    seen_paths: set[str] = set()
    for ex in exchanges:
        status_codes[str(ex.response.status)] += 1
        seen_paths.add(urlparse(ex.request.url).path)

    templated = {ep.path_pattern for ep in api.endpoints}
    gap_candidates = sorted(p for p in seen_paths if p not in templated)[:25]

    return CoverageStats(
        total_requests=len(exchanges),
        api_requests=sum(1 for _ in exchanges),
        unique_endpoints=len(api.endpoints),
        endpoints_with_response_schema=sum(
            1 for ep in api.endpoints if ep.response_schema
        ),
        endpoints_with_request_schema=sum(
            1 for ep in api.endpoints if ep.request_schema
        ),
        auth_protected=sum(1 for ep in api.endpoints if ep.auth_required),
        methods=dict(methods),
        status_codes=dict(status_codes),
        gap_candidates=gap_candidates,
    )


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #0b0d10; --panel: #14181d; --fg: #e6edf3; --muted: #8b949e;
    --accent: #58a6ff; --ok: #3fb950; --warn: #d29922; --bad: #f85149;
    --border: #30363d;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--fg); }}
  header {{ padding: 32px 40px; border-bottom: 1px solid var(--border); }}
  header h1 {{ margin: 0 0 4px; font-size: 22px; }}
  header .sub {{ color: var(--muted); }}
  main {{ padding: 24px 40px; max-width: 1200px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }}
  .card .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
  .card .value {{ font-size: 22px; font-weight: 600; margin-top: 4px; }}
  section {{ margin-top: 32px; }}
  section h2 {{ font-size: 16px; margin: 0 0 12px; color: var(--fg); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
  th, td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 13px; vertical-align: top; }}
  th {{ background: #1c2128; color: var(--muted); font-weight: 500; text-transform: uppercase; font-size: 11px; letter-spacing: 0.04em; }}
  tr:last-child td {{ border-bottom: none; }}
  .m {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; font-family: ui-monospace, SFMono-Regular, monospace; }}
  .m-GET {{ background: #1f6feb33; color: #58a6ff; }}
  .m-POST {{ background: #3fb95033; color: var(--ok); }}
  .m-PUT, .m-PATCH {{ background: #d2992233; color: var(--warn); }}
  .m-DELETE {{ background: #f8514933; color: var(--bad); }}
  code {{ font-family: ui-monospace, SFMono-Regular, monospace; font-size: 12.5px; }}
  .pill {{ display: inline-block; padding: 1px 8px; border: 1px solid var(--border); border-radius: 12px; font-size: 11px; color: var(--muted); margin-right: 4px; }}
  .gaps li {{ margin-bottom: 4px; color: var(--muted); }}
  .empty {{ color: var(--muted); font-style: italic; }}
  footer {{ padding: 24px 40px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--border); margin-top: 40px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="sub">{subtitle}</div>
</header>
<main>
  <div class="grid">
    <div class="card"><div class="label">Endpoints</div><div class="value">{unique_endpoints}</div></div>
    <div class="card"><div class="label">API Requests</div><div class="value">{api_requests}</div></div>
    <div class="card"><div class="label">With Response Schema</div><div class="value">{with_resp}</div></div>
    <div class="card"><div class="label">With Request Schema</div><div class="value">{with_req}</div></div>
    <div class="card"><div class="label">Auth Required</div><div class="value">{auth_protected}</div></div>
  </div>

  <section>
    <h2>Endpoints</h2>
    {endpoints_table}
  </section>

  <section>
    <h2>Methods</h2>
    <div>{methods_pills}</div>
  </section>

  <section>
    <h2>Status Codes Observed</h2>
    <div>{status_pills}</div>
  </section>

  <section>
    <h2>Coverage Gaps</h2>
    <p class="sub" style="color: var(--muted); margin-top: 0;">
      Observed paths that did not generalise into a templated endpoint.
      Exploring these flows would expand the spec.
    </p>
    {gaps_block}
  </section>
</main>
<footer>
  Generated by <strong>site2cli</strong> · {generated_at}
</footer>
</body>
</html>
"""


_EMPTY = '<span class="empty">&mdash;</span>'


def _endpoints_table(api: DiscoveredAPI) -> str:
    if not api.endpoints:
        return '<p class="empty">No endpoints discovered.</p>'
    rows = []
    for ep in api.endpoints:
        params = ", ".join(
            f"<code>{html.escape(p.name)}</code>" for p in ep.parameters[:6]
        ) or _EMPTY
        flags = []
        if ep.response_schema:
            flags.append('<span class="pill">response schema</span>')
        if ep.request_schema:
            flags.append('<span class="pill">request schema</span>')
        if ep.auth_required:
            flags.append('<span class="pill">auth</span>')
        rows.append(
            f"<tr>"
            f'<td><span class="m m-{html.escape(ep.method)}">{html.escape(ep.method)}</span></td>'
            f"<td><code>{html.escape(ep.path_pattern)}</code></td>"
            f"<td>{html.escape(ep.description) or _EMPTY}</td>"
            f"<td>{params}</td>"
            f"<td>{' '.join(flags)}</td>"
            f"</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Method</th><th>Path</th><th>Description</th><th>Parameters</th><th>Flags</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _pills(counter: dict[str, int]) -> str:
    if not counter:
        return '<span class="empty">None</span>'
    return "".join(
        f'<span class="pill">{html.escape(str(k))} · {v}</span>'
        for k, v in sorted(counter.items())
    )


def _gaps_block(gaps: list[str]) -> str:
    if not gaps:
        return '<p class="empty">No gaps — every observed path mapped to an endpoint.</p>'
    items = "".join(f"<li><code>{html.escape(p)}</code></li>" for p in gaps)
    return f'<ul class="gaps">{items}</ul>'


def render_report(
    api: DiscoveredAPI, exchanges: list[CapturedExchange] | None = None
) -> str:
    stats = compute_coverage(api, exchanges)
    return _TEMPLATE.format(
        title=f"{api.site_url} — API Coverage",
        subtitle=f"Base: {html.escape(api.base_url)} · Auth: {api.auth_type.value}",
        unique_endpoints=stats.unique_endpoints,
        api_requests=stats.api_requests,
        with_resp=stats.endpoints_with_response_schema,
        with_req=stats.endpoints_with_request_schema,
        auth_protected=stats.auth_protected,
        endpoints_table=_endpoints_table(api),
        methods_pills=_pills(stats.methods),
        status_pills=_pills(stats.status_codes),
        gaps_block=_gaps_block(stats.gap_candidates),
        generated_at=api.discovered_at.isoformat(timespec="seconds"),
    )


def save_report(
    api: DiscoveredAPI,
    output_path: Path,
    exchanges: list[CapturedExchange] | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_report(api, exchanges), encoding="utf-8")
    return output_path


def save_coverage_json(
    api: DiscoveredAPI,
    output_path: Path,
    exchanges: list[CapturedExchange] | None = None,
) -> Path:
    stats = compute_coverage(api, exchanges)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(stats.__dict__, indent=2, default=str), encoding="utf-8"
    )
    return output_path
