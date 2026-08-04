"""Unit tests for WebView2 runtime detection and environment bridge (§P3.2)."""

from __future__ import annotations

import sys
from pathlib import Path

from modes.web import webview2_runtime


def test_webview2_runtime_detection_in_current_env():
    """Verify check_webview2_available returns expected status without error."""
    available, message = webview2_runtime.check_webview2_available()
    assert isinstance(available, bool)
    assert isinstance(message, str)
    if sys.platform != "win32":
        assert not available
        assert message == "WebView2 is not available"
    assert webview2_runtime.is_webview2_available() == available


def test_webview2_user_data_dir():
    """Verify profile lives in %LOCALAPPDATA%\\Halcyon\\webview2_data (§P3.2)."""
    data_dir = webview2_runtime.get_user_data_dir()
    assert isinstance(data_dir, Path)
    assert data_dir.parts[-2:] == ("Halcyon", "webview2_data")


def test_webview2_anti_bot_user_agent():
    """User agent must strip 'WebView2' token to remain login-friendly (§P3.1, §P3.2)."""
    ua_with_token = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 "
        "Edg/128.0.0.0 WebView2/1.0.2651.64"
    )
    cleaned = webview2_runtime.get_anti_bot_user_agent(ua_with_token)
    assert "WebView2" not in cleaned
    assert "Chrome/128.0.0.0" in cleaned
    assert "Safari/537.36" in cleaned

    default_cleaned = webview2_runtime.get_anti_bot_user_agent("")
    assert "WebView2" not in default_cleaned
    assert "Mozilla/5.0" in default_cleaned


def test_webview2_anti_bot_init_script():
    """Verify JavaScript to hide navigator.webdriver is generated (§P3.1)."""
    script = webview2_runtime.get_anti_bot_init_script()
    assert "navigator" in script
    assert "webdriver" in script
    assert "undefined" in script


def test_webview2_url_or_search_resolution():
    """Verify address bar URL vs search resolution (§P3.1, §P3.4)."""
    assert (
        webview2_runtime.resolve_url_or_search("https://example.com")
        == "https://example.com"
    )
    assert (
        webview2_runtime.resolve_url_or_search("example.com")
        == "https://example.com"
    )
    assert (
        webview2_runtime.resolve_url_or_search("localhost:8080")
        == "http://localhost:8080"
    )
    assert (
        webview2_runtime.resolve_url_or_search("hello world")
        == "https://www.google.com/search?q=hello+world"
    )
    assert (
        webview2_runtime.resolve_url_or_search("")
        == "https://www.google.com"
    )
    assert (
        webview2_runtime.resolve_url_or_search("   ")
        == "https://www.google.com"
    )


def test_webview2_stage_error_message():
    """When runtime is missing, stage must show 'WebView2 is not available' (§P3.2)."""
    assert webview2_runtime.get_stage_error_message() == "WebView2 is not available"


def test_webview2_runtime_windows_mock_detection(monkeypatch):
    """Verify check_webview2_available returns (True, 'OK') when Windows runtime is present."""
    import types

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(webview2_runtime, "_check_runtime_registry", lambda: True)

    mock_clr = types.ModuleType("clr")
    mock_clr.AddReference = lambda name: None

    mock_core = types.ModuleType("Microsoft.Web.WebView2.Core")
    mock_env_cls = type(
        "CoreWebView2Environment",
        (),
        {
            "GetAvailableBrowserVersionString": staticmethod(
                lambda folder: "128.0.2651.64"
            )
        },
    )
    mock_core.CoreWebView2Environment = mock_env_cls

    monkeypatch.setitem(sys.modules, "clr", mock_clr)
    monkeypatch.setitem(sys.modules, "Microsoft.Web.WebView2.Core", mock_core)

    available, message = webview2_runtime.check_webview2_available()
    assert available is True
    assert message == "OK"

