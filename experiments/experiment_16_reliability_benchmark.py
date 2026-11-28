"""Experiment #16: Execution reliability benchmark (issue #31)

Measures whether site2cli completes the intended task, classifies rejections
correctly, preserves sessions and avoids duplicate side effects, against one
deterministic local fixture site. No external sites, LLM key, proxy or CAPTCHA
vendor is used.

The "challenge" scenario is a SYNTHETIC page containing a challenge-script
marker. It tests handling only. Nothing here measures, or claims, getting past
Cloudflare, DataDome, Akamai or any other protection provider.

Run: python experiments/experiment_16_reliability_benchmark.py [--repeats N] [--out DIR]
Writes reliability_results.json and reliability_report.md to DIR
(default: experiments/results/).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

CHALLENGE = (
    '<html><body><script src="/cdn-cgi/challenge-platform/h/b/orchestrate.js">'
    "</script></body></html>"
)
ARTICLE = "<html><body><h1>How CAPTCHA works</h1><p>A captcha is a test.</p></body></html>"
ME_PAGE = (
    "<html><body><p>cookie:%s</p><p id='ls'></p><script>"
    "document.getElementById('ls').textContent='storage:'+localStorage.getItem('token')"
    "</script></body></html>"
)
LOGIN_PAGE = "<html><body>ok<script>localStorage.setItem('token','t1')</script></body></html>"


class Fixture(BaseHTTPRequestHandler):
    """The fixture site. Counts every request per path on the server object."""

    def _send(self, status: int, ctype: str, body: str, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body.encode())))
        for k, v in headers.items():
            self.send_header(k.replace("_", "-"), v)
        self.end_headers()
        self.wfile.write(body.encode())

    def _serve(self) -> None:
        path, _, query = self.path.partition("?")
        self.server.hits[path] += 1  # type: ignore[attr-defined]
        cookie = self.headers.get("Cookie", "")
        if path == "/items":
            self._send(200, "application/json", json.dumps({"query": query, "items": [1, 2]}))
        elif path == "/account":
            if "session=valid" in cookie:
                self._send(200, "application/json", '{"user": "alice"}')
            else:
                self._send(401, "application/json", '{"detail": "login required"}')
        elif path == "/forbidden":
            self._send(403, "application/json", '{"detail": "no"}')
        elif path == "/limited":
            self._send(429, "application/json", "{}", Retry_After="7")
        elif path == "/challenge":
            self._send(200, "text/html", CHALLENGE)
        elif path == "/article":
            self._send(200, "text/html", ARTICLE)
        elif path == "/order":
            # The mutation is applied (counted above), then the reply is cut off.
            self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{")
            self.wfile.flush()
            self.connection.close()
        elif path == "/login":
            self._send(200, "text/html", LOGIN_PAGE, Set_Cookie="user=alice; Path=/")
        elif path == "/me":
            user = "alice" if "user=alice" in cookie else "anon"
            self._send(200, "text/html", ME_PAGE % user)
        else:
            self._send(200, "text/html", "<html><body></body></html>")

    do_GET = do_POST = _serve  # noqa: N815

    def log_message(self, *args: object) -> None:
        pass


@dataclass
class Case:
    """One scenario. `expect` is fixed here, before anything is executed."""

    id: str
    scenario: str
    transport: str  # "http" or "browser"
    expect_outcome: str
    expect_requests: dict[str, int]  # server hits per path for ONE attempt
    expect_text: str = ""  # must appear in the JSON-serialised result
    note: str = ""


@dataclass
class Attempt:
    outcome: str
    correct: bool
    requests: dict[str, int]
    duplicate_side_effects: int
    fallbacks: int
    human_interventions: int
    latency_ms: float
    transport: str
    detail: str = ""


@dataclass
class CaseResult:
    case: Case
    attempts: list[Attempt] = field(default_factory=list)
    status: str = "verified"  # verified | failed | untested


CASES = [
    Case("json_read", "Public JSON read with parameters", "http",
         "success", {"/items": 1}, '"query": "q=shoes"'),
    Case("cookie_valid", "Cookie-authenticated read", "http",
         "success", {"/account": 1}, "alice"),
    Case("cookie_expired", "Same read after the cookie expired", "http",
         "auth_required", {"/account": 1},
         note="Browser fallback is attempted (the request was refused) and fails here."),
    Case("forbidden", "Forbidden endpoint", "http", "forbidden", {"/forbidden": 1},
         note="Browser fallback is attempted and fails here."),
    Case("rate_limited", "Rate-limited endpoint", "http", "rate_limited", {"/limited": 1}, '"7"'),
    Case("synthetic_challenge", "HTTP 200 synthetic challenge page (handling test only)", "http",
         "challenge", {"/challenge": 1},
         note="Synthetic marker page; not a protection-provider evaluation."),
    Case("html_mentions_captcha", "Expected HTML that mentions CAPTCHA", "http",
         "success", {"/article": 1}, "How CAPTCHA works"),
    Case("dropped_mutation", "POST applied, response dropped", "http",
         "unknown", {"/order": 1}, "requires_review"),
    Case("session_reused", "Browser workflow, storage reused in a named session", "browser",
         "success", {"/login": 1, "/me": 1}, "cookie:alice"),
    Case("session_fresh", "Same workflow in fresh browsers (no session)", "browser",
         "success", {"/login": 1, "/me": 1}, "cookie:anon",
         note="Control: without a session, login state must not carry over."),
    Case("workflow_failed_step", "Workflow whose final step cannot complete", "browser",
         "failed", {}, "error"),
]


class _FailingBrowser:
    """Stands in for the LLM browser tier (no API key here) and counts fallbacks."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute_action(self, *args: object, **kwargs: object) -> dict:
        self.calls += 1
        return {"error": "browser tier disabled in benchmark", "outcome": "failed"}


def _setup_registry(base: str) -> None:
    from site2cli.config import get_config
    from site2cli.models import (
        EndpointInfo,
        ParameterInfo,
        RecordedWorkflow,
        SiteAction,
        SiteEntry,
        Tier,
        WorkflowStep,
    )
    from site2cli.registry import SiteRegistry
    from site2cli.tiers.cached_workflow import save_workflow

    config = get_config()

    def api(name: str, path: str, method: str = "GET", ctype: str = "application/json",
            params: list[ParameterInfo] | None = None) -> SiteAction:
        return SiteAction(name=name, tier=Tier.API, endpoint=EndpointInfo(
            method=method, path_pattern=path, response_content_type=ctype,
            parameters=params or []))

    def workflow(name: str, steps: list[WorkflowStep]) -> SiteAction:
        wf = RecordedWorkflow(id=f"bench-{name}", site_domain="local.test",
                              action_name=name, steps=steps)
        save_workflow(wf, config.workflows_dir)
        return SiteAction(name=name, tier=Tier.WORKFLOW, workflow_id=wf.id)

    nav = lambda p: WorkflowStep(action="navigate", url=base + p)  # noqa: E731
    body = WorkflowStep(action="extract", selector="body")
    actions = [
        api("json_read", "/items", params=[ParameterInfo(name="q", location="query")]),
        api("account", "/account"),
        api("forbidden", "/forbidden", "POST"),
        api("rate_limited", "/limited"),
        api("synthetic_challenge", "/challenge", "POST"),
        api("html_mentions_captcha", "/article", ctype="text/html"),
        api("dropped_mutation", "/order", "POST"),
        workflow("login", [nav("/login"), body]),
        workflow("whoami", [nav("/me"), body]),
        workflow("workflow_failed_step", [
            nav("/me"), WorkflowStep(action="click", selector="#does-not-exist")]),
    ]
    registry = SiteRegistry(config.db_path)
    registry.add_site(SiteEntry(domain="local.test", base_url=base, actions=actions))
    registry.close()


async def _chromium_available() -> bool:
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            await (await pw.chromium.launch()).close()
        return True
    except Exception:
        return False


async def _run_case(case: Case, server: ThreadingHTTPServer, host: str, n: int) -> Attempt:
    from site2cli.auth.cookies import CookieManager
    from site2cli.browser.session import current_session, get_session_manager
    from site2cli.config import get_config
    from site2cli.outcome import outcome_of
    from site2cli.registry import SiteRegistry
    from site2cli.router import Router

    registry = SiteRegistry(get_config().db_path)
    router = Router(registry)
    stub = _FailingBrowser()
    if case.transport == "http":
        router._browser = stub  # type: ignore[assignment]

    def cookie(expires: float) -> dict:
        return {"name": "session", "value": "valid", "domain": host, "path": "/",
                "expires": expires}

    server.hits.clear()  # type: ignore[attr-defined]
    started = time.perf_counter()
    try:
        if case.id == "cookie_valid":
            CookieManager().set_all("local.test", [cookie(time.time() + 3600)])
            result = await router.execute("local.test", "account", {})
        elif case.id == "cookie_expired":
            CookieManager().set_all("local.test", [cookie(time.time() - 60)])
            result = await router.execute("local.test", "account", {})
        elif case.id == "json_read":
            result = await router.execute("local.test", "json_read", {"q": "shoes"})
        elif case.id in ("session_reused", "session_fresh"):
            name = f"bench-{n}" if case.id == "session_reused" else None
            token = current_session.set(name)
            try:
                await router.execute("local.test", "login", {})
                result = await router.execute("local.test", "whoami", {})
            finally:
                current_session.reset(token)
                if name:
                    await get_session_manager().close(name)
        else:
            result = await router.execute("local.test", case.id, {})
    finally:
        CookieManager().clear("local.test")
        registry.close()
    latency = (time.perf_counter() - started) * 1000

    outcome = outcome_of(result).value
    hits = {k: v for k, v in server.hits.items() if k != "/"}  # type: ignore[attr-defined]
    text = json.dumps(result, default=str)
    duplicates = sum(max(0, hits.get(p, 0) - want) for p, want in case.expect_requests.items())
    correct = (
        outcome == case.expect_outcome
        and all(hits.get(p, 0) == want for p, want in case.expect_requests.items())
        and case.expect_text in text
    )
    return Attempt(
        outcome=outcome,
        correct=correct,
        requests=hits,
        duplicate_side_effects=duplicates,
        fallbacks=stub.calls,
        human_interventions=0,
        latency_ms=round(latency, 1),
        transport=str(result.get("transport", "")) if isinstance(result, dict) else "",
        detail="" if correct else str(result.get("error", ""))[:200],
    )


def _versions() -> dict[str, str]:
    out = {"python": platform.python_version(), "platform": platform.platform()}
    for pkg in ("site2cli", "httpx", "playwright"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "not installed"
    try:
        out["commit"] = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
            cwd=Path(__file__).parent, check=False,
        ).stdout.strip() or "unknown"
    except OSError:
        out["commit"] = "unknown"
    return out


async def run_benchmark(repeats: int = 3) -> dict:
    """Run every case `repeats` times in an isolated data dir. Returns the report dict."""
    data_dir = Path(tempfile.mkdtemp(prefix="s2c-bench"))
    previous = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(data_dir)
    from site2cli.config import reset_config

    reset_config()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    server.hits = Counter()  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = "127.0.0.1"
    try:
        _setup_registry(f"http://{host}:{server.server_address[1]}")
        has_browser = await _chromium_available()
        results = []
        for case in CASES:
            res = CaseResult(case)
            if case.transport == "browser" and not has_browser:
                res.status = "untested"
            else:
                for n in range(repeats):
                    res.attempts.append(await _run_case(case, server, host, n))
                res.status = "verified" if all(a.correct for a in res.attempts) else "failed"
            results.append(res)
    finally:
        server.shutdown()
        server.server_close()
        if previous is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = previous
        reset_config()
        shutil.rmtree(data_dir, ignore_errors=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": _versions(),
        "conditions": {
            "mode": "headless Chromium; direct HTTP via httpx; no proxy; LLM browser tier stubbed",
            "repeats": repeats,
            "chromium_available": has_browser,
            "targets": "local fixture only (127.0.0.1)",
        },
        "cases": [
            {**asdict(r.case), "status": r.status, "attempts": [asdict(a) for a in r.attempts]}
            for r in results
        ],
    }


def render_markdown(report: dict) -> str:
    env, cond = report["environment"], report["conditions"]
    lines = [
        "# Reliability benchmark",
        "",
        f"Generated {report['generated_at']} at commit `{env['commit']}`. "
        f"Python {env['python']}, httpx {env['httpx']}, playwright {env['playwright']}.",
        f"Mode: {cond['mode']}. Targets: {cond['targets']}. "
        f"Each case ran {cond['repeats']} times.",
        "",
        "The challenge case is a synthetic page. It tests handling only and is not a "
        "Cloudflare, DataDome or Akamai result. No protected third-party site was tested.",
        "",
        "| Scenario | Expected | Correct | Requests per attempt | Duplicate side effects "
        "| Fallbacks | Human steps | Median latency | Status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in report["cases"]:
        a = c["attempts"]
        if not a:
            lines.append(f"| {c['scenario']} | {c['expect_outcome']} | 0/0 | n/a | n/a | n/a "
                         "| n/a | n/a | untested (Chromium not available) |")
            continue
        latencies = sorted(x["latency_ms"] for x in a)
        requests = ", ".join(f"{p}: {n}" for p, n in sorted(a[0]["requests"].items())) or "none"
        lines.append(
            f"| {c['scenario']} | {c['expect_outcome']} "
            f"| {sum(x['correct'] for x in a)}/{len(a)} | {requests} "
            f"| {sum(x['duplicate_side_effects'] for x in a)} "
            f"| {sum(x['fallbacks'] for x in a)} | {sum(x['human_interventions'] for x in a)} "
            f"| {latencies[len(latencies) // 2]:.0f} ms | {c['status']} |"
        )
    notes = [f"- {c['scenario']}: {c['note']}" for c in report["cases"] if c["note"]]
    lines += ["", "Notes:", *notes, "",
              "Not covered: real bot-protection providers, CAPTCHA solving, human challenge "
              "handoff, proxies, the LLM-driven browser tier, and cross-process daemon use."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args()

    report = asyncio.run(run_benchmark(args.repeats))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "reliability_results.json").write_text(json.dumps(report, indent=2))
    markdown = render_markdown(report)
    (args.out / "reliability_report.md").write_text(markdown)
    print(markdown)  # noqa: T201 - CLI output of a standalone script
    return 1 if any(c["status"] == "failed" for c in report["cases"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
