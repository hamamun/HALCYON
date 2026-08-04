"""Edge WebView2 runtime detection and shared environment bridge (§P3.2).

Halcyon uses Windows' built-in Edge WebView2 directly via pythonnet (Route A,
owner decision 4 Aug 2026). No Qt WebView, no QtWebEngine, nothing bundled.

Detection (§P3.2):
  • Check registry for WebView2 Runtime installation:
    ``HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}``
  • Verify pythonnet bridge and ``Microsoft.Web.WebView2.Core`` load.
  • If either fails, return availability status without crash or bundling.
  • User profile resides in ``%LOCALAPPDATA%\\Halcyon\\webview2_data``.
"""

from __future__ import annotations

import logging
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any

logger = logging.getLogger("modes.web.webview2_runtime")

#: Runtime client GUID for Evergreen WebView2 Runtime
WEBVIEW2_RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

#: Vendor directory holding managed bridge Core.dll and native WebView2Loader.dll
VENDOR_WEBVIEW2_DIR = (
    Path(__file__).resolve().parent.parent.parent / "vendor" / "webview2"
)

#: Default fallback User Agent string (modern Edge/Chromium desktop without WebView2 token)
DEFAULT_EDGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_SHARED_ENVIRONMENT: Any = None
_COM_INITIALIZED: bool = False


def get_user_data_dir() -> Path:
    """Return user data folder for shared WebView2 profile (§P3.2).

    Lives in ``%LOCALAPPDATA%\\Halcyon\\webview2_data``.
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data)
        else:
            base = Path.home() / "AppData" / "Local"
    else:
        base = Path.home() / ".local" / "share"
    data_dir = base / "Halcyon" / "webview2_data"
    return data_dir


def _check_runtime_registry() -> bool:
    """Return True if WebView2 Runtime is registered in Windows registry."""
    if sys.platform != "win32":
        return False

    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return False

    registry_paths = [
        (
            winreg.HKEY_LOCAL_MACHINE,
            f"SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_RUNTIME_GUID}",
        ),
        (
            winreg.HKEY_LOCAL_MACHINE,
            f"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_RUNTIME_GUID}",
        ),
        (
            winreg.HKEY_CURRENT_USER,
            f"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_RUNTIME_GUID}",
        ),
    ]

    for root_key, sub_key in registry_paths:
        try:
            with winreg.OpenKey(root_key, sub_key, 0, winreg.KEY_READ) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
                if version and str(version).strip() != "" and str(version) != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def _setup_vendor_path() -> None:
    """Add vendor/webview2 to sys.path and PATH so bridge DLLs can be found."""
    if VENDOR_WEBVIEW2_DIR.exists():
        vendor_str = str(VENDOR_WEBVIEW2_DIR)
        if vendor_str not in sys.path:
            sys.path.insert(0, vendor_str)
        path_env = os.environ.get("PATH", "")
        if vendor_str not in path_env.split(os.pathsep):
            os.environ["PATH"] = f"{vendor_str}{os.pathsep}{path_env}"


def check_webview2_available() -> tuple[bool, str]:
    """Check if built-in Edge WebView2 runtime and pythonnet bridge are ready.

    Returns:
        (True, "OK") if available, or (False, "WebView2 is not available") on failure.
    """
    if sys.platform != "win32":
        return (
            False,
            "WebView2 is not available",
        )

    if not _check_runtime_registry():
        return (
            False,
            "WebView2 is not available",
        )

    try:
        _setup_vendor_path()
        import clr  # type: ignore[import-not-found]

        clr.AddReference("Microsoft.Web.WebView2.Core")
        from Microsoft.Web.WebView2.Core import CoreWebView2Environment  # type: ignore[import-not-found]

        version = CoreWebView2Environment.GetAvailableBrowserVersionString(None)
        if not version:
            return (False, "WebView2 is not available")
        return (True, "OK")
    except Exception as exc:
        logger.debug("WebView2 import test failed: %s", exc)
        return (False, "WebView2 is not available")


def is_webview2_available() -> bool:
    """Return True if Edge WebView2 is available on this system."""
    available, _ = check_webview2_available()
    return available


def get_stage_error_message() -> str:
    """Return the exact stage error message when runtime is missing (§P3.2)."""
    return "WebView2 is not available"


def init_pythonnet_com() -> None:
    """Initialize COM and pythonnet bridge before any view is created (§P3.2)."""
    global _COM_INITIALIZED
    if _COM_INITIALIZED or sys.platform != "win32":
        return

    try:
        _setup_vendor_path()
        import clr  # type: ignore[import-not-found]

        # Ensure Python threading/COM apartment state is compatible if needed
        _COM_INITIALIZED = True
        logger.debug("COM and pythonnet initialized for WebView2")
    except Exception as exc:
        logger.debug("Failed to initialize pythonnet COM: %s", exc)


def get_shared_environment() -> Any:
    """Return the singleton CoreWebView2Environment shared across all tabs (§P3.2)."""
    global _SHARED_ENVIRONMENT
    if _SHARED_ENVIRONMENT is not None:
        return _SHARED_ENVIRONMENT

    if not is_webview2_available():
        return None

    try:
        init_pythonnet_com()
        from Microsoft.Web.WebView2.Core import CoreWebView2Environment  # type: ignore[import-not-found]

        data_dir = get_user_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        task = CoreWebView2Environment.CreateAsync(None, str(data_dir), None)
        # Synchronous wait for singleton initialization during setup
        env = task.ConfigureAwait(False).GetAwaiter().GetResult()
        _SHARED_ENVIRONMENT = env
        return _SHARED_ENVIRONMENT
    except Exception as exc:
        logger.warning("Failed to create shared CoreWebView2Environment: %s", exc)
        return None


def get_anti_bot_user_agent(default_ua: str = "") -> str:
    """Return User-Agent string with 'WebView2' stripped (§P3.1, §P3.2).

    Login-friendly / anti-bot: makes embedded WebView2 look like standard desktop Edge.
    """
    ua = default_ua or DEFAULT_EDGE_USER_AGENT
    tokens = ua.split(" ")
    cleaned_tokens = [
        token for token in tokens if "WebView2" not in token and "webview2" not in token.lower()
    ]
    cleaned = " ".join(cleaned_tokens).strip()
    return cleaned or DEFAULT_EDGE_USER_AGENT


def get_anti_bot_init_script() -> str:
    """Return JavaScript to inject on document creation to hide navigator.webdriver."""
    return (
        "try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } "
        "catch (e) {}"
    )


def resolve_url_or_search(query: str) -> str:
    """Resolve user input to a navigation URL or Google search (§P3.1, §P3.4).

    - Valid schemes (http, https, file, about, data, qrc) passed through.
    - Bare domains or localhost automatically get https:// / http://.
    - Other text queries become Google searches (default search engine).
    """
    text = (query or "").strip()
    if not text:
        return "https://www.google.com"

    lower = text.lower()
    for scheme in ("http://", "https://", "file://", "about:", "data:", "qrc:"):
        if lower.startswith(scheme):
            return text

    if lower.startswith("localhost:") or lower == "localhost":
        return f"http://{text}"

    # Check if text looks like a domain name or host/path without spaces
    if " " not in text and ("." in text or "/" in text):
        return f"https://{text}"

    encoded = urllib.parse.quote_plus(text)
    return f"https://www.google.com/search?q={encoded}"
