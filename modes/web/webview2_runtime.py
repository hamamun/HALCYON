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

from core import paths as _paths  # noqa: E402  — must follow stdlib imports

ROOT = _paths.ROOT
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
    # Nuitka does not set sys.frozen; use the shared packaged-build check so
    # the bridge DLLs shipped under {app}\vendor\webview2 are actually found
    # on an installed build.
    if _paths.is_packaged_build():
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


# ---------------------------------------------------------------------------
# Clearing browsing data — the one simple path
# ---------------------------------------------------------------------------
# The dialog has NO time-range dropdown: every clear is "all time".
# WebView2's one-argument overload ClearBrowsingDataAsync(kinds) clears the
# given kinds regardless of timestamp — that IS "all time", per the official
# docs.  No time-range object, no FILETIME math.
#
# IMPORTANT (why the old code silently did nothing):
#   * The kind enum must be imported at CALL time, not module import time.
#     At startup the WebView2 bridge is not loaded yet, so an import-time
#     try/except left a module flag permanently False and the clear function
#     returned before doing anything.
#   * The profile must come from a LIVE CoreWebView2 (a running tab):
#     CoreWebView2Environment has no Profile; CoreWebView2.Profile is the
#     documented source.
#
# The id strings here are the SAME ids the dialog's eight CheckBoxRows use
# (see ClearBrowsingDataDialog.qml).  The QML owns the rows; this table owns
# the mapping id -> WebView2 flag bits.  Values below are Microsoft's official
# CoreWebView2BrowsingDataKinds constants (verified against the SDK docs).
def _kind_flags() -> dict[str, int]:
    """Map checkbox id -> WebView2 data-kind flag bits.

    Read at call time: the bridge is only importable after
    ``get_shared_environment`` has loaded it, which is guaranteed to have
    happened by the time the user can click Clear.  On a non-Windows dev box
    the fallback constants (which equal the official enum values) keep the
    pure-Python tests meaningful.
    """
    try:
        from Microsoft.Web.WebView2.Core import CoreWebView2BrowsingDataKinds as K

        return {
            "browsingHistory": int(K.BrowsingHistory),
            "downloadHistory": int(K.DownloadHistory),
            "cookies": int(K.Cookies) | int(K.AllDomStorage),
            "cache": int(K.DiskCache),
            "passwords": int(K.PasswordAutosave),
            "autofill": int(K.GeneralAutofill),
            # Site permissions are cleared by the Settings kind (the SDK has
            # no separate "site permissions" member).
            "sitePermissions": int(K.Settings),
            "serviceWorkers": int(K.ServiceWorkers),
        }
    except Exception:
        # Official CoreWebView2BrowsingDataKinds values — keep in lock-step
        # with the try branch above (test_kind_flags_match_official_enum
        # guards this table).
        return {
            "browsingHistory": 4096,    # BrowsingHistory
            "downloadHistory": 512,     # DownloadHistory
            "cookies": 64 | 32,         # Cookies | AllDomStorage
            "cache": 256,               # DiskCache
            "passwords": 2048,          # PasswordAutosave
            "autofill": 1024,           # GeneralAutofill
            "sitePermissions": 8192,    # Settings (covers site permissions)
            "serviceWorkers": 32768,    # ServiceWorkers
        }


def clear_browsing_data_all(profile: Any, options: list[str], *, wipe_folders: bool = True) -> bool:
    """Clear the ticked browsing-data kinds from a live profile, ALL TIME.

    ``profile`` is the CoreWebView2Profile of a running tab (the browser
    passes ``webview.Profile``).  ``options`` is the list of ticked checkbox
    ids from the dialog.  One SDK call, then — when the cache row is ticked —
    a physical wipe of the regenerable cache folders so the next size probe
    shows the real post-clear number.

    Never raises: a failed clear logs and returns False instead of crashing
    the browser.
    """
    options = list(options or [])
    if profile is None or not options:
        return False

    kinds = _kind_flags()
    combined = 0
    for opt_id in options:
        combined |= kinds.get(opt_id, 0)
    if combined == 0:
        return False

    ok = False
    try:
        # The one-argument form: clears these kinds for ALL TIME.
        arg = combined
        try:
            # Wrap the combined int in the real enum type so pythonnet never
            # has to guess; if the bridge is somehow absent, the int itself
            # still converts fine.
            from Microsoft.Web.WebView2.Core import CoreWebView2BrowsingDataKinds as K

            arg = K(combined)
        except Exception:
            pass
        task = profile.ClearBrowsingDataAsync(arg)
        _wait_for_task(task, timeout_s=60.0)
        logger.info("Cleared browsing data (kinds=0x%04X, all time)", combined)
        ok = True
    except Exception as exc:
        logger.warning("clear_browsing_data_all failed: %s", exc, exc_info=True)

    # The cache folder wipe runs even if the SDK call failed — it is our own
    # code and can reclaim space regardless.  It runs AFTER the SDK call so
    # any files the renderer still had open are released first.
    if "cache" in options and wipe_folders:
        _delete_cache_directories()

    return ok


# Directory names that hold WebView2's on-disk caches.  Walking the profile
# and summing these gives the number shown next to "Cached images and files".
# Keep in lock-step with ``_delete_cache_directories``: the MB shown MUST
# equal the bytes we can actually remove, or the user sees "nothing cleared".
_CACHE_DIR_NAMES = frozenset(
    {
        "cache_data",       # HTTP cache (Default/Cache/Cache_Data) — wiped by DiskCache
        "code cache",       # compiled JS bytecode
        "gpucache",
        "shadercache",
        "grshadercache",
        "dawncache",
        "cachestorage",     # Service Worker cache storage
        "scriptcache",      # Service Worker scripts
        "backforwardcache",
    }
)


def get_cache_size_bytes() -> int:
    """Return the on-disk size of the profile's caches, in bytes.

    WebView2 exposes no public "cache size" API, so the size is measured the
    way Chromium-based browsers' own UIs describe it: sum the files inside
    the profile's cache directories.  Safe everywhere — a missing profile or
    permission error simply yields 0, never an exception.
    """
    root_dir = get_user_data_dir()
    if not root_dir.is_dir():
        return 0

    total = 0
    try:
        cache_roots: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(root_dir, onerror=None):
            absolute = os.path.abspath(dirpath)
            if os.path.basename(dirpath).lower() in _CACHE_DIR_NAMES:
                cache_roots.append(absolute)
                in_cache_tree = True
            else:
                in_cache_tree = any(absolute.startswith(root + os.sep) for root in cache_roots)
            if not in_cache_tree:
                continue
            for name in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    continue
    except OSError:
        pass
    return total


def _delete_cache_directories() -> None:
    """Physically remove cache folders the WebView2 SDK won't delete on its own.

    ``ClearBrowsingDataAsync(Kinds.DiskCache)`` only invalidates and trims the
    HTTP cache; compiled JS bytecode, GPU/shader caches, Dawn cache, service
    worker scripts and back-forward cache can remain on disk until the
    renderer next runs its own eviction.  After an SDK clear we delete those
    directories ourselves — they are pure regenerable caches, WebView2 simply
    recreates them on next navigation.

    Failures are swallowed and logged; a locked file on Windows just means
    that slice stays until the next launch, which is acceptable.
    """
    import shutil

    root_dir = get_user_data_dir()
    if not root_dir.is_dir():
        return

    def _onerror(func: Any, path: str, exc_info: Any) -> None:  # noqa: ANN401 - shutil signature
        logger.debug("cache cleanup skipped %s: %s", path, exc_info[1] if exc_info else "")

    try:
        for dirpath, dirnames, _filenames in os.walk(root_dir, topdown=True, onerror=None):
            base = os.path.basename(dirpath).lower()
            if base in _CACHE_DIR_NAMES and base != "cache_data":
                try:
                    shutil.rmtree(dirpath, ignore_errors=False, onerror=_onerror)
                except Exception as exc:
                    logger.debug("cache cleanup rmtree %s failed: %s", dirpath, exc)
                # Prevent os.walk descending into a directory we just removed.
                dirnames[:] = []
                continue
            if base == "cache_data":
                # HTTP cache was logically cleared by the SDK.  Any files
                # remaining are still-open handles or orphan journal entries;
                # delete what we can without fighting the renderer.
                for entry in os.listdir(dirpath):
                    full = os.path.join(dirpath, entry)
                    try:
                        if os.path.isdir(full):
                            shutil.rmtree(full, ignore_errors=False, onerror=_onerror)
                        else:
                            os.remove(full)
                    except OSError as exc:
                        logger.debug("cache cleanup entry %s skipped: %s", full, exc)
                dirnames[:] = []
    except Exception as exc:
        logger.debug("cache directory cleanup failed: %s", exc)


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


def get_media_probe_script() -> str:
    """Injected into every page: report the main media element's state.

    Phase R (web chip, §R.2). Runs entirely inside the page and
    posts a JSON message to the host via ``chrome.webview.postMessage``.
    Upgraded vs original: includes shadowRoot + iframe traversal,
    picks playing element preferentially over largest, and hooks
    timeupdate/play/pause/volumechange for low-latency remote seekbar.
    Fully wrapped so any page without the WebView2 bridge still
    behaves normally.
    """
    return r"""
(() => {
  if (window.__halcyonMediaProbe) return;
  window.__halcyonMediaProbe = true;

  const collectMedia = (root, out) => {
    if (!root) return;
    try {
      const nodes = root.querySelectorAll ? root.querySelectorAll('video, audio') : [];
      for (const n of nodes) out.push(n);
    } catch(e) {}
    try {
      const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const el of all) {
        if (el.shadowRoot) collectMedia(el.shadowRoot, out);
        if (el.tagName === 'IFRAME') {
          try { if (el.contentDocument) collectMedia(el.contentDocument, out); } catch(e) {}
          try { if (el.contentWindow && el.contentWindow.document) collectMedia(el.contentWindow.document, out); } catch(e) {}
        }
      }
    } catch(e) {}
  };

  const pickMain = () => {
    try {
      const all = [];
      collectMedia(document, all);
      if (!all.length) return null;
      let best = all[0];
      for (const m of all) {
        const area = (m.videoWidth || 0) * (m.videoHeight || 0);
        const bestArea = (best.videoWidth || 0) * (best.videoHeight || 0);
        const isPlaying = !m.paused && !m.ended && m.readyState > 2;
        const bestIsPlaying = !best.paused && !best.ended && best.readyState > 2;
        if (isPlaying && !bestIsPlaying) { best = m; continue; }
        if (area > bestArea) best = m;
      }
      return best;
    } catch (e) { return null; }
  };

  const post = (data) => {
    try {
      if (window.chrome && window.chrome.webview && window.chrome.webview.postMessage) {
        window.chrome.webview.postMessage(JSON.stringify(data));
      }
    } catch (e) {}
  };

  let lastReport = 0;
  const report = () => {
    try {
      const m = pickMain();
      if (!m) { post({ halcyon: 'media', found: false }); return; }
      const dur = (typeof m.duration === 'number' && isFinite(m.duration)) ? m.duration : 0;
      // Throttle timeupdate bursts: at most ~5 per sec, but still post immediately on play/pause
      const now = Date.now();
      const payload = {
        halcyon: 'media', found: true, paused: !!m.paused,
        currentTime: m.currentTime || 0, duration: dur,
        volume: typeof m.volume === 'number' ? m.volume : 1,
        muted: !!m.muted,
        hasVideo: (m.tagName === 'VIDEO') || ((m.videoWidth||0) > 0)
      };
      lastReport = now;
      post(payload);
    } catch(e) {}
  };

  const hookMedia = (m) => {
    try {
      if (m.__halcyonHooked) return;
      m.__halcyonHooked = true;
      ['play','pause','volumechange','ratechange','emptied'].forEach(ev => {
        try { m.addEventListener(ev, () => setTimeout(report, 30), {passive:true}); } catch(e){}
      });
      try { m.addEventListener('timeupdate', () => { const n=Date.now(); if (n-lastReport>350) report(); }, {passive:true}); } catch(e){}
    } catch(e){}
  };

  const scanAndHook = () => {
    try {
      const all = []; collectMedia(document, all);
      for (const mm of all) hookMedia(mm);
    } catch(e){}
  };

  try {
    // Immediate + periodic + observers
    report();
    setInterval(() => { scanAndHook(); report(); }, 400);
    scanAndHook();
    // Watch for dynamically added video elements
    try {
      const obs = new MutationObserver(() => { scanAndHook(); });
      obs.observe(document.documentElement||document.body, {childList:true, subtree:true});
    } catch(e){}
    // Also report when tab becomes visible
    try { document.addEventListener('visibilitychange', () => { if (!document.hidden) report(); }); } catch(e){}
  } catch (e) {}
})();
"""


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
