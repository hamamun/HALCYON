"""Browser context and tab manager for Web mode (§P3.1, §P3.4).

Manages:
  • Tab model (maximum 15 tabs; "Maximum 15 tabs reached." in-chrome message).
  • No tabs on entry (+ only); typing in address bar creates first tab (§P3.1).
  • Active tab navigation, Back, Forward, Reload/Stop, Home (§P3.4).
  • Intercepted popup/new-window routing -> new Halcyon tab (§P3.4).
  • Bookmarks store integration (star states, dropdown, manager tab, §P3.5).
  • Tab persistence across mode switches (keep_stage_alive=True), never saved
    after restart (§P3.1).
"""

from __future__ import annotations

import logging
import urllib.parse
import uuid
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from modes.web import webview2_runtime
from modes.web.bookmarks import BookmarksStore
from modes.web.webview2_host import WebViewHost

logger = logging.getLogger("modes.web.browser")

MAX_TABS = 15


class BrowserContext(QObject):
    """The central Web mode controller exposed to QML as modeContext_web (§A.2)."""

    tabsChanged = Signal()
    activeTabIndexChanged = Signal()
    activeTabChanged = Signal()
    tabLimitMessageVisibleChanged = Signal()
    bookmarksChanged = Signal()

    def __init__(self, bookmarks: BookmarksStore | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tabs: list[dict[str, Any]] = []
        self._active_index: int = -1
        self._tab_limit_message_visible: bool = False
        self._bookmarks = bookmarks or BookmarksStore()
        self._bookmarks.bookmarksChanged.connect(self.bookmarksChanged.emit)

    @Property(int, notify=tabsChanged)
    def tabCount(self) -> int:
        return len(self._tabs)

    @Property(int, notify=activeTabIndexChanged)
    def activeTabIndex(self) -> int:
        return self._active_index

    @Property("QVariantMap", notify=activeTabChanged)
    def activeTab(self) -> dict[str, Any]:
        if 0 <= self._active_index < len(self._tabs):
            return dict(self._tabs[self._active_index])
        return {
            "id": "",
            "title": "",
            "url": "",
            "loading": False,
            "canGoBack": False,
            "canGoForward": False,
        }

    @Property("QVariantList", notify=tabsChanged)
    def tabs(self) -> list[dict[str, Any]]:
        return [dict(t) for t in self._tabs]

    @Property(bool, notify=tabsChanged)
    def isAtMaxTabs(self) -> bool:
        return len(self._tabs) >= MAX_TABS

    @Property(bool, notify=tabLimitMessageVisibleChanged)
    def tabLimitMessageVisible(self) -> bool:
        return self._tab_limit_message_visible

    @Property(QObject, notify=bookmarksChanged)
    def bookmarks(self) -> BookmarksStore:
        return self._bookmarks

    @Slot(str, result=bool)
    def addTab(self, url: str = "") -> bool:
        """Create a new tab (§P3.1, §P3.4).

        Enforces MAX_TABS (15). If reached, disables + and displays the in-chrome
        message 'Maximum 15 tabs reached.' in the tabs row without opening tab.
        """
        if len(self._tabs) >= MAX_TABS:
            self._set_tab_limit_message_visible(True)
            logger.info("MAX_TABS (15) reached — blocking addTab request.")
            return False

        clean_url = (url or "").strip()
        if clean_url:
            clean_url = webview2_runtime.resolve_url_or_search(clean_url)

        tab_id = uuid.uuid4().hex
        tab = {
            "id": tab_id,
            "title": clean_url or "New Tab",
            "url": clean_url,
            "loading": False,
            "canGoBack": False,
            "canGoForward": False,
        }
        self._tabs.append(tab)
        self._active_index = len(self._tabs) - 1
        self.tabsChanged.emit()
        self.activeTabIndexChanged.emit()
        self.activeTabChanged.emit()
        return True

    @Slot(int, result=bool)
    def closeTab(self, index: int) -> bool:
        """Close tab at index (§P3.4)."""
        if index < 0 or index >= len(self._tabs):
            return False

        self._tabs.pop(index)
        if len(self._tabs) < MAX_TABS and self._tab_limit_message_visible:
            self._set_tab_limit_message_visible(False)

        if len(self._tabs) == 0:
            self._active_index = -1
        elif self._active_index >= len(self._tabs):
            self._active_index = len(self._tabs) - 1
        elif index < self._active_index:
            self._active_index -= 1

        self.tabsChanged.emit()
        self.activeTabIndexChanged.emit()
        self.activeTabChanged.emit()
        return True

    @Slot(int)
    def setActiveTab(self, index: int) -> None:
        """Switch active tab."""
        if 0 <= index < len(self._tabs) and index != self._active_index:
            self._active_index = index
            self.activeTabIndexChanged.emit()
            self.activeTabChanged.emit()

    @Slot(str)
    def navigateActive(self, url_or_search: str) -> None:
        """Navigate active tab, or create first tab if none exist (§P3.1, §P3.4)."""
        resolved = webview2_runtime.resolve_url_or_search(url_or_search)
        if self._active_index < 0 or len(self._tabs) == 0:
            self.addTab(resolved)
            return

        tab = self._tabs[self._active_index]
        tab["url"] = resolved
        tab["title"] = resolved
        self.tabsChanged.emit()
        self.activeTabChanged.emit()

    @Slot()
    def navigateHome(self) -> None:
        """Navigate to loaded site homepage, or Google on a blank/no tab (§P3.4)."""
        if self._active_index < 0 or len(self._tabs) == 0:
            self.addTab("https://www.google.com")
            return

        url = self._tabs[self._active_index].get("url", "")
        if not url or url == "New Tab":
            self.navigateActive("https://www.google.com")
            return

        try:
            parts = urllib.parse.urlsplit(url)
            if parts.scheme and parts.netloc:
                home_url = f"{parts.scheme}://{parts.netloc}"
                self.navigateActive(home_url)
            else:
                self.navigateActive("https://www.google.com")
        except Exception:
            self.navigateActive("https://www.google.com")

    @Slot(str)
    def onPopupRequested(self, url: str) -> None:
        """Route site popup / new window request to a new Halcyon tab (§P3.4)."""
        logger.info("Routing popup/new-window to Halcyon tab: %s", url)
        self.addTab(url)

    @Slot()
    def dismissTabLimitMessage(self) -> None:
        """Hide the 15-tab limit in-chrome message pill."""
        self._set_tab_limit_message_visible(False)

    def _set_tab_limit_message_visible(self, visible: bool) -> None:
        if self._tab_limit_message_visible != visible:
            self._tab_limit_message_visible = visible
            self.tabLimitMessageVisibleChanged.emit()

    def reset_for_restart(self) -> None:
        """Clear tabs for fresh restart (tabs never saved across restart, §P3.1)."""
        self._tabs.clear()
        self._active_index = -1
        self._tab_limit_message_visible = False
        self.tabsChanged.emit()
        self.activeTabIndexChanged.emit()
        self.activeTabChanged.emit()
