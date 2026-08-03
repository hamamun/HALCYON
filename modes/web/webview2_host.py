"""Web-mode controller: QML chrome plus native WebView2 child surfaces."""
from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Property, Signal, Slot

from core import paths
from modes.web.bookmarks import BookmarkModel, clean_title, normalise_url
from modes.web.tabs import MANAGER_URL, MAX_TABS, TabModel, display_url
from modes.web import webview_integration
from modes.web.webview_integration import check_webview2_available

if TYPE_CHECKING:
    from PySide6.QtQuick import QQuickWindow

log = logging.getLogger(__name__)


def _is_valid_hwnd(hwnd: int) -> bool:
    """Return True when ``hwnd`` names a live native window.

    WebView2 controller creation fails with ERROR_INVALID_WINDOW_HANDLE if Qt
    has already discarded/recreated the HWND that was captured earlier.  The
    guard is intentionally cheap and side-effect free: when Qt reports a handle
    that Windows does not recognise yet (or no handle at all), the host simply
    defers controller creation until the next geometry/visibility sync.
    """
    if not hwnd:
        return False
    if sys.platform != "win32":
        # Non-Windows test environments never create WebView2 controllers, but
        # treating non-zero fake handles as valid lets lifecycle tests exercise
        # the retry logic with monkeypatched WebView factories.
        return True
    try:
        import ctypes

        return bool(ctypes.windll.user32.IsWindow(int(hwnd)))
    except Exception as exc:  # pragma: no cover - defensive Windows guard
        log.warning("Could not validate HALCYON window handle %s: %s", hwnd, exc)
        return False


class WebContext(QObject):
    """QML-facing browser state and owner of native tab controllers.

    The QML stage remains HALCYON's existing UI.  Its browser rectangle reports
    geometry here; the active native WebView2 child is positioned over exactly
    that rectangle.
    """
    activeChanged = Signal()
    toastRequested = Signal(str)
    runtimeChanged = Signal()
    nativeVisibilityChanged = Signal()

    def __init__(self, settings=None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._tabs = TabModel(self)
        self._bookmarks = BookmarkModel(parent=self)
        available, message = check_webview2_available()
        self._runtime_available, self._runtime_message = available, message
        #: Last WebView2 controller init failure, shown instead of the generic
        #: "runtime detected" line when a controller could not start.  Empty
        #: when everything is healthy.  Kept separate from ``_runtime_available``
        #: (which only reflects whether the pip package imports) so a one-off
        #: init failure never permanently masks a later successful start.
        self._init_error_message = ""
        self._window: QQuickWindow | None = None
        self._window_hwnd = 0
        self._bounds = (0, 0, 0, 0)
        self._stage_visible = False
        self._popup_open = False
        # Keys are id(Tab), not list indexes: indexes change when a tab closes.
        self._webviews: dict[int, webview_integration.WebViewBase | None] = {}

        self._tabs.activeChanged.connect(self._sync_webviews)
        self._tabs.changed.connect(self._sync_webviews)
        self._tabs.limitReached.connect(lambda: self.toastRequested.emit(f"Maximum {MAX_TABS} tabs reached."))
        self._bookmarks.changed.connect(self.activeChanged)

    @Property(QObject, constant=True)
    def tabs(self) -> QObject: return self._tabs
    @Property(QObject, constant=True)
    def bookmarks(self) -> QObject: return self._bookmarks
    @Property(str, notify=activeChanged)
    def activeUrl(self) -> str: return self._tabs.activeUrl
    @Property(str, notify=activeChanged)
    def activeDisplayUrl(self) -> str: return display_url(self._tabs.activeUrl)
    @Property(str, notify=activeChanged)
    def activeTitle(self) -> str: return self._tabs.activeTitle
    @Property(bool, notify=activeChanged)
    def hasActiveTab(self) -> bool: return self._tabs.hasActiveTab
    @Property(bool, notify=activeChanged)
    def activeIsManager(self) -> bool: return self._tabs.activeIsManager
    @Property(bool, notify=activeChanged)
    def activeBookmarked(self) -> bool: return self.current_bookmark_index() >= 0
    @Property(int, notify=activeChanged)
    def currentBookmarkIndex(self) -> int: return self.current_bookmark_index()
    @Property(bool, notify=activeChanged)
    def canGoBack(self) -> bool: # noqa: N802
        view = self._active_webview()
        return view.can_go_back if view else self._tabs.canGoBack
    @Property(bool, notify=activeChanged)
    def canGoForward(self) -> bool: # noqa: N802
        view = self._active_webview()
        return view.can_go_forward if view else self._tabs.canGoForward
    @Property(bool, notify=runtimeChanged)
    def webView2Available(self) -> bool: return self._runtime_available
    @Property(str, notify=runtimeChanged)
    def webView2Status(self) -> str: return self._runtime_message
    @Property(str, notify=runtimeChanged)
    def webView2InitError(self) -> str: return self._init_error_message
    @Property(bool, notify=nativeVisibilityChanged)
    def nativeBrowserVisible(self) -> bool: # noqa: N802
        return self._native_should_be_visible()

    # QML bridge -------------------------------------------------------------
    @Slot(QObject)
    def attachWindow(self, window: QObject) -> None: # noqa: N802
        """Receive the QQuickWindow that owns the QML scene.

        Do not cache ``winId()`` here as the final HWND.  Calling ``winId()`` can
        cause Qt to create/recreate the native window, and a handle captured at
        component-completion time may be stale by the time the user opens a URL.
        ``_sync_webviews`` re-queries and validates the current HWND every time
        it needs to touch a native WebView2 controller.
        """
        if self._window is not window:
            self._window = window  # keep the Python wrapper alive
            try:
                window.visibleChanged.connect(lambda *_: self._sync_webviews())
            except Exception:
                pass
        self._sync_webviews()

    @Slot(float, float, float, float, bool)
    def setBrowserRect(self, x: float, y: float, width: float, height: float, visible: bool) -> None: # noqa: N802
        """Set QML browserRect bounds in QQuickWindow client coordinates."""
        # WebView2 consumes native pixels; QML uses device-independent pixels.
        dpr = float(getattr(self._window, "devicePixelRatio", lambda: 1.0)()) if self._window else 1.0
        self._bounds = tuple(round(v * dpr) for v in (x, y, width, height))
        self._stage_visible = bool(visible)
        self._sync_webviews()

    @Slot(bool)
    def setOverlayOpen(self, open_: bool) -> None: # noqa: N802
        """Hide the native child while a QML overlay occupies browserRect."""
        self._popup_open = bool(open_)
        self._sync_webviews()

    # tabs -------------------------------------------------------------------
    @Slot()
    def newTab(self) -> None: self._tabs.newBlankTab()
    @Slot(str)
    def openNewTab(self, url: str) -> None: self._tabs.openUrl(url)
    @Slot()
    def openBookmarkManager(self) -> None: self._tabs.openManager()
    @Slot(int)
    def activateTab(self, index: int) -> None: self._tabs.activate(index)
    @Slot(int)
    def closeTab(self, index: int) -> None: self._tabs.close(index)
    @Slot(int)
    def openBookmark(self, source_index: int) -> None:
        item = self._bookmarks.get(source_index)
        if isinstance(item, dict) and item.get("url"):
            self.navigate(str(item["url"]))

    @Slot(str)
    def navigate(self, text: str) -> None:
        url = normalise_url(text)
        if not url:
            return
        self._tabs.navigateActive(url)
        self._sync_webviews()
        view = self._active_webview()
        if view:
            view.navigate(url)

    @Slot()
    def goBack(self) -> None: # noqa: N802
        view = self._active_webview()
        if view: view.go_back()
        else: self._tabs.back()
    @Slot()
    def goForward(self) -> None: # noqa: N802
        view = self._active_webview()
        if view: view.go_forward()
        else: self._tabs.forward()
    @Slot()
    def reload(self) -> None:
        view = self._active_webview()
        if view: view.reload()
    @Slot()
    def stop(self) -> None:
        view = self._active_webview()
        if view: view.stop()
    @Slot()
    def home(self) -> None: self.navigate("https://www.bing.com")

    # bookmarks --------------------------------------------------------------
    @Slot(str, str, result=bool)
    def saveBookmark(self, title: str, url: str) -> bool: # noqa: N802
        ok = self._bookmarks.addBookmark(title, url)
        if ok: self.toastRequested.emit("Bookmark saved.")
        return ok
    @Slot(str, result=bool)
    def saveCurrentBookmark(self, title: str = "") -> bool: # noqa: N802
        url = self._tabs.activeUrl
        return bool(url and url not in ("about:blank", MANAGER_URL) and self.saveBookmark(title or self._tabs.activeTitle, url))
    @Slot(str, str, result=bool)
    def updateCurrentBookmark(self, title: str, url: str) -> bool: # noqa: N802
        idx = self.current_bookmark_index()
        return self.saveBookmark(title, url) if idx < 0 else self._bookmarks.updateBookmark(idx, clean_title(title, url), normalise_url(url))
    @Slot(result=bool)
    def removeCurrentBookmark(self) -> bool: # noqa: N802
        idx = self.current_bookmark_index()
        return idx >= 0 and self._bookmarks.deleteBookmark(idx)
    @Slot(int, str, str, result=bool)
    def updateBookmark(self, index: int, title: str, url: str) -> bool: return self._bookmarks.updateBookmark(index, title, url)
    @Slot(int, result=bool)
    def deleteBookmark(self, index: int) -> bool: return self._bookmarks.deleteBookmark(index)
    @Slot(int, int, result=bool)
    def moveBookmark(self, source: int, target: int) -> bool: return self._bookmarks.moveBookmark(source, target)
    @Slot(int, result="QVariant")
    def bookmark(self, index: int): return self._bookmarks.get(index)
    def current_bookmark_index(self) -> int:
        url = self._tabs.activeUrl
        return -1 if not url or url in ("about:blank", MANAGER_URL) else self._bookmarks.index_of_url(url)

    # native host lifecycle --------------------------------------------------
    def _current_hwnd(self) -> int:
        """Fetch and validate the current QQuickWindow HWND.

        Qt may replace the native window after ``winId()`` has first been called.
        Returning the latest valid handle here prevents WebView2 from being
        parented to a stale HWND; returning 0 tells the caller to defer and try
        again on the next sync rather than caching a failed controller forever.
        """
        if not self._window:
            return 0
        try:
            hwnd = int(self._window.winId())
        except Exception as exc:
            log.warning("Could not get the HALCYON window handle: %s", exc)
            return 0
        if not _is_valid_hwnd(hwnd):
            log.debug("HALCYON QML window HWND %s is not valid yet; deferring WebView2 creation", hwnd)
            return 0
        return hwnd

    def _close_all_webviews(self) -> None:
        for view in self._webviews.values():
            if view:
                view.close()
        self._webviews.clear()

    def _sync_webviews(self) -> None:
        current_hwnd = self._current_hwnd()
        if current_hwnd != self._window_hwnd:
            if self._window_hwnd or current_hwnd:
                log.info("WebView2 HALCYON window HWND changed from %s to %s", self._window_hwnd, current_hwnd)
            # Existing native child windows are parented to the old HWND (which
            # may already be invalid), so discard them and let this/later syncs
            # recreate against the fresh handle.
            self._close_all_webviews()
            self._window_hwnd = current_hwnd

        live_ids = {id(tab) for tab in self._tabs._tabs if not tab.is_manager}
        for key in list(self._webviews):
            view = self._webviews.get(key)
            if key not in live_ids:
                view = self._webviews.pop(key)
                if view:
                    view.close()
            elif view is not None and not view.is_ready:
                view = self._webviews.pop(key)
                view.close()
        if self._window_hwnd:
            for tab in self._tabs._tabs:
                if not tab.is_manager and id(tab) not in self._webviews:
                    self._create_webview(tab)
        active = self._tabs.active_tab()
        active_key = id(active) if active and not active.is_manager else None
        visible = self._native_should_be_visible()
        for key, view in self._webviews.items():
            if view:
                view.update_bounds(*self._bounds)
                view.set_visible(visible and key == active_key)
        self.activeChanged.emit()
        self.nativeVisibilityChanged.emit()

    def _create_webview(self, tab) -> None:
        key = id(tab)
        # Reserve the slot *before* the native initialisation. WebView2 init
        # pumps a nested QEventLoop (see webview2_windows._run_initialization),
        # so a re-entrant _sync_webviews during it must see this tab as already
        # being created rather than spawn a duplicate controller.
        self._webviews[key] = None
        view = webview_integration.create_webview(
            self._window_hwnd, tab.url,
            on_title_changed=lambda title, k=key: self._on_webview_title(k, title),
            on_url_changed=lambda url, k=key: self._on_webview_url(k, url),
            on_loading_changed=lambda loading, k=key: self._on_webview_loading(k, loading),
            on_navigation_completed=lambda success, k=key: self._on_webview_completed(k, success),
            on_init_error=lambda message, k=key: self._on_webview_init_error(k, message),
        )
        # Native init pumps a nested event loop, so the tab could have been
        # closed (or the whole browser torn down) while we were creating the
        # controller.  Drop it rather than leave a controller parented to a tab
        # nobody owns anymore.
        still_live = {id(t) for t in self._tabs._tabs if not t.is_manager}
        if key not in still_live:
            if view:
                view.close()
            self._webviews.pop(key, None)
            return
        if not (view and view.is_ready):
            # ``None`` or a WebView object whose controller failed to initialise
            # must not occupy the tab slot forever.  Dropping it lets a later
            # geometry/visibility/navigation sync retry, which is crucial when
            # the previous attempt raced a stale HWND.
            if view:
                view.close()
            self._webviews.pop(key, None)
            return
        if self._init_error_message:
            self._init_error_message = ""
            self.runtimeChanged.emit()
        self._webviews[key] = view

    def _tab_for_key(self, key: int):
        return next((tab for tab in self._tabs._tabs if id(tab) == key), None)
    def _active_webview(self):
        tab = self._tabs.active_tab()
        return self._webviews.get(id(tab)) if tab and not tab.is_manager else None
    def _native_should_be_visible(self) -> bool:
        if not (self._runtime_available and self._stage_visible and not self._popup_open and
                self._tabs.hasActiveTab and not self._tabs.activeIsManager and self._window_hwnd):
            return False
        # Availability only means the WebView2 *package* imports.  If the actual
        # runtime/controller failed to start, do not claim the native browser is
        # showing: the QML fallback column (which appears when this is false)
        # is the only place the user learns init failed instead of staring at a
        # silent blank rectangle.
        view = self._active_webview()
        return bool(view and view.is_ready)
    def _on_webview_title(self, key: int, title: str) -> None:
        tab = self._tab_for_key(key)
        if tab: self._tabs.set_web_state(tab, title=title)
    def _on_webview_url(self, key: int, url: str) -> None:
        tab = self._tab_for_key(key)
        if tab: self._tabs.set_web_state(tab, url=url)
    def _on_webview_loading(self, key: int, loading: bool) -> None:
        tab = self._tab_for_key(key)
        if tab: self._tabs.set_web_state(tab, loading=loading)
    def _on_webview_completed(self, key: int, _success: bool) -> None:
        self._on_webview_loading(key, False)
    def _on_webview_init_error(self, key: int, message: str) -> None:
        """A native controller could not start: tell the UI instead of a blank box.

        ``is_ready`` stays False on the view, so ``nativeBrowserVisible`` is now
        False and the QML fallback column will show ``webView2Status`` — which is
        exactly the message we set here.
        """
        tab = self._tab_for_key(key)
        label = f" in {tab.title!r}" if tab else ""
        log.error("WebView2 initialisation failed%s: %s", label, message)
        self._init_error_message = message
        self.runtimeChanged.emit()
        self.nativeVisibilityChanged.emit()
    def _set_runtime_error(self, message: str) -> None:
        self._runtime_available, self._runtime_message = False, message
        self.runtimeChanged.emit()

    def shutdown(self) -> None:
        for view in self._webviews.values():
            if view: view.close()
        self._webviews.clear()


class RuntimeStatus:
    def __init__(self, available: bool, message: str) -> None:
        self.available, self.message = available, message


def _runtime_status() -> RuntimeStatus:
    return RuntimeStatus(*check_webview2_available())


def build_web_context(engine=None, controller=None, settings=None):
    profile = paths.data_dir() / "web"
    profile.mkdir(parents=True, exist_ok=True)
    return WebContext(settings=settings)
