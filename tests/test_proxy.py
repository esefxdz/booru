"""effective_proxy: app setting first, else the system proxy, never for LAN hosts."""
import pytest

from core import proxy, settings


@pytest.fixture
def system(monkeypatch):
    monkeypatch.setattr(settings.manager, "proxy_url", "", raising=False)
    monkeypatch.setattr(proxy, "_system_proxies",
                        lambda: {"http": "http://127.0.0.1:3128", "https": "http://127.0.0.1:3128"})
    monkeypatch.setattr(proxy.urllib.request, "proxy_bypass", lambda host: host == "skip.example")
    proxy._bypassed.cache_clear()
    yield
    proxy._bypassed.cache_clear()


def test_app_proxy_wins(system, monkeypatch):
    monkeypatch.setattr(settings.manager, "proxy_url", "socks5://10.0.0.1:9050", raising=False)
    assert proxy.effective_proxy("https://e621.net/x") == "socks5://10.0.0.1:9050"


def test_system_proxy_used_when_app_proxy_empty(system):
    assert proxy.effective_proxy("https://static1.e621.net/a.webm") == "http://127.0.0.1:3128"
    assert proxy.effective_proxy() == "http://127.0.0.1:3128"


def test_lan_and_bypassed_hosts_go_direct(system):
    assert proxy.effective_proxy("http://192.168.1.20:8080/") == ""
    assert proxy.effective_proxy("http://localhost/") == ""
    assert proxy.effective_proxy("https://skip.example/") == ""


def test_no_proxy_anywhere_is_direct(monkeypatch):
    monkeypatch.setattr(settings.manager, "proxy_url", "", raising=False)
    monkeypatch.setattr(proxy, "_system_proxies", lambda: {})
    assert proxy.effective_proxy("https://safebooru.org/") == ""


def test_bypass_sessions_get_the_system_proxy(system, monkeypatch):
    import boorus
    import cloudflare_bypasser
    monkeypatch.setitem(boorus.REGISTRY, "px_test", {"url": "https://e621.net", "api_type": "e621"})
    s = cloudflare_bypasser.get_session("px_test")
    assert s.proxy_url == "http://127.0.0.1:3128"
