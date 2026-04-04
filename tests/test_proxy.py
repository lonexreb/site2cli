"""Tests for proxy configuration."""

from __future__ import annotations

from site2cli.config import ProxyConfig


def test_proxy_config_defaults():
    proxy = ProxyConfig()
    assert proxy.url is None
    assert proxy.server is None
    assert proxy.username is None
    assert proxy.password is None
    assert proxy.bypass == []


def test_get_proxy_url_from_url():
    proxy = ProxyConfig(url="http://proxy.example.com:8080")
    assert proxy.get_proxy_url() == "http://proxy.example.com:8080"


def test_get_proxy_url_from_server():
    proxy = ProxyConfig(server="http://proxy.example.com:8080")
    assert proxy.get_proxy_url() == "http://proxy.example.com:8080"


def test_get_proxy_url_with_auth():
    proxy = ProxyConfig(
        server="http://proxy.example.com:8080",
        username="user",
        password="pass",
    )
    assert proxy.get_proxy_url() == "http://user:pass@proxy.example.com:8080"


def test_get_proxy_url_with_auth_no_scheme():
    proxy = ProxyConfig(server="proxy.example.com:8080", username="user", password="pass")
    assert proxy.get_proxy_url() == "http://user:pass@proxy.example.com:8080"


def test_get_proxy_url_none():
    proxy = ProxyConfig()
    assert proxy.get_proxy_url() is None


def test_get_playwright_proxy():
    proxy = ProxyConfig(url="http://proxy.example.com:8080", bypass=["localhost", "127.0.0.1"])
    result = proxy.get_playwright_proxy()
    assert result == {"server": "http://proxy.example.com:8080", "bypass": "localhost,127.0.0.1"}


def test_get_playwright_proxy_no_bypass():
    proxy = ProxyConfig(url="http://proxy.example.com:8080")
    result = proxy.get_playwright_proxy()
    assert result == {"server": "http://proxy.example.com:8080"}


def test_get_playwright_proxy_none():
    proxy = ProxyConfig()
    assert proxy.get_playwright_proxy() is None


def test_get_httpx_proxy():
    proxy = ProxyConfig(url="http://proxy.example.com:8080")
    assert proxy.get_httpx_proxy() == "http://proxy.example.com:8080"


def test_get_httpx_proxy_none():
    proxy = ProxyConfig()
    assert proxy.get_httpx_proxy() is None


def test_proxy_url_takes_precedence():
    """If both url and server are set, url takes precedence."""
    proxy = ProxyConfig(url="http://primary:8080", server="http://secondary:9090")
    assert proxy.get_proxy_url() == "http://primary:8080"


def test_proxy_config_in_main_config():
    """Proxy config is accessible from the top-level Config."""
    from site2cli.config import Config

    config = Config()
    assert config.proxy is not None
    assert config.proxy.get_proxy_url() is None

    config.proxy.url = "http://myproxy:8080"
    assert config.proxy.get_proxy_url() == "http://myproxy:8080"
