"""Small platform boundary for HALCYON's native WebView2 browser surface."""
from __future__ import annotations

import importlib
import logging
import sys
from abc import ABC, abstractmethod
from typing import Callable

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"
WEBVIEW2_AVAILABLE = False
PACKAGE_NAME = "webview2-Microsoft.Web.WebView2.Core"
WEBVIEW2_MODULE = "webview2.microsoft.web.webview2.core"

if IS_WINDOWS:
    try:
        importlib.import_module(WEBVIEW2_MODULE)
        WEBVIEW2_AVAILABLE = True
    except ImportError as exc:
        log.info("%s is not installed: %s", PACKAGE_NAME, exc)
    except Exception as exc:
        log.warning("WebView2 projection import failed: %s", exc)


def check_webview2_available() -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "WebView2 is available on Windows builds only."
    if not WEBVIEW2_AVAILABLE:
        return False, f"WebView2 package not installed. Run: pip install {PACKAGE_NAME}"
    # Environment/controller creation remains the definitive runtime check.
    return True, "WebView2 package detected; browser engine will start when Web mode opens."


class WebViewBase(ABC):
    @abstractmethod
    def navigate(self, url: str) -> None: ...
    @abstractmethod
    def go_back(self) -> None: ...
    @abstractmethod
    def go_forward(self) -> None: ...
    @abstractmethod
    def reload(self) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
    @abstractmethod
    def update_bounds(self, x: int, y: int, width: int, height: int) -> None: ...

    def set_visible(self, visible: bool) -> None: pass
    @property
    def is_ready(self) -> bool:
        """True once the native controller exists and can render content.

        Distinct from "the WebView2 package imports".  The package being
        installed does not mean the runtime/controller came up, so callers that
        decide whether to show native content (or fall back to a message) must
        gate on this, not on availability alone.
        """
        return False
    @property
    def can_go_back(self) -> bool: return False
    @property
    def can_go_forward(self) -> bool: return False
    @property
    def current_url(self) -> str: return ""
    @property
    def current_title(self) -> str: return ""


def create_webview(
    parent_hwnd: int,
    initial_url: str = "about:blank",
    on_title_changed: Callable[[str], None] | None = None,
    on_url_changed: Callable[[str], None] | None = None,
    on_loading_changed: Callable[[bool], None] | None = None,
    on_navigation_completed: Callable[[bool], None] | None = None,
    on_init_error: Callable[[str], None] | None = None,
) -> WebViewBase | None:
    if not IS_WINDOWS or not WEBVIEW2_AVAILABLE or not parent_hwnd:
        return None
    try:
        from modes.web.webview2_windows import WebView
        return WebView(parent_hwnd, initial_url, on_title_changed, on_url_changed,
                       on_loading_changed, on_navigation_completed, on_init_error)
    except Exception as exc:
        if on_init_error:
            on_init_error(f"Could not create WebView2 controller: {exc}")
        log.exception("Could not create WebView2 controller: %s", exc)
        return None


__all__ = ["IS_WINDOWS", "WEBVIEW2_AVAILABLE", "WebViewBase", "check_webview2_available", "create_webview"]
