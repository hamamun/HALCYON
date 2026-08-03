"""Web mode context and WebView2 host boundary (§P3).

This file deliberately keeps the native browser boundary behind a tiny QObject.
The tab/bookmark UI can be developed and tested on every platform, while the
Windows runtime check and future WebView2 controller attachment live here.

WebView2 Integration:
- Uses Windows' built-in WebView2 Runtime (no separate installation needed)
- Creates WebView2 control attached to Qt widget HWND
- Connects to existing TabModel for navigation control
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Property, Signal, Slot

from core import paths
from modes.web.bookmarks import BookmarkModel, clean_title, normalise_url
from modes.web.tabs import MANAGER_URL, MAX_TABS, TabModel, display_url
from modes.web import webview_integration
from modes.web.webview_integration import check_webview2_available

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)


class WebContext(QObject):
    """The one Web-mode object exposed to QML as ``WebPlaylist``.

    The name comes from the existing generic context-property convention
    (``<mode>.capitalize() + 'Playlist'``).  It is a browser context, not a media
    playlist.
    
    Integrates with WebView2 for actual web browsing on Windows.
    """

    activeChanged = Signal()
    toastRequested = Signal(str)
    runtimeChanged = Signal()
    
    # Signal emitted when WebView2 container widget is ready
    webviewContainerReady = Signal("QWidget")

    def __init__(self, settings=None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._tabs = TabModel(self)
        self._bookmarks = BookmarkModel(parent=self)
        self._runtime_status = _runtime_status()
        self._webviews: dict[int, "webview_integration.WebViewBase | None"] = {}
        self._container_widget = None
        self._webview_initialized = False
        
        # Connect TabModel signals
        self._tabs.activeChanged.connect(self._on_tab_active_changed)
        self._tabs.limitReached.connect(
            lambda: self.toastRequested.emit(f"Maximum {MAX_TABS} tabs reached.")
        )
        self._tabs.changed.connect(self._on_tabs_changed)
        self._bookmarks.changed.connect(self.activeChanged)
        
        # Initialize WebView2
        self._init_webview2()

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

    # ------------------------------------------------------------ WebView2 ---
    
    def _init_webview2(self) -> None:
        """Initialize WebView2 and create container widget."""
        if not self._runtime_status.available:
            log.info("WebView2 not available - browsing will be disabled")
            return
        
        # Create container widget for WebView2
        self._create_container_widget()
    
    def _create_container_widget(self) -> None:
        """Create Qt widget to host WebView2."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtCore import QSize
            
            # Create a hidden container widget
            container = QWidget()
            container.setFixedSize(QSize(1, 1))  # Minimal size until shown
            container.setVisible(False)
            container.setParent(None)
            
            self._container_widget = container
            log.info("WebView2 container widget created")
            
            # Emit signal so QML can position it
            self.webviewContainerReady.emit(container)
            
        except Exception as e:
            log.error("Failed to create WebView2 container: %s", e)
    
    def _on_tabs_changed(self) -> None:
        """Handle tab changes - create/destroy WebViews as needed."""
        self._sync_webviews_with_tabs()
    
    def _on_tab_active_changed(self) -> None:
        """Handle active tab change - show correct WebView."""
        self._sync_webviews_with_tabs()
        self.activeChanged.emit()
    
    def _sync_webviews_with_tabs(self) -> None:
        """Sync WebView instances with tab model."""
        # Ensure we have a WebView for each tab
        for i in range(self._tabs.count):
            if i not in self._webviews:
                self._create_webview_for_tab(i)
        
        # Clean up WebViews for closed tabs
        removed = [i for i in self._webviews if i >= self._tabs.count]
        for i in removed:
            webview = self._webviews.pop(i, None)
            if webview:
                webview.close()
    
    def _create_webview_for_tab(self, index: int) -> None:
        """Create WebView instance for a tab."""
        if not self._container_widget or not self._runtime_status.available:
            self._webviews[index] = None
            return
        
        tab = self._tabs._tabs[index] if index < len(self._tabs._tabs) else None
        if not tab:
            self._webviews[index] = None
            return
        
        try:
            webview = webview_integration.create_webview(
                widget=self._container_widget,
                initial_url=tab.url,
                on_title_changed=lambda title, i=index: self._on_webview_title_changed(i, title),
                on_url_changed=lambda url, i=index: self._on_webview_url_changed(i, url),
                on_loading_changed=lambda loading, i=index: self._on_webview_loading_changed(i, loading),
                on_navigation_completed=lambda success, i=index: self._on_webview_navigation_completed(i, success),
            )
            self._webviews[index] = webview
            log.debug("Created WebView for tab %d", index)
        except Exception as e:
            log.error("Failed to create WebView for tab %d: %s", index, e)
            self._webviews[index] = None
    
    def _on_webview_title_changed(self, index: int, title: str) -> None:
        """Handle WebView title change."""
        if index == self._tabs.activeIndex:
            self.activeChanged.emit()
    
    def _on_webview_url_changed(self, index: int, url: str) -> None:
        """Handle WebView URL change - sync with TabModel."""
        if index == self._tabs.activeIndex:
            # Update TabModel with actual URL from WebView2
            # This handles redirects and URL normalization
            self.activeChanged.emit()
    
    def _on_webview_loading_changed(self, index: int, is_loading: bool) -> None:
        """Handle WebView loading state change."""
        log.debug("Tab %d loading: %s", index, is_loading)
    
    def _on_webview_navigation_completed(self, index: int, success: bool) -> None:
        """Handle WebView navigation completed."""
        log.debug("Tab %d navigation completed: %s", index, success)
    
    def _get_active_webview(self):
        """Get WebView for currently active tab."""
        if self._tabs.activeIndex < 0:
            return None
        return self._webviews.get(self._tabs.activeIndex)
    
    # Override navigation methods to use WebView2
    @Slot(str)
    def navigate(self, text: str) -> None:
        """Navigate to URL - uses WebView2 on Windows."""
        if not self._runtime_status.available:
            self.toastRequested.emit("Web browsing is not available on this platform.")
            return
        
        url = normalise_url(text)
        if not url:
            return
        
        # Update TabModel first
        self._tabs.navigateActive(text)
        
        # Then navigate WebView
        webview = self._get_active_webview()
        if webview:
            webview.navigate(url)
    
    @Slot()
    def goBack(self) -> None:  # noqa: N802
        """Go back - uses WebView2 on Windows."""
        if not self._runtime_status.available:
            return
        
        self._tabs.back()
        
        webview = self._get_active_webview()
        if webview:
            webview.go_back()
    
    @Slot()
    def goForward(self) -> None:  # noqa: N802
        """Go forward - uses WebView2 on Windows."""
        if not self._runtime_status.available:
            return
        
        self._tabs.forward()
        
        webview = self._get_active_webview()
        if webview:
            webview.go_forward()
    
    @Slot()
    def reload(self) -> None:
        """Reload - uses WebView2 on Windows."""
        if not self._runtime_status.available:
            return
        
        webview = self._get_active_webview()
        if webview:
            webview.reload()
    
    @Slot()
    def stop(self) -> None:
        """Stop loading - uses WebView2 on Windows."""
        if not self._runtime_status.available:
            return
        
        webview = self._get_active_webview()
        if webview:
            webview.stop()
    
    @Slot()
    def home(self) -> None:
        """Go home - navigates to default home page."""
        self._tabs.home()
        
        if self._runtime_status.available:
            webview = self._get_active_webview()
            if webview:
                webview.navigate("https://www.bing.com")
    
    def shutdown(self) -> None:
        """Clean up WebView2 instances."""
        # Close all WebViews
        for webview in self._webviews.values():
            if webview:
                webview.close()
        self._webviews.clear()
        
        # Close container widget
        if self._container_widget:
            self._container_widget.deleteLater()
            self._container_widget = None


class RuntimeStatus:
    def __init__(self, available: bool, message: str) -> None:
        self.available = available
        self.message = message


def _runtime_status() -> RuntimeStatus:
    available, message = check_webview2_available()
    return RuntimeStatus(available, message)


def build_web_context(engine=None, controller=None, settings=None):
    """ModeSpec setup hook."""
    profile = paths.data_dir() / "web"
    profile.mkdir(parents=True, exist_ok=True)
    return WebContext(settings=settings)
