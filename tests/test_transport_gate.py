"""Direct-HTTP eligibility is based on evidence, not on capture (issue #30)."""

from __future__ import annotations

import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from site2cli.discovery.client_generator import generate_client_code
from site2cli.models import EndpointInfo, SiteAction, SiteEntry, Tier, Transport
from site2cli.registry import SiteRegistry
from site2cli.router import Router


class _Api(BaseHTTPRequestHandler):
    def _serve(self) -> None:
        self.server.hits.append((self.command, self.path))  # type: ignore[attr-defined]
        status = 403 if self.path == "/blocked" else 200
        body = b'{"ok": true}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _serve  # noqa: N815

    def log_message(self, *args: object) -> None:
        pass


class _NoAuth:
    def get_auth_headers(self, *a: object) -> dict:
        return {}

    def get_httpx_cookies(self, *a: object) -> None:
        return None


class _Browser:
    def __init__(self) -> None:
        self.calls = 0

    async def execute_action(self, *a: object) -> dict:
        self.calls += 1
        return {"result": {"ok": True}, "history": [], "outcome": "success"}


@pytest.fixture
def env(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    srv.hits = []  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    registry = SiteRegistry(tmp_path / "t.db")

    def make(path="/items", method="GET", tier=Tier.API, transport=Transport.HTTP_CANDIDATE):
        action = SiteAction(
            name="act",
            tier=tier,
            transport=transport,
            endpoint=EndpointInfo(method=method, path_pattern=path),
        )
        registry.add_site(SiteEntry(
            domain="local.test",
            base_url=f"http://127.0.0.1:{srv.server_address[1]}",
            actions=[action],
        ))
        router = Router(registry)
        router._direct_api._auth = _NoAuth()
        router._browser = _Browser()
        return router

    def action() -> SiteAction:
        return registry.get_site("local.test").actions[0]

    yield make, action, srv, registry
    registry.close()
    srv.shutdown()
    srv.server_close()


@pytest.mark.asyncio
async def test_candidate_becomes_verified_only_by_a_real_direct_success(env):
    make, action, srv, _ = env
    router = make()
    assert action().transport is Transport.HTTP_CANDIDATE  # as discovery registers it

    result = await router.execute("local.test", "act", {})

    assert result["transport"] == "http" and result["via_proxy"] is False
    assert srv.hits == [("GET", "/items")]
    assert action().transport is Transport.HTTP_VERIFIED


@pytest.mark.asyncio
async def test_rejection_invalidates_verified_evidence_but_keeps_endpoint(env):
    make, action, _, _ = env
    router = make(path="/blocked", transport=Transport.HTTP_VERIFIED)
    await router.execute("local.test", "act", {})
    assert action().transport is Transport.HTTP_CANDIDATE
    assert action().endpoint.path_pattern == "/blocked"


@pytest.mark.asyncio
async def test_browser_required_never_uses_http_even_after_many_successes(env):
    make, action, srv, _ = env
    router = make(method="POST", transport=Transport.BROWSER_REQUIRED)

    for _ in range(7):
        result = await router.execute("local.test", "act", {})
        assert result["transport"] == "browser"

    assert srv.hits == []  # no direct request, not even to probe
    assert router._browser.calls == 7
    assert action().transport is Transport.BROWSER_REQUIRED
    assert action().success_count == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "transport", "promoted"),
    [
        ("POST", Transport.HTTP_CANDIDATE, False),  # browser success proves nothing
        ("POST", Transport.HTTP_VERIFIED, True),
        ("GET", Transport.HTTP_CANDIDATE, True),  # safe read: first call is the check
    ],
)
async def test_workflow_to_api_promotion_needs_evidence(env, method, transport, promoted):
    make, action, srv, registry = env
    router = make(method=method, tier=Tier.WORKFLOW, transport=transport)
    for _ in range(5):
        registry.record_action_result("local.test", "act", success=True)

    router._maybe_promote("local.test", action())

    assert (action().tier is Tier.API) is promoted
    assert srv.hits == []  # promotion itself never sends anything


def test_existing_database_migrates_to_candidate(tmp_path):
    db = tmp_path / "old.db"
    registry = SiteRegistry(db)
    registry.add_site(SiteEntry(domain="d", base_url="http://d", actions=[
        SiteAction(name="a", tier=Tier.API, endpoint=EndpointInfo(method="GET", path_pattern="/"))
    ]))
    registry.close()
    conn = sqlite3.connect(db)  # simulate a pre-migration database
    conn.execute("ALTER TABLE actions DROP COLUMN transport")
    conn.commit()
    conn.close()

    reopened = SiteRegistry(db)
    action = reopened.get_site("d").actions[0]
    assert action.transport is Transport.HTTP_CANDIDATE and action.tier is Tier.API
    reopened.close()


def test_generated_client_passes_the_configured_proxy_to_httpx(monkeypatch):
    seen: dict = {}
    real = httpx.Client

    def spy(**kwargs: object) -> httpx.Client:
        seen.update(kwargs)
        return real()

    namespace: dict = {}
    exec(generate_client_code({"info": {"title": "P"}, "paths": {}}), namespace)  # noqa: S102
    monkeypatch.setattr(namespace["httpx"], "Client", spy)
    namespace["PClient"](proxy="http://proxy.test:8080").close()
    assert seen["proxy"] == "http://proxy.test:8080"
