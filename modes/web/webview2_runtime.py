"""Edge WebView2 runtime discovery and the shared browser environment.

The Web mode deliberately talks to Windows' installed Edge WebView2 Runtime
through the small managed SDK bridge in ``vendor/webview2``.  The two DLLs in
that directory are *not* a browser; they only let pythonnet locate the runtime
that Windows/Edge maintains.

This module has no Qt Quick dependency.  It is safe to import on Linux/macOS so
that the rest of Halcyon can still start and the Web stage can explain why it is
unavailable instead of becoming a blank surface.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any

logger = logging.getLogger("modes.web.webview2_runtime")

# Evergreen WebView2 Runtime client GUID published by Microsoft.
WEBVIEW2_RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

ROOT = Path(__file__).resolve().parents[2]
VENDOR_WEBVIEW2_DIR = ROOT / "vendor" / "webview2"
CORE_DLL_NAME = "Microsoft.Web.WebView2.Core.dll"
LOADER_DLL_NAME = "WebView2Loader.dll"

DEFAULT_EDGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_SHARED_ENVIRONMENT: Any = None
_SHARED_ENVIRONMENT_TASK: Any = None
_COM_INITIALIZED = False
_COM_OWNED_BY_HALCYON = False
_DLL_DIRECTORY_HANDLES: list[Any] = []
_DLL_DIRECTORY_PATHS: set[str] = set()


# ---------------------------------------------------------------------------
# Paths and process setup
# ---------------------------------------------------------------------------
def get_user_data_dir() -> Path:
    """Return the persistent profile directory used by every WebView2 tab."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        # Development/CI fallback.  It is never used for an actual WebView2
        # controller, but keeping this deterministic makes the helper testable.
        base = Path.home() / ".local" / "share"
    return base / "Halcyon" / "webview2_data"


def _candidate_vendor_dirs() -> list[Path]:
    """Return source and frozen-build locations for the bridge files."""
    candidates = [VENDOR_WEBVIEW2_DIR]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "vendor" / "webview2")

    unique: list[Path] = []
    for directory in candidates:
        if directory not in unique:
            unique.append(directory)
    return unique


def _setup_vendor_path() -> list[Path]:
    """Make the SDK bridge and its native loader discoverable on Windows.

    Editing ``PATH`` alone is unreliable on modern Python/Windows: DLL search
    directories are captured by the loader.  ``os.add_dll_directory`` is the
    correct API; its handles are held for the process lifetime so the directory
    stays active while a WebView controller is alive.
    """
    existing = [directory for directory in _candidate_vendor_dirs() if directory.is_dir()]
    for directory in existing:
        value = str(directory)
        if value not in sys.path:
            sys.path.insert(0, value)

        path_parts = os.environ.get("PATH", "").split(os.pathsep)
        if value not in path_parts:
            os.environ["PATH"] = value + os.pathsep + os.environ.get("PATH", "")

        add_dll_directory = getattr(os, "add_dll_directory", None)
        if sys.platform == "win32" and callable(add_dll_directory):
            try:
                # Calling it more than once is harmless but leaks a process
                # handle, so remember paths independently of the opaque handle
                # object returned by CPython.
                if value not in _DLL_DIRECTORY_PATHS:
                    handle = add_dll_directory(value)
                    _DLL_DIRECTORY_HANDLES.append(handle)
                    _DLL_DIRECTORY_PATHS.add(value)
            except (OSError, AttributeError) as exc:
                logger.debug("could not add WebView2 DLL directory %s: %s", directory, exc)
    return existing


def _find_core_dll() -> Path | None:
    for directory in _candidate_vendor_dirs():
        candidate = directory / CORE_DLL_NAME
        if candidate.is_file():
            return candidate
    return None


def _find_loader_dll() -> Path | None:
    for directory in _candidate_vendor_dirs():
        candidate = directory / LOADER_DLL_NAME
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Runtime detection and CLR / COM bridge
# ---------------------------------------------------------------------------
def _check_runtime_registry() -> bool:
    """Return whether Evergreen WebView2 is registered for this Windows user."""
    if sys.platform != "win32":
        return False

    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return False

    paths = (
        (winreg.HKEY_LOCAL_MACHINE,
         f"SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_RUNTIME_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE,
         f"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_RUNTIME_GUID}"),
        (winreg.HKEY_CURRENT_USER,
         f"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_RUNTIME_GUID}"),
    )
    for root, subkey in paths:
        try:
            with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
            if version and str(version).strip() not in {"", "0.0.0.0"}:
                return True
        except OSError:
            continue
    return False


def _add_core_reference() -> None:
    """Load the managed SDK bridge through pythonnet.

    Loading by absolute filename is important for source checkouts: .NET's
    ordinary assembly probing does not promise to search a Python package's
    ``vendor`` directory.  The assembly-name fallback keeps test doubles and a
    globally installed bridge usable.
    """
    _setup_vendor_path()
    import clr  # type: ignore[import-not-found]

    core_dll = _find_core_dll()
    if core_dll is not None:
        try:
            clr.AddReference(str(core_dll))
            return
        except Exception as exc:
            logger.debug("absolute WebView2 bridge reference failed: %s", exc)
    clr.AddReference("Microsoft.Web.WebView2.Core")


def init_pythonnet_com() -> bool:
    """Initialise the GUI thread for COM and make pythonnet discoverable.

    ``CoInitializeEx`` can return ``RPC_E_CHANGED_MODE`` when Qt has already
    initialised this thread in a different valid apartment.  That is not an
    error: WebView2 may use Qt's existing apartment.  We only call
    ``CoUninitialize`` later when this function itself obtained an apartment.
    """
    global _COM_INITIALIZED, _COM_OWNED_BY_HALCYON
    if _COM_INITIALIZED:
        return True
    if sys.platform != "win32":
        return False

    try:
        _setup_vendor_path()
        try:
            ole32 = ctypes.windll.ole32
            # COINIT_APARTMENTTHREADED.  HRESULT is signed on some Python builds.
            result = int(ole32.CoInitializeEx(None, 0x2)) & 0xFFFFFFFF
            if result in (0x00000000, 0x00000001):  # S_OK / S_FALSE
                _COM_OWNED_BY_HALCYON = True
            elif result == 0x80010106:  # RPC_E_CHANGED_MODE
                logger.debug("Qt already owns this thread's COM apartment")
            else:
                logger.debug("CoInitializeEx returned HRESULT 0x%08X", result)
        except AttributeError:
            # Useful for a mocked Windows platform in the pure-Python tests;
            # real Windows always provides ctypes.windll.  pythonnet can still
            # prove the managed bridge independently in that test setup.
            logger.debug("Windows COM entry points are unavailable in this process")

        # Importing clr starts/attaches pythonnet's CLR host.  Do this before a
        # CoreWebView2Environment is requested, never from an event callback.
        import clr  # type: ignore[import-not-found]  # noqa: F401

        _COM_INITIALIZED = True
        return True
    except Exception as exc:
        logger.debug("pythonnet/COM initialisation failed: %s", exc)
        return False


def shutdown_pythonnet_com() -> None:
    """Release the environment and the COM apartment owned by Halcyon."""
    global _SHARED_ENVIRONMENT, _SHARED_ENVIRONMENT_TASK, _COM_INITIALIZED, _COM_OWNED_BY_HALCYON
    _SHARED_ENVIRONMENT = None
    _SHARED_ENVIRONMENT_TASK = None
    if sys.platform == "win32" and _COM_OWNED_BY_HALCYON:
        try:
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            logger.debug("CoUninitialize failed", exc_info=True)
    _COM_INITIALIZED = False
    _COM_OWNED_BY_HALCYON = False
    for handle in reversed(_DLL_DIRECTORY_HANDLES):
        try:
            handle.close()
        except Exception:
            pass
    _DLL_DIRECTORY_HANDLES.clear()
    _DLL_DIRECTORY_PATHS.clear()


def check_webview2_available() -> tuple[bool, str]:
    """Check the Windows runtime and the vendored managed bridge.

    The public message intentionally stays short and stable because it is shown
    directly in QML.  The detailed cause goes to debug logging, where it is
    useful without exposing a raw .NET traceback to a normal user.
    """
    if sys.platform != "win32":
        return False, "WebView2 is not available"

    if not _check_runtime_registry():
        logger.debug("Evergreen WebView2 Runtime registry key was not found")
        return False, "WebView2 is not available"

    try:
        if not init_pythonnet_com():
            return False, "WebView2 is not available"
        _add_core_reference()
        from Microsoft.Web.WebView2.Core import CoreWebView2Environment  # type: ignore[import-not-found]

        version = CoreWebView2Environment.GetAvailableBrowserVersionString(None)
        if not version:
            return False, "WebView2 is not available"
        return True, "OK"
    except Exception as exc:
        logger.debug("WebView2 import test failed: %s", exc, exc_info=True)
        return False, "WebView2 is not available"


def is_webview2_available() -> bool:
    return check_webview2_available()[0]


def get_stage_error_message() -> str:
    return "WebView2 is not available"


def _wait_for_task(task: Any, timeout_s: float = 25.0) -> Any:
    """Synchronously obtain a .NET Task result across pythonnet runtimes.

    WebView2 async creation methods require Windows message pumping on the STA
    GUI thread. Pumping Qt events while waiting prevents UI thread deadlocks.

    The default timeout is generous because ad-heavy sites (e.g. bilibili.tv)
    can queue several controller creations in a row; a too-aggressive timeout
    would turn a slow but healthy startup into a blank stage.
    """
    import time

    try:
        from PySide6.QtCore import QCoreApplication
    except ImportError:
        QCoreApplication = None

    if hasattr(task, "IsCompleted"):
        start_time = time.monotonic()
        try:
            while not bool(getattr(task, "IsCompleted", False)):
                app = QCoreApplication.instance() if QCoreApplication is not None else None
                if app is not None:
                    app.processEvents()
                else:
                    time.sleep(0.01)

                if time.monotonic() - start_time > timeout_s:
                    raise TimeoutError("WebView2 task did not complete within timeout")
        except TimeoutError:
            raise
        except Exception as exc:
            logger.debug("error checking task.IsCompleted: %s", exc)

    try:
        return task.GetAwaiter().GetResult()
    except AttributeError:
        # Kept for older pythonnet/.NET Framework combinations.
        return task.ConfigureAwait(False).GetAwaiter().GetResult()


def get_shared_environment() -> Any:
    """Create and return the one profile-sharing CoreWebView2Environment."""
    global _SHARED_ENVIRONMENT, _SHARED_ENVIRONMENT_TASK
    if _SHARED_ENVIRONMENT is not None:
        return _SHARED_ENVIRONMENT

    available, _ = check_webview2_available()
    if not available:
        return None

    try:
        if _SHARED_ENVIRONMENT_TASK is not None:
            return _wait_for_task(_SHARED_ENVIRONMENT_TASK)

        _add_core_reference()
        from Microsoft.Web.WebView2.Core import CoreWebView2Environment  # type: ignore[import-not-found]

        profile = get_user_data_dir()
        profile.mkdir(parents=True, exist_ok=True)
        task = CoreWebView2Environment.CreateAsync(None, str(profile), None)
        _SHARED_ENVIRONMENT_TASK = task
        try:
            _SHARED_ENVIRONMENT = _wait_for_task(task)
            return _SHARED_ENVIRONMENT
        finally:
            _SHARED_ENVIRONMENT_TASK = None
    except Exception as exc:
        logger.warning("failed to create the shared WebView2 environment: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Browser input helpers
# ---------------------------------------------------------------------------
def get_anti_bot_user_agent(default_ua: str = "") -> str:
    """Remove the WebView2 token while retaining a normal desktop Edge UA."""
    ua = default_ua or DEFAULT_EDGE_USER_AGENT
    tokens = ua.split()
    cleaned = " ".join(token for token in tokens if "webview2" not in token.lower()).strip()
    return cleaned or DEFAULT_EDGE_USER_AGENT


def get_anti_bot_init_script() -> str:
    return (
        "try { Object.defineProperty(navigator, 'webdriver', "
        "{ get: () => undefined, configurable: true }); } catch (e) {}"
    )


def resolve_url_or_search(query: str) -> str:
    """Turn address-bar text into a URL or the configured Google search URL."""
    text = (query or "").strip()
    if not text:
        return "https://www.google.com"

    lower = text.lower()
    for scheme in ("http://", "https://", "file://", "about:", "data:", "qrc:"):
        if lower.startswith(scheme):
            return text

    if lower == "localhost" or lower.startswith("localhost:"):
        return f"http://{text}"

    # A host, IPv4 address, or host/path is navigation.  Natural-language input
    # (including spaces) remains a Google search.
    if " " not in text and ("." in text or "/" in text):
        return f"https://{text}"

    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(text)
