"""Unit tests for WebView2 per-tab host and popup routing (§P3.2, §P3.4)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject

from modes.web.webview2_host import WebViewHost


class MockNewWindowArgs:
    def __init__(self, uri: str) -> None:
        self.Handled = False
        self.Uri = uri


def test_webview2_host_initial_properties():
    """Verify default properties of a new WebViewHost tab instance."""
    host = WebViewHost()
    assert host.url == ""
    assert host.title == ""
    assert not host.loading
    assert not host.isReady
    assert host.errorMessage == ""


def test_webview2_host_not_available_fallback():
    """When WebView2 is not available, init_controller fails gracefully without crash (§P3.2)."""
    host = WebViewHost()
    errors: list[str] = []
    host.errorOccurred.connect(errors.append)

    # In Linux CI / non-Windows, init_controller should return False and emit error message
    with patch("modes.web.webview2_runtime.is_webview2_available", return_value=False):
        ok = host.init_controller(0)
        assert not ok
        assert host.errorMessage == "WebView2 is not available"
        assert errors == ["WebView2 is not available"]

    # Methods must safely no-op without raising when controller is absent
    host.navigate("https://example.com")
    assert host.url == "https://example.com"
    host.go_back()
    host.go_forward()
    host.reload()
    host.stop()
    host.set_bounds(10, 10, 800, 600)
    host.set_visible(False)
    host.close()
    assert not host.isReady


def test_webview2_host_new_window_routing():
    """Site popups/new-windows must be handled by setting Handled=True and emitting URL (§P3.4)."""
    args = MockNewWindowArgs("https://example.com/popup")
    routed_urls: list[str] = []

    WebViewHost.handle_new_window_request(args, routed_urls.append)

    assert args.Handled is True, "Must prevent default external Edge browser window"
    assert routed_urls == ["https://example.com/popup"], "Must route URL to Halcyon tab model"


def test_webview2_host_signals():
    """Verify Qt signals emit correctly on property updates."""
    host = WebViewHost()
    urls: list[str] = []
    host.urlChanged.connect(urls.append)

    host.navigate("example.com")
    assert urls == ["https://example.com"]
    assert host.url == "https://example.com"


def test_webview2_host_does_not_try_to_fullscreen_its_qobject_parent():
    """The host's parent is BrowserContext, not the QML Window."""
    source = Path(__file__).resolve().parent.parent.joinpath(
        "modes", "web", "webview2_host.py"
    ).read_text(encoding="utf-8")

    assert "showFullScreen" not in source
    assert "showNormal" not in source
    assert "fullscreenChanged.emit" in source
