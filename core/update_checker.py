"""Vendor dependency update checker — §U.

Checks whether the vendored VLC and WebView2 files are up to date.
Reads local file versions, compares against known latest, and provides
download URLs + file placement guidance to the QML Update tab.

The checker is lightweight: it reads DLL product-version stamps from
``vendor/vlc/`` and ``vendor/webview2/`` and reports what it finds.
A future enhancement can add HTTP checks against upstream release pages;
the QML side is already structured to display results from either source.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot

from core import paths

log = logging.getLogger(__name__)

# ── Known latest versions (update when new releases ship) ──────────────
VLC_KNOWN_LATEST = "3.0.21"
WEBVIEW2_KNOWN_LATEST = "1.0.2903"

# ── Official download sources ──────────────────────────────────────────
VLC_DOWNLOAD_URL = "https://download.videolan.org/pub/videolan/vlc/3.0.21/win64/"
WEBVIEW2_DOWNLOAD_URL = "https://www.nuget.org/packages/Microsoft.Web.WebView2"

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

    Exposed to QML as the ``UpdateChecker`` context property.  The Update tab
    in Settings calls ``checkUpdates()`` and reads results from signals and
    properties.
    """

    checkStarted = Signal()
    checkFinished = Signal("QVariant")  # dict with full results

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._checking = False
        self._vlcCurrentVersion = self._detect_vlc_version()
        self._webview2CurrentVersion = self._detect_webview2_version()
        self._lastResult: dict[str, Any] = {}
        # Sensible default so QML bindings never see null
        self._updateAvailable: dict[str, Any] = {
            "vlc": {
                "update": False,
                "current": self._vlcCurrentVersion,
                "latest": VLC_KNOWN_LATEST,
            },
            "webview2": {
                "update": False,
                "current": self._webview2CurrentVersion,
                "latest": WEBVIEW2_KNOWN_LATEST,
            },
        }

    # ──────────────────────────────────────────────────── version detect ──

    def _detect_vlc_version(self) -> str:
        """Read the product version from vendor/vlc/libvlc.dll."""
        dll = paths.VENDOR_VLC / "libvlc.dll"
        if not dll.exists():
            return "Not found"
        return self._read_file_version(dll) or "Unknown"

    def _detect_webview2_version(self) -> str:
        """Read the file version from vendor/webview2/ DLLs or .nupkg name."""
        core_dll = paths.ROOT / "vendor" / "webview2" / "Microsoft.Web.WebView2.Core.dll"
        if core_dll.exists():
            ver = self._read_file_version(core_dll)
            if ver:
                return ver
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
                                return candidate
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
        """Run the version check (synchronous — fast disk reads only)."""
        self._checking = True
        self.checkStarted.emit()

        # Re-read versions from disk
        self._vlcCurrentVersion = self._detect_vlc_version()
        self._webview2CurrentVersion = self._detect_webview2_version()

        # Compare
        vlc_update = self._is_update_available(
            self._vlcCurrentVersion, VLC_KNOWN_LATEST
        )
        wv2_update = self._is_update_available(
            self._webview2CurrentVersion, WEBVIEW2_KNOWN_LATEST
        )

        self._updateAvailable = {
            "vlc": {
                "update": vlc_update,
                "current": self._vlcCurrentVersion,
                "latest": VLC_KNOWN_LATEST,
            },
            "webview2": {
                "update": wv2_update,
                "current": self._webview2CurrentVersion,
                "latest": WEBVIEW2_KNOWN_LATEST,
            },
        }

        any_update = vlc_update or wv2_update
        self._lastResult = {
            "anyUpdate": any_update,
            "vlc": {
                "update": vlc_update,
                "current": self._vlcCurrentVersion,
                "latest": VLC_KNOWN_LATEST,
            },
            "webview2": {
                "update": wv2_update,
                "current": self._webview2CurrentVersion,
                "latest": WEBVIEW2_KNOWN_LATEST,
            },
        }

        self._checking = False
        self.checkFinished.emit(self._lastResult)

    @staticmethod
    def _is_update_available(current: str, known_latest: str) -> bool:
        """True when *current* looks like an older version than *known_latest*.

        ``"Not found"`` or ``"Unknown"`` are treated as needing an update
        because the files are missing or unreadable — the user should place
        fresh copies.
        """
        if current in ("Not found", "Unknown", ""):
            return True
        try:
            cur_parts = [int(x) for x in current.split(".")[:4]]
            lat_parts = [int(x) for x in known_latest.split(".")[:4]]
            return cur_parts < lat_parts
        except (ValueError, IndexError):
            # Non-numeric version string — cannot compare, assume up to date
            return False

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
