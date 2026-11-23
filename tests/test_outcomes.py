"""Execution outcomes (issue #27): truthful success counts, no duplicate sends.

Runs against a real local HTTP server so request counts are observed, not mocked.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from site2cli.discovery.client_generator import generate_client_code
from site2cli.models import EndpointInfo, SiteAction, SiteEntry, Tier
from site2cli.outcome import Outcome, outcome_of
from site2cli.registry import SiteRegistry
from site2cli.router import Router

CHALLENGE = (
    '<html><body><script src="/cdn-cgi/challenge-platform/h/b/orchestrate.js">'
    "</script></body></html>"
)
ARTICLE = "<html><body><h1>How CAPTCHA works</h1><p>A captcha is a test.</p></body></html>"

# path -> (status, content-type, body, extra headers)
ROUTES: dict[str, tuple[int, str, str, dict[str, str]]] = {
    "/ok": (200, "application/json", '{"items": [1, 2]}', {}),
    "/empty": (204, "application/json", "", {}),
    "/401": (401, "application/json", '{"detail": "login"}', {}),
    "/403": (403, "application/json", '{"detail": "no"}', {}),
    "/429": (429, "application/json", "{}", {"Retry-After": "7"}),
    "/303": (303, "text/html", "", {"Location": "/done"}),
    "/429c": (429, "text/html", CHALLENGE, {"cf-mitigated": "challenge"}),
    "/challenge": (200, "text/html", CHALLENGE, {}),
    "/html": (200, "text/html", ARTICLE, {}),
    "/garbage": (200, "application/json", "not json", {}),
}


class _Handler(BaseHTTPRequestHandler):
    def _serve(self) -> None:
        path = self.path.split("?")[0]
        self.server.hits[path] = self.server.hits.get(path, 0) + 1  # type: ignore[attr-defined]
        if path == "/drop":
            # Accept the mutation, then die before a complete response.
            self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{")
            self.wfile.flush()
            self.connection.close()
            return
        status, ctype, body, extra = ROUTES[path]
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "sid=secret-session-value")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    do_GET = do_POST = _serve  # noqa: N815

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.hits = {}  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


class _NoAuth:
    def get_auth_headers(self, *a: object) -> dict:
        return {}

    def get_auth_cookies(self, *a: object) -> list:
        return []


class _Browser:
    """Stands in for the browser tier and counts how often it is used."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute_action(self, *a: object) -> dict:
        self.calls += 1
        return {"error": "browser unavailable in tests"}


@pytest.fixture
def env(tmp_path, server):
    registry = SiteRegistry(tmp_path / "t.db")
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def make(path: str, method: str = "GET", *, json_op: bool = True, client: bool = False):
        ep = EndpointInfo(
            method=method,
            path_pattern=path,
            description="do it",
            response_content_type="application/json" if json_op else "text/html",
        )
        site = SiteEntry(
            domain="local.test",
            base_url=base,
            actions=[SiteAction(name="act", tier=Tier.API, endpoint=ep)],
        )
        if client:
            spec = {
                "info": {"title": "Local API"},
                "servers": [{"url": base}],
                "paths": {path: {method.lower(): {"operationId": "do_it"}}},
            }
            client_path = tmp_path / "client.py"
            client_path.write_text(generate_client_code(spec))
            site.client_module_path = str(client_path)
        registry.add_site(site)
        router = Router(registry)
        router._direct_api._auth = _NoAuth()
        router._browser = _Browser()
        return router

    def counts() -> tuple[int, int, Tier]:
        action = registry.get_site("local.test").actions[0]
        return action.success_count, action.failure_count, action.tier

    yield make, counts, server
    registry.close()


async def _run(router: Router) -> dict:
    return await router.execute("local.test", "act", {})


@pytest.mark.asyncio
async def test_json_success_counted_once_with_payload(env):
    make, counts, server = env
    result = await _run(make("/ok"))
    assert result["data"] == {"items": [1, 2]}
    assert outcome_of(result) is Outcome.SUCCESS
    assert server.hits == {"/ok": 1}
    assert counts()[:2] == (1, 0)
    assert "set-cookie" not in {k.lower() for k in result["headers"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("client", [False, True])
async def test_204_is_success_without_second_request(env, client):
    make, counts, server = env
    result = await _run(make("/empty", "POST", client=client))
    assert outcome_of(result) is Outcome.SUCCESS
    assert server.hits == {"/empty": 1}
    assert counts()[:2] == (1, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/401", Outcome.AUTH_REQUIRED),
        ("/403", Outcome.FORBIDDEN),
        ("/429", Outcome.RATE_LIMITED),
        ("/challenge", Outcome.CHALLENGE),
        ("/html", Outcome.UNEXPECTED_RESPONSE),
    ],
)
@pytest.mark.parametrize("client", [False, True])
async def test_rejections_are_distinct_and_never_promote(env, path, expected, client):
    make, counts, server = env
    router = make(path, "POST", client=client)
    result = await _run(router)
    if client and expected in (Outcome.CHALLENGE, Outcome.UNEXPECTED_RESPONSE):
        # A generated client only sees undecodable content.
        expected = Outcome.UNEXPECTED_RESPONSE
    if path in ("/401", "/403") or (path == "/challenge" and not client):
        # Refused requests may fall back to the browser, which fails here.
        assert router._browser.calls == 1
        assert outcome_of(result) is not Outcome.SUCCESS
    else:
        assert outcome_of(result) is expected
        assert router._browser.calls == 0
    assert server.hits == {path: 1}
    success, failures, tier = counts()
    assert success == 0 and failures >= 1 and tier is Tier.API


@pytest.mark.asyncio
async def test_rate_limit_keeps_retry_metadata_and_blocks_fallback(env):
    make, _, server = env
    router = make("/429")  # even a safe GET must not hop tiers past a limit
    result = await _run(router)
    assert result["outcome"] == "rate_limited"
    assert result["retry_after"] == "7"
    assert router._browser.calls == 0 and server.hits == {"/429": 1}


@pytest.mark.asyncio
async def test_expected_html_mentioning_captcha_is_success(env):
    make, counts, _ = env
    result = await _run(make("/html", json_op=False))
    assert outcome_of(result) is Outcome.SUCCESS
    assert counts()[:2] == (1, 0)


@pytest.mark.asyncio
async def test_unusable_client_falls_back_to_raw_http_once(env):
    make, _, server = env
    router = make("/ok", client=True)
    site = router._registry.get_site("local.test")
    # Break the client before dispatch: no method matches the endpoint.
    site.actions[0].endpoint.description = "missing method"
    router._registry.add_site(site)
    result = await _run(router)
    assert result["transport"] == "http"
    assert server.hits == {"/ok": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "client"), [("/drop", False), ("/drop", True), ("/garbage", True)]
)
async def test_ambiguous_post_is_never_reissued(env, path, client):
    make, counts, server = env
    router = make(path, "POST", client=client)
    result = await _run(router)
    assert server.hits == {path: 1}  # the mutation counter
    assert router._browser.calls == 0
    assert outcome_of(result) in (Outcome.UNKNOWN, Outcome.UNEXPECTED_RESPONSE)
    assert result["requires_review"] is True
    assert counts()[:2] == (0, 1)


def test_failed_workflow_and_browser_results_are_not_success():
    failed_step = {
        "steps_executed": 1,
        "steps_total": 3,
        "results": [{"step": 0, "success": False, "error": "no selector"}],
    }
    assert outcome_of(failed_step) is Outcome.FAILED
    assert outcome_of({"error": "browser crashed"}) is Outcome.FAILED
    # The browser agent ran out of steps or its LLM call failed.
    assert outcome_of({"result": {}, "history": [], "outcome": "failed"}) is Outcome.FAILED
    complete = {"steps_executed": 1, "steps_total": 1, "results": [{"success": True}]}
    assert outcome_of(complete) is Outcome.SUCCESS


def test_payload_mentioning_error_or_author_is_still_success():
    scraped = {"result": {"error": "Invalid ZIP", "author": "x"}, "outcome": "success"}
    assert outcome_of(scraped) is Outcome.SUCCESS
    assert outcome_of({"data": {"error": None}, "error": None}) is Outcome.SUCCESS


@pytest.mark.asyncio
async def test_browser_rejection_never_triggers_an_api_send(env):
    """A browser run may have submitted the form before hitting a login wall."""
    make, _, server = env
    router = make("/ok", "POST")
    site = router._registry.get_site("local.test")
    site.actions[0].tier = Tier.BROWSER
    router._registry.add_site(site)

    async def walled(*a: object) -> dict:
        return {"error": "Auth required", "outcome": "auth_required"}

    router._browser.execute_action = walled
    result = await _run(router)
    assert result["outcome"] == "auth_required"
    assert server.hits == {}


@pytest.mark.asyncio
async def test_redirect_after_post_is_not_retried_or_counted(env):
    make, counts, server = env
    router = make("/303", "POST")
    result = await _run(router)
    assert result["outcome"] == "unexpected_response"
    assert result["location"] == "/done" and result["requires_review"] is True
    assert server.hits == {"/303": 1} and router._browser.calls == 0
    assert counts()[:2] == (0, 1)


@pytest.mark.asyncio
async def test_rate_limit_wins_over_challenge_header(env):
    make, _, server = env
    router = make("/429c")
    result = await _run(router)
    assert result["outcome"] == "rate_limited"
    assert router._browser.calls == 0


def test_cli_exits_nonzero_with_machine_readable_outcome(monkeypatch):
    from typer.testing import CliRunner

    from site2cli import cli

    async def fake_execute(self, domain, action, params):
        return {"outcome": "forbidden", "error": "Forbidden (HTTP 403)", "status_code": 403}

    monkeypatch.setattr(Router, "execute", fake_execute)
    result = CliRunner().invoke(cli.app, ["run", "local.test", "act"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["outcome"] == "forbidden"
