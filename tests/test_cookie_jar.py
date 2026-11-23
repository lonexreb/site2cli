"""Stored browser cookies -> scoped HTTPX jar (issue #28).

Uses real HTTPX client construction and request preparation throughout.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from site2cli.auth.cookies import CookieManager, to_httpx_cookies
from site2cli.config import reset_config
from site2cli.discovery.client_generator import generate_client_code
from site2cli.models import EndpointInfo, SiteEntry
from site2cli.tiers.direct_api import DirectAPIExecutor


@pytest.fixture(autouse=True)
def _isolate_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    yield
    reset_config()


def _cookie(name: str, value: str, domain: str = "example.test", **kw: object) -> dict:
    return {"name": name, "value": value, "domain": domain, "path": "/", **kw}


def _sent(jar: httpx.Cookies, url: str) -> str:
    """The Cookie header HTTPX would actually send to ``url``."""
    with httpx.Client(cookies=jar) as client:
        return client.build_request("GET", url).headers.get("cookie", "")


def test_playwright_list_constructs_a_client():
    # This exact input raised "too many values to unpack" when passed raw.
    jar = to_httpx_cookies([_cookie("session", "v", httpOnly=True, sameSite="Lax", expires=-1)])
    assert _sent(jar, "http://example.test/") == "session=v"


def test_same_name_on_different_paths_survives_storage_and_scoping():
    mgr = CookieManager()
    mgr.set("example.test", "tok", "root", path="/")
    mgr.set("example.test", "tok", "admin", path="/admin")
    mgr.set("example.test", "tok", "admin2", path="/admin")  # replaces only /admin
    stored = mgr.list("example.test")
    assert sorted((c["path"], c["value"]) for c in stored) == [("/", "root"), ("/admin", "admin2")]

    jar = to_httpx_cookies(stored)
    assert _sent(jar, "http://example.test/shop") == "tok=root"
    assert "tok=admin2" in _sent(jar, "http://example.test/admin/users")


def test_secure_expired_and_session_cookies():
    jar = to_httpx_cookies([
        _cookie("sec", "1", secure=True),
        _cookie("old", "1", expires=time.time() - 60),
        _cookie("live", "1", expires=time.time() + 3600),
        _cookie("sess", "1", expires=-1),
    ])
    assert _sent(jar, "http://example.test/") == "live=1; sess=1"
    assert "sec=1" in _sent(jar, "https://example.test/")


def test_cookies_stay_on_their_site():
    jar = to_httpx_cookies([_cookie("a", "1", domain="example.test")])
    assert _sent(jar, "http://example.test/") == "a=1"
    assert _sent(jar, "http://evil.test/") == ""
    assert _sent(jar, "http://notexample.test/") == ""
    assert _sent(jar, "http://example.test.evil.test/") == ""


def test_empty_and_legacy_flat_inputs():
    assert _sent(to_httpx_cookies([]), "http://example.test/") == ""
    assert _sent(to_httpx_cookies(None), "http://example.test/") == ""
    assert _sent(to_httpx_cookies({"a": "b"}), "http://example.test/") == "a=b"


def test_malformed_cookie_is_skipped_without_leaking_its_value():
    jar = to_httpx_cookies([{"value": "super-secret"}, _cookie("ok", "1")])
    assert _sent(jar, "http://example.test/") == "ok=1"


class _Echo(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = ('{"cookie": "%s"}' % self.headers.get("Cookie", "")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("use_client", [False, True])
async def test_stored_cookies_reach_local_server_on_both_paths(tmp_path, use_client):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        CookieManager().set_all("local.test", [
            _cookie("session", "abc", domain="127.0.0.1"),
            _cookie("other", "x", domain="elsewhere.test"),
        ])
        site = SiteEntry(domain="local.test", base_url=base)
        if use_client:
            spec = {"info": {"title": "L"}, "paths": {"/me": {"get": {"operationId": "me"}}}}
            path = tmp_path / "client.py"
            path.write_text(generate_client_code(spec))
            site.client_module_path = str(path)
        endpoint = EndpointInfo(method="GET", path_pattern="/me", description="me")

        result = await DirectAPIExecutor().execute(site, endpoint, {})
    finally:
        srv.shutdown()
        srv.server_close()

    assert result["transport"] == ("generated_client" if use_client else "http")
    assert result["data"] == {"cookie": "session=abc"}
