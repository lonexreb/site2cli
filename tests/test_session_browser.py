"""Named sessions through the daemon with a real browser (issue #29).

Skipped when Chromium is not installed. Everything else is local: a fixture
HTTP server, an in-process daemon on a Unix socket, and recorded workflows.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from site2cli.config import get_config, reset_config
from site2cli.daemon.client import DaemonClient
from site2cli.daemon.server import DaemonServer
from site2cli.models import RecordedWorkflow, SiteAction, SiteEntry, Tier, WorkflowStep
from site2cli.registry import SiteRegistry
from site2cli.tiers.cached_workflow import save_workflow

ME_PAGE = (
    "<html><body><p id='c'>cookie:%s</p><p id='ls'></p><script>"
    "document.getElementById('ls').textContent='storage:'+localStorage.getItem('token')"
    "</script></body></html>"
)
LOGIN_PAGE = "<html><body>ok<script>localStorage.setItem('token','t1')</script></body></html>"


class _Site(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        cookie = self.headers.get("Cookie", "")
        user = cookie.split("user=")[1].split(";")[0] if "user=" in cookie else "anon"
        body = {"/login": LOGIN_PAGE, "/me": ME_PAGE % user}.get(self.path, "<html></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        if self.path == "/login":
            self.send_header("Set-Cookie", "user=alice; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def base_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def data_dir(monkeypatch: pytest.MonkeyPatch):
    # Unix socket paths are limited to ~104 bytes; pytest's tmp_path is too long.
    path = Path(tempfile.mkdtemp(prefix="s2c"))
    monkeypatch.setenv("XDG_DATA_HOME", str(path))
    reset_config()
    yield path
    reset_config()
    shutil.rmtree(path, ignore_errors=True)


def _register_site(base_url: str) -> None:
    config = get_config()
    actions = []
    for name, path in (("login", "/login"), ("whoami", "/me")):
        steps = [
            WorkflowStep(action="navigate", url=base_url + path),
            WorkflowStep(action="extract", selector="body"),
        ]
        workflow = RecordedWorkflow(
            id=f"wf-{name}", site_domain="local.test", action_name=name, steps=steps
        )
        save_workflow(workflow, config.workflows_dir)
        actions.append(SiteAction(name=name, tier=Tier.WORKFLOW, workflow_id=workflow.id))
    registry = SiteRegistry(config.db_path)
    registry.add_site(SiteEntry(domain="local.test", base_url=base_url, actions=actions))
    registry.close()


def _body(result: dict) -> str:
    assert result.get("outcome", "success") == "success", result
    return result["results"][-1]["extracted"]


@pytest.mark.asyncio
async def test_named_sessions_persist_isolate_and_close(base_url, data_dir):
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            await (await pw.chromium.launch()).close()
    except Exception as exc:  # package or browser binary missing
        pytest.skip(f"Chromium not available: {type(exc).__name__}")

    _register_site(base_url)
    server = DaemonServer(get_config().daemon_socket_path)
    task = asyncio.create_task(server.run())
    while not server.socket_path.exists():
        await asyncio.sleep(0.05)
    client = DaemonClient(server.socket_path)
    mgr = server._session_mgr

    try:
        await client.execute("local.test", "login", session="a")
        # The first action has finished; the session must still be live.
        me = _body(await client.execute("local.test", "whoami", session="a"))
        assert "cookie:alice" in me and "storage:t1" in me

        other = _body(await client.execute("local.test", "whoami", session="b"))
        assert "cookie:anon" in other and "storage:null" in other

        assert sorted(await client.list_sessions()) == ["a", "b"]
        _, ctx_a = mgr.get("a")
        assert len(ctx_a.pages) <= 1  # per-call pages are closed

        # A browser that died underneath its session is reported, not reused.
        browser_b, _ = mgr.get("b")
        await browser_b.close()
        dead = await client.execute("local.test", "whoami", session="b")
        assert dead["outcome"] == "failed" and "lost its browser" in dead["error"]
        assert await client.list_sessions() == ["a"]

        await client.close_session("a")
        await client.close_session("a")  # second close is a no-op
        assert await client.list_sessions() == []
        assert not ctx_a.browser.is_connected()
    finally:
        await client.send("close_all_sessions", {})
        await client.shutdown()
        await task
