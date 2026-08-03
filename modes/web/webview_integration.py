"""Windows WebView2 integration for HALCYON Web Mode.

This module provides WebView2 browser integration using Windows' built-in
WebView2 Runtime. No separate installation required on Windows 10/11.

The approach:
1. Uses webview2-Microsoft.Web.WebView2.Core package for WinRT access
2. Creates WebView2 control attached to a Qt widget's HWND
3. Provides navigation API compatible with our TabModel
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from PySide6.QtCore import QObject

log = logging.getLogger(__name__)

# Check platform
IS_WINDOWS = sys.platform == "win32"

# Try to import WebView2 WinRT package
WEBVIEW2_AVAILABLE = False
_webview2_core = None

if IS_WINDOWS:
    try:
        import webview2_Microsoft.Web.WebView2.Core as _webview2_core
        WEBVIEW2_AVAILABLE = True
        log.debug("webview2-Microsoft.Web.WebView2.Core imported successfully")
    except ImportError as e:
        log.info("webview2-Microsoft.Web.WebView2.Core not installed: %s", e)
        log.info("Install with: pip install webview2-Microsoft.Web.WebView2.Core")
    except Exception as e:
        log.warning("Failed to import WebView2: %s", e)


def check_webview2_available() -> tuple[bool, str]:
    """Check if WebView2 Runtime is available on this system.
    
    Returns:
        Tuple of (is_available, status_message)
    """
    if not IS_WINDOWS:
        return False, "WebView2 is available on Windows builds only."

    if not WEBVIEW2_AVAILABLE:
        return False, "WebView2 package not installed. Run: pip install webview2-Microsoft.Web.WebView2.Core"

    # Check Windows version (WebView2 requires Windows 10 1809+)
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        version = kernel.GetVersion()
        major = version & 0xFF
        
        if major < 10:
            return False, "WebView2 requires Windows 10 or later."
    except Exception:
        pass

    # Check registry for WebView2 installation
    try:
        import winreg
        keys = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F1E7A9BD-E883-4C4D-93C0-6F7E1B0C136A}"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\EdgeUpdate\Clients\{F1E7A9BD-E883-4C4D-93C0-6F7E1B0C136A}"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F1E7A9BD-E883-4C4D-93C0-6F7E1B0C136A}"),
        ]
        for root, subkey in keys:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    value, _ = winreg.QueryValueEx(key, "pv")
                    if value:
                        return True, f"Microsoft Edge WebView2 Runtime {value} detected."
            except OSError:
                continue
    except ImportError:
        pass

    return False, "Microsoft Edge WebView2 Runtime not found. It should be included with Windows 11 or available via Windows Update on Windows 10."


def create_webview(
    widget: "QWidget | None" = None,
    initial_url: str = "about:blank",
    on_title_changed: Callable[[str], None] | None = None,
    on_url_changed: Callable[[str], None] | None = None,
    on_loading_changed: Callable[[bool], None] | None = None,
    on_navigation_completed: Callable[[bool], None] | None = None,
) -> "WebView | None":
    """Create a WebView2 instance attached to a Qt widget.
    
    Args:
        widget: QWidget to host the WebView2 (its HWND will be used)
        initial_url: URL to load initially
        on_title_changed: Callback when page title changes
        on_url_changed: Callback when URL changes
        on_loading_changed: Callback when loading state changes
        on_navigation_completed: Callback when navigation finishes
        
    Returns:
        WebView instance for navigation control, or None if unavailable
    """
    if not IS_WINDOWS:
        log.warning("WebView2 is only available on Windows")
        return None

    if not WEBVIEW2_AVAILABLE:
        log.warning("WebView2 package not available")
        return None

    try:
        from modes.web.webview2_windows import WebView
        return WebView(
            widget=widget,
            initial_url=initial_url,
            on_title_changed=on_title_changed,
            on_url_changed=on_url_changed,
            on_loading_changed=on_loading_changed,
            on_navigation_completed=on_navigation_completed,
        )
    except Exception as e:
        log.error("Failed to create WebView: %s", e)
        return None


# Re-export for convenience
from modes.web.webview_integration import WebViewBase
__all__ = ["check_webview2_available", "create_webview", "WebViewBase"]
