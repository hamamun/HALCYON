"""Web mode context and WebView2 host boundary (§P3).

This file deliberately keeps the native browser boundary behind a tiny QObject.
The tab/bookmark UI can be developed and tested on every platform, while the
Windows runtime check and future WebView2 controller attachment live here.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

from core import paths
from modes.web.bookmarks import BookmarkModel, clean_title, normalise_url
from modes.web.tabs import MANAGER_URL, MAX_TABS, TabModel, display_url

log = logging.getLogger(__name__)


class WebContext(QObject):
    """The one Web-mode object exposed to QML as ``WebPlaylist``.

    The name comes from the existing generic context-property convention
    (``<mode>.capitalize() + 'Playlist'``).  It is a browser context, not a media
    playlist.
    """

    activeChanged = Signal()
    toastRequested = Signal(str)
    runtimeChanged = Signal()

    def __init__(self, settings=None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._tabs = TabModel(self)
        self._bookmarks = BookmarkModel(parent=self)
        self._runtime_status = _runtime_status()
        self._tabs.activeChanged.connect(self.activeChanged)
        self._tabs.limitReached.connect(
            lambda: self.toastRequested.emit(f"Maximum {MAX_TABS} tabs reached.")
        )
        self._bookmarks.changed.connect(self.activeChanged)

    @Property(QObject, constant=True)
    def tabs(self) -> QObject:
        return self._tabs

    @Property(QObject, constant=True)
    def bookmarks(self) -> QObject:
        return self._bookmarks

    @Property(str, notify=activeChanged)
    def activeUrl(self) -> str:  # noqa: N802
        return self._tabs.activeUrl

    @Property(str, notify=activeChanged)
    def activeDisplayUrl(self) -> str:  # noqa: N802
        return display_url(self._tabs.activeUrl)

    @Property(str, notify=activeChanged)
    def activeTitle(self) -> str:  # noqa: N802
        return self._tabs.activeTitle

    @Property(bool, notify=activeChanged)
    def hasActiveTab(self) -> bool:  # noqa: N802
        return self._tabs.hasActiveTab

    @Property(bool, notify=activeChanged)
    def activeIsManager(self) -> bool:  # noqa: N802
        return self._tabs.activeIsManager

    @Property(bool, notify=activeChanged)
    def activeBookmarked(self) -> bool:  # noqa: N802
        return self.current_bookmark_index() >= 0

    @Property(int, notify=activeChanged)
    def currentBookmarkIndex(self) -> int:  # noqa: N802
        return self.current_bookmark_index()

    @Property(bool, notify=activeChanged)
    def canGoBack(self) -> bool:  # noqa: N802
        return self._tabs.canGoBack

    @Property(bool, notify=activeChanged)
    def canGoForward(self) -> bool:  # noqa: N802
        return self._tabs.canGoForward

    @Property(bool, notify=runtimeChanged)
    def webView2Available(self) -> bool:  # noqa: N802
        return self._runtime_status.available

    @Property(str, notify=runtimeChanged)
    def webView2Status(self) -> str:  # noqa: N802
        return self._runtime_status.message

    # ---------------------------------------------------------------- tabs --
    @Slot()
    def newTab(self) -> None:  # noqa: N802
        self._tabs.newBlankTab()

    @Slot(str)
    def openNewTab(self, url: str) -> None:  # noqa: N802
        self._tabs.openUrl(url)

    @Slot()
    def openBookmarkManager(self) -> None:  # noqa: N802
        self._tabs.openManager()

    @Slot(int)
    def activateTab(self, index: int) -> None:  # noqa: N802
        self._tabs.activate(index)

    @Slot(int)
    def closeTab(self, index: int) -> None:  # noqa: N802
        self._tabs.close(index)

    @Slot(str)
    def navigate(self, text: str) -> None:
        self._tabs.navigateActive(text)

    @Slot()
    def goBack(self) -> None:  # noqa: N802
        self._tabs.back()

    @Slot()
    def goForward(self) -> None:  # noqa: N802
        self._tabs.forward()

    @Slot()
    def reload(self) -> None:
        self._tabs.reload()

    @Slot()
    def stop(self) -> None:
        self._tabs.stop()

    @Slot()
    def home(self) -> None:
        self._tabs.home()

    @Slot(int)
    def openBookmark(self, source_index: int) -> None:  # noqa: N802
        item = self._bookmarks.get(source_index)
        url = item.get("url", "") if isinstance(item, dict) else ""
        if url:
            self._tabs.navigateActive(url)

    # ------------------------------------------------------------- bookmarks --
    @Slot(str, str, result=bool)
    def saveBookmark(self, title: str, url: str) -> bool:  # noqa: N802
        ok = self._bookmarks.addBookmark(title, url)
        if ok:
            self.toastRequested.emit("Bookmark saved.")
            self.activeChanged.emit()
        return ok

    @Slot(str, result=bool)
    def saveCurrentBookmark(self, title: str = "") -> bool:  # noqa: N802
        url = self._tabs.activeUrl
        if not url or url in ("about:blank", MANAGER_URL):
            return False
        return self.saveBookmark(title or self._tabs.activeTitle, url)

    @Slot(str, str, result=bool)
    def updateCurrentBookmark(self, title: str, url: str) -> bool:  # noqa: N802
        idx = self.current_bookmark_index()
        if idx < 0:
            return self.saveBookmark(title, url)
        ok = self._bookmarks.updateBookmark(idx, clean_title(title, url), normalise_url(url))
        if ok:
            self.toastRequested.emit("Bookmark updated.")
            self.activeChanged.emit()
        return ok

    @Slot(result=bool)
    def removeCurrentBookmark(self) -> bool:  # noqa: N802
        idx = self.current_bookmark_index()
        if idx < 0:
            return False
        ok = self._bookmarks.deleteBookmark(idx)
        if ok:
            self.toastRequested.emit("Bookmark removed.")
            self.activeChanged.emit()
        return ok

    @Slot(int, str, str, result=bool)
    def updateBookmark(self, source_index: int, title: str, url: str) -> bool:  # noqa: N802
        ok = self._bookmarks.updateBookmark(source_index, title, url)
        if ok:
            self.toastRequested.emit("Bookmark updated.")
            self.activeChanged.emit()
        return ok

    @Slot(int, result=bool)
    def deleteBookmark(self, source_index: int) -> bool:  # noqa: N802
        ok = self._bookmarks.deleteBookmark(source_index)
        if ok:
            self.toastRequested.emit("Bookmark deleted.")
            self.activeChanged.emit()
        return ok

    @Slot(int, int, result=bool)
    def moveBookmark(self, source_index: int, target_index: int) -> bool:  # noqa: N802
        return self._bookmarks.moveBookmark(source_index, target_index)

    @Slot(int, result="QVariant")
    def bookmark(self, source_index: int):
        return self._bookmarks.get(source_index)

    def current_bookmark_index(self) -> int:
        url = self._tabs.activeUrl
        if not url or url in ("about:blank", MANAGER_URL):
            return -1
        return self._bookmarks.index_of_url(url)

    def shutdown(self) -> None:
        # Bookmarks save immediately; tabs are intentionally session-only.
        pass


class RuntimeStatus:
    def __init__(self, available: bool, message: str) -> None:
        self.available = available
        self.message = message


def _runtime_status() -> RuntimeStatus:
    if sys.platform != "win32":
        return RuntimeStatus(False, "WebView2 browsing is available on Windows builds.")
    version = _webview2_version()
    if version:
        return RuntimeStatus(True, f"Microsoft Edge WebView2 Runtime {version} detected.")
    return RuntimeStatus(False, "Microsoft Edge WebView2 Runtime is not installed.")


def _webview2_version() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except Exception:
        return ""

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
                    return str(value)
        except OSError:
            continue
    return ""


def build_web_context(engine=None, controller=None, settings=None):
    """ModeSpec setup hook."""
    profile = paths.data_dir() / "web"
    profile.mkdir(parents=True, exist_ok=True)
    return WebContext(settings=settings)
