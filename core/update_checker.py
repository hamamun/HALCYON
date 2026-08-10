"""Vendor dependency update checker — §U.

Checks whether the vendored VLC and WebView2 files are up to date.
Reads local file versions, queries live online sources in a background thread,
compares local against latest online versions, and provides download URLs +
file placement guidance to the QML Update tab.
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot

from core import paths

log = logging.getLogger(__name__)

# ── Known latest versions (fallback when offline) ──────────────────────
VLC_KNOWN_LATEST = "3.0.23"
WEBVIEW2_KNOWN_LATEST = "1.0.4129.50"

# ── Official download sources ──────────────────────────────────────────
# Stable URLs only: these never embed a version number, so they always
# point at the newest release and cannot go stale like a hardcoded
# versioned folder would (e.g. ".../vlc/3.0.21/win64/").
VLC_DOWNLOAD_URL = "https://download.videolan.org/pub/videolan/vlc/last/win64/"  # "last/" alias = newest VLC release
WEBVIEW2_DOWNLOAD_URL = "https://www.nuget.org/packages/Microsoft.Web.WebView2"  # package page always shows newest version

# ── File placement guidance (shown to the user after extraction) ───────
VLC_EXTRACTION_GUIDE = (
    "After extraction, these files are at the root of the extracted folder:"
)
VLC_FILES = [
    ("libvlc.dll",        "root of extracted folder"),
    ("libvlccore.dll",    "root of extracted folder"),
    ("plugins/ (folder)", "root of extracted folder"),
]
VLC_PLACE_PATHS = [
    ("vendor\\vlc",            "libvlc.dll, libvlccore.dll"),
    ("vendor\\vlc\\plugins",   "contents of the plugins/ folder"),
]

WEBVIEW2_EXTRACTION_GUIDE = (
    "Rename .nupkg to .zip, extract, then navigate to build\\native\\x64\\:"
)
WEBVIEW2_FILES = [
    ("Microsoft.Web.WebView2.Core.dll", "build\\native\\x64\\"),
    ("WebView2Loader.dll",              "build\\native\\x64\\"),
]
WEBVIEW2_PLACE_PATHS = [
    ("vendor\\webview2", "both DLLs"),
]


class UpdateChecker(QObject):
    """Checks vendor dependency versions and guides the user through updates.

    Exposed to QML as the ``UpdateChecker`` context property. The Update tab
    in Settings calls ``checkUpdates()`` / ``cancelCheck()`` and reads results
    from signals and properties.
    """

    checkStarted = Signal()
    checkFinished = Signal("QVariant")  # dict with full results
    checkCancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._checking = False
        self._cancelled = False
        self._worker_thread: threading.Thread | None = None

        self._vlcCurrentVersion = self._normalize_version(
            self._detect_vlc_version()
        )
        self._webview2CurrentVersion = self._normalize_version(
            self._detect_webview2_version()
        )
        self._lastResult: dict[str, Any] = {}
        # Sensible default so QML bindings never see null
        self._updateAvailable: dict[str, Any] = {
            "anyUpdate": False,
            "checkedOnline": False,
            "vlc": {
                "update": False,
                "current": self._vlcCurrentVersion,
                "latest": self._normalize_version(VLC_KNOWN_LATEST),
                "online": False,
            },
            "webview2": {
                "update": False,
                "current": self._webview2CurrentVersion,
                "latest": self._normalize_version(WEBVIEW2_KNOWN_LATEST),
                "online": False,
            },
        }

    # ──────────────────────────────────────────────────── version detect ──

    def _detect_vlc_version(self) -> str:
        """Read the product version from vendor/vlc/libvlc.dll."""
        dll = paths.VENDOR_VLC / "libvlc.dll"
        if not dll.exists():
            return "Not found"
        return self._normalize_version(self._read_file_version(dll) or "Unknown")

    def _detect_webview2_version(self) -> str:
        """Read the file version from vendor/webview2/ DLLs or .nupkg name."""
        core_dll = paths.ROOT / "vendor" / "webview2" / "Microsoft.Web.WebView2.Core.dll"
        if core_dll.exists():
            ver = self._read_file_version(core_dll)
            if ver:
                return self._normalize_version(ver)
        # Fallback: parse the version from the NuGet package filename
        wv2_dir = paths.ROOT / "vendor" / "webview2"
        if wv2_dir.exists():
            for f in wv2_dir.iterdir():
                if f.suffix.lower() == ".nupkg" and "webview2" in f.stem.lower():
                    # e.g. microsoft.web.webview2.1.0.2903.nupkg
                    parts = f.stem.split(".")
                    for i, part in enumerate(parts):
                        if part.isdigit() and i + 2 < len(parts):
                            candidate = ".".join(parts[i : i + 3])
                            if candidate[0].isdigit():
                                return self._normalize_version(candidate)
        return "Not found"

    @staticmethod
    def _read_file_version(file_path: Path) -> str | None:
        """Read the product/file version from a Windows DLL via PowerShell."""
        if sys.platform != "win32":
            return None
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"(Get-Item '{file_path}').VersionInfo.ProductVersion",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ver = result.stdout.strip()
            if ver and ver != "0.0.0.0":
                return ver
        except Exception:
            pass
        # Fallback: try file version
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"(Get-Item '{file_path}').VersionInfo.FileVersion",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ver = result.stdout.strip()
            if ver and ver != "0.0.0.0":
                return ver
        except Exception:
            pass
        return None

    # ──────────────────────────────────────────────────── online fetching ──

    def _fetch_url(self, url: str, timeout: float = 5.0) -> bytes | None:
        """Fetch content from *url* with timeout and cancellation check."""
        if self._cancelled:
            return None
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Halcyon-UpdateChecker/1.0 (Windows NT 10.0; Win64; x64)"},
        )
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception as exc:
            log.debug("HTTP fetch failed for %s: %s", url, exc)
        return None

    def _fetch_online_vlc_version(self) -> tuple[str, bool]:
        """Fetch the latest VLC version from live online sources.

        Returns tuple: (version_string, online_success_bool)
        """
        urls = [
            "https://download.videolan.org/pub/videolan/vlc/",
            "https://update.videolan.org/vlc/status.xml",
        ]
        for url in urls:
            if self._cancelled:
                break
            data = self._fetch_url(url, timeout=5.0)
            if not data:
                continue
            try:
                content = data.decode("utf-8", errors="ignore")
                # XML check: <version>3.0.21</version>
                xml_match = re.search(
                    r"<version>\s*(\d+\.\d+\.\d+(?:\.\d+)?)\s*</version>",
                    content,
                    re.IGNORECASE,
                )
                if xml_match:
                    ver = xml_match.group(1).strip()
                    log.info("Found online VLC version from XML status: %s", ver)
                    return ver, True

                # Directory listing check: href="3.0.21/"
                matches = re.findall(
                    r'href=["\']?(\d+\.\d+\.\d+(?:\.\d+)?)/?["\']?', content
                )
                if matches:
                    valid_versions = []
                    for m in matches:
                        t = self._parse_version_tuple(m)
                        if t and t[0] >= 3:  # VLC 3.x or 4.x
                            valid_versions.append((t, m))
                    if valid_versions:
                        valid_versions.sort(key=lambda x: x[0])
                        latest_str = valid_versions[-1][1]
                        log.info("Found online VLC version from directory listing: %s", latest_str)
                        return latest_str, True
            except Exception as exc:
                log.warning("Error parsing VLC online version from %s: %s", url, exc)

        return VLC_KNOWN_LATEST, False

    def _fetch_online_webview2_version(self) -> tuple[str, bool]:
        """Fetch the latest Microsoft.Web.WebView2 version from NuGet API.

        Returns tuple: (version_string, online_success_bool)
        """
        urls = [
            "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/index.json",
            "https://www.nuget.org/packages/Microsoft.Web.WebView2",
        ]
        for url in urls:
            if self._cancelled:
                break
            data = self._fetch_url(url, timeout=5.0)
            if not data:
                continue
            try:
                content = data.decode("utf-8", errors="ignore")
                if url.endswith(".json"):
                    doc = json.loads(content)
                    versions = doc.get("versions", [])
                    valid_versions = []
                    for v in versions:
                        if "-" not in v:  # filter out pre-releases
                            t = self._parse_version_tuple(v)
                            if t and t[0] >= 1:
                                valid_versions.append((t, v))
                    if valid_versions:
                        valid_versions.sort(key=lambda x: x[0])
                        latest_str = valid_versions[-1][1]
                        log.info("Found online WebView2 version from NuGet API: %s", latest_str)
                        return latest_str, True
                else:
                    matches = re.findall(
                        r"Microsoft\.Web\.WebView2\s+(\d+\.\d+\.\d+(?:\.\d+)?)",
                        content,
                    )
                    if matches:
                        valid_versions = []
                        for m in matches:
                            t = self._parse_version_tuple(m)
                            if t:
                                valid_versions.append((t, m))
                        if valid_versions:
                            valid_versions.sort(key=lambda x: x[0])
                            latest_str = valid_versions[-1][1]
                            log.info("Found online WebView2 version from NuGet page: %s", latest_str)
                            return latest_str, True
            except Exception as exc:
                log.warning("Error parsing WebView2 online version from %s: %s", url, exc)

        return WEBVIEW2_KNOWN_LATEST, False

    # ──────────────────────────────────────────────────── Qt properties ──

    @Property(bool, notify=checkFinished)
    def checking(self) -> bool:
        return self._checking

    @Property(str, notify=checkFinished)
    def vlcCurrentVersion(self) -> str:  # noqa: N802
        return self._vlcCurrentVersion

    @Property(str, notify=checkFinished)
    def webview2CurrentVersion(self) -> str:  # noqa: N802
        return self._webview2CurrentVersion

    @Property("QVariant", notify=checkFinished)
    def updateAvailable(self) -> dict:  # noqa: N802
        return self._updateAvailable

    @Property("QVariant", notify=checkFinished)
    def lastResult(self) -> dict:  # noqa: N802
        return self._lastResult

    # ──────────────────────────────────────────────────── check logic ──

    @Slot()
    def checkUpdates(self) -> None:  # noqa: N802
        """Start an asynchronous online update check in a background thread."""
        if self._checking:
            return

        self._checking = True
        self._cancelled = False
        self.checkStarted.emit()

        self._worker_thread = threading.Thread(
            target=self._run_check_thread, daemon=True
        )
        self._worker_thread.start()

    @Slot()
    def cancelCheck(self) -> None:  # noqa: N802
        """Cancel an in-progress update check."""
        if self._checking:
            self._cancelled = True
            self._checking = False
            self.checkCancelled.emit()

    def _run_check_thread(self) -> None:
        """Worker thread function performing disk checks + online HTTP checks."""
        # Step 1: Local disk detection
        vlc_current = self._normalize_version(self._detect_vlc_version())
        wv2_current = self._normalize_version(self._detect_webview2_version())

        if self._cancelled:
            self._checking = False
            return

        # Step 2: Online HTTP fetching
        vlc_latest, vlc_online = self._fetch_online_vlc_version()
        vlc_latest = self._normalize_version(vlc_latest)
        if self._cancelled:
            self._checking = False
            return

        wv2_latest, wv2_online = self._fetch_online_webview2_version()
        wv2_latest = self._normalize_version(wv2_latest)
        if self._cancelled:
            self._checking = False
            return

        # Step 3: Compare versions
        vlc_update = self._is_update_available(vlc_current, vlc_latest)
        wv2_update = self._is_update_available(wv2_current, wv2_latest)

        any_update = vlc_update or wv2_update
        checked_online = vlc_online or wv2_online

        result = {
            "anyUpdate": any_update,
            "checkedOnline": checked_online,
            "vlc": {
                "update": vlc_update,
                "current": vlc_current,
                "latest": vlc_latest,
                "online": vlc_online,
            },
            "webview2": {
                "update": wv2_update,
                "current": wv2_current,
                "latest": wv2_latest,
                "online": wv2_online,
            },
        }

        self._vlcCurrentVersion = vlc_current
        self._webview2CurrentVersion = wv2_current
        self._updateAvailable = result
        self._lastResult = result
        self._checking = False

        if not self._cancelled:
            self.checkFinished.emit(result)

    @classmethod
    def _is_update_available(cls, current: str, latest: str) -> bool:
        """True when *current* looks like an older version than *latest*.

        ``"Not found"`` or ``"Unknown"`` are treated as needing an update
        because the files are missing or unreadable.
        """
        if current in ("Not found", "Unknown", ""):
            return True
        cur_parts = cls._parse_version_tuple(current)
        lat_parts = cls._parse_version_tuple(latest)
        return cur_parts < lat_parts

    @staticmethod
    def _normalize_version(ver_str: str) -> str:
        """Normalize a version for display and comparison.

        Windows file metadata can expose a version with comma separators (for
        example, ``"3,0,23,0"``). The updater uses dotted versions from its
        online sources, so make both forms consistent. A final zero component
        is insignificant in a file-version value, so trailing zero-only
        components are omitted while non-zero components remain intact.

        Non-version status strings such as ``"Not found"`` pass through
        unchanged.
        """
        clean = ver_str.strip()
        match = re.fullmatch(r"(\d+(?:[.,]\d+)*)(.*)", clean)
        if not match:
            return clean

        numeric, suffix = match.groups()
        parts = numeric.replace(",", ".").split(".")
        while len(parts) > 1 and int(parts[-1]) == 0:
            parts.pop()
        return ".".join(parts) + suffix

    @classmethod
    def _parse_version_tuple(cls, ver_str: str) -> tuple[int, ...]:
        """Parse dotted or comma-separated version text into comparable ints."""
        clean = cls._normalize_version(ver_str).split("-", 1)[0]
        parts = []
        for part in clean.split("."):
            try:
                parts.append(int(part))
            except ValueError:
                break
        return tuple(parts) if parts else (0,)

    # ──────────────────────────────────────────────────── static data for QML ──

    @Property(str, constant=True)
    def vlcDownloadUrl(self) -> str:  # noqa: N802
        return VLC_DOWNLOAD_URL

    @Property(str, constant=True)
    def webview2DownloadUrl(self) -> str:  # noqa: N802
        return WEBVIEW2_DOWNLOAD_URL

    @Property("QVariantList", constant=True)
    def vlcFiles(self) -> list:  # noqa: N802
        """Files to extract from VLC archive + where they sit after extraction."""
        return [{"name": name, "location": loc} for name, loc in VLC_FILES]

    @Property("QVariantList", constant=True)
    def vlcPlacePaths(self) -> list:  # noqa: N802
        """Destination folders in the app install + what goes in each."""
        return [{"path": p, "files": f} for p, f in VLC_PLACE_PATHS]

    @Property("QVariantList", constant=True)
    def webview2Files(self) -> list:  # noqa: N802
        return [{"name": name, "location": loc} for name, loc in WEBVIEW2_FILES]

    @Property("QVariantList", constant=True)
    def webview2PlacePaths(self) -> list:  # noqa: N802
        return [{"path": p, "files": f} for p, f in WEBVIEW2_PLACE_PATHS]

    @Property(str, constant=True)
    def vlcExtractionGuide(self) -> str:  # noqa: N802
        return VLC_EXTRACTION_GUIDE

    @Property(str, constant=True)
    def webview2ExtractionGuide(self) -> str:  # noqa: N802
        return WEBVIEW2_EXTRACTION_GUIDE

    # ──────────────────────────────────────────────────── user actions ──

    @Slot(str)
    def openFolder(self, relative_path: str) -> None:  # noqa: N802
        """Open *relative_path* (relative to repo root) in Windows Explorer."""
        folder = paths.ROOT / relative_path
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            try:
                os.startfile(str(folder.resolve()))
            except OSError as exc:
                log.warning("could not open folder %s: %s", folder, exc)
        else:
            # macOS / Linux fallback
            try:
                subprocess.Popen(["xdg-open", str(folder.resolve())])
            except OSError:
                pass

    @Slot()
    def openVlcDownload(self) -> None:  # noqa: N802
        webbrowser.open(VLC_DOWNLOAD_URL)

    @Slot()
    def openWebview2Download(self) -> None:  # noqa: N802
        webbrowser.open(WEBVIEW2_DOWNLOAD_URL)

    @Property(str, constant=True)
    def appRootPath(self) -> str:  # noqa: N802
        """Absolute path of the application root (for display in the UI)."""
        return str(paths.ROOT)
