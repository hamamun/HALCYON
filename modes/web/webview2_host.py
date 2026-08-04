"""Per-tab WebView2 host wrapping a native child HWND (§P3.2, §P3.4).

Each tab in Web mode runs inside a native child window below Halcyon's chrome.
Using direct Edge WebView2 via pythonnet gives us:
  • Single shared CoreWebView2Environment across all tabs.
  • add_NewWindowRequested -> routes popup/new-window requests to new Halcyon tabs
    never opening an outside browser window (§P3.4).
  • Anti-bot User-Agent and navigator.webdriver hiding (§P3.1).
  • Graceful fallback when runtime is not available ("WebView2 is not available").
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from PySide6.QtCore import Property, QObject, Signal

from modes.web import webview2_runtime

logger = logging.getLogger("modes.web.webview2_host")


class WebViewHost(QObject):
    """Host controller for a single WebView2 tab (§P3.2).

    Manages the CoreWebView2Controller bound to a parent window HWND.
    All public methods operate safely even when WebView2 is not available.
    """

    urlChanged = Signal(str)
    titleChanged = Signal(str)
    loadingChanged = Signal(bool)
    newWindowRequested = Signal(str)  # ★ Route site popups to new Halcyon tabs (§P3.4)
    errorOccurred = Signal(str)
    faviconChanged = Signal(str)
    fullscreenChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url: str = ""
        self._title: str = ""
        self._loading: bool = False
        self._is_ready: bool = False
        self._error_message: str = ""
        self._pending_url: str = ""

        self.controller: Any = None
        self.webview: Any = None
        self._bounds: tuple[int, int, int, int] = (0, 0, 800, 600)
        self._visible: bool = True

    @Property(str, notify=urlChanged)
    def url(self) -> str:
        return self._url

    @Property(str, notify=titleChanged)
    def title(self) -> str:
        return self._title

    @Property(bool, notify=loadingChanged)
    def loading(self) -> bool:
        return self._loading

    @Property(bool)
    def isReady(self) -> bool:
        return self._is_ready

    @Property(str, notify=errorOccurred)
    def errorMessage(self) -> str:
        return self._error_message

    def init_controller(self, parent_hwnd: int, env: Any = None) -> bool:
        """Initialize the CoreWebView2Controller inside parent_hwnd.

        Returns False and emits errorOccurred if runtime is not available.
        """
        if not webview2_runtime.is_webview2_available():
            self._error_message = webview2_runtime.get_stage_error_message()
            self.errorOccurred.emit(self._error_message)
            return False

        if sys.platform != "win32":
            self._error_message = webview2_runtime.get_stage_error_message()
            self.errorOccurred.emit(self._error_message)
            return False

        try:
            webview2_runtime.init_pythonnet_com()
            environment = env or webview2_runtime.get_shared_environment()
            if not environment:
                self._error_message = webview2_runtime.get_stage_error_message()
                self.errorOccurred.emit(self._error_message)
                return False

            task = environment.CreateCoreWebView2ControllerAsync(parent_hwnd)
            controller = task.ConfigureAwait(False).GetAwaiter().GetResult()
            self.controller = controller
            self.webview = controller.CoreWebView2

            # Configure bounds and visibility
            x, y, w, h = self._bounds
            self._apply_bounds_to_controller(x, y, w, h)
            controller.IsVisible = self._visible

            # Configure anti-bot User-Agent & navigator.webdriver hiding (§P3.1, §P3.2)
            default_ua = getattr(self.webview.Settings, "UserAgent", "")
            self.webview.Settings.UserAgent = webview2_runtime.get_anti_bot_user_agent(
                default_ua
            )
            self.webview.AddScriptToExecuteOnDocumentCreatedAsync(
                webview2_runtime.get_anti_bot_init_script()
            )

            # Apply sensible browser settings (§P3.2)
            settings = self.webview.Settings
            settings.IsScriptEnabled = True
            settings.IsWebMessageEnabled = True
            settings.IsStatusBarEnabled = False
            settings.AreDefaultContextMenusEnabled = True
            settings.IsZoomControlEnabled = True
            settings.AreDevToolsEnabled = True
            settings.IsGeneralAutofillEnabled = True
            settings.IsPasswordAutosaveEnabled = True

            # Connect event handlers
            self._connect_webview_events()

            self._is_ready = True
            if self._pending_url:
                url = self._pending_url
                self._pending_url = ""
                self.navigate(url)
            return True
        except Exception as exc:
            logger.warning("Failed to initialize WebView2 controller: %s", exc)
            self._error_message = webview2_runtime.get_stage_error_message()
            self.errorOccurred.emit(self._error_message)
            return False

    def _connect_webview_events(self) -> None:
        """Bind .NET events on CoreWebView2 to our Qt signals."""
        if not self.webview:
            return

        def on_navigation_starting(sender: Any, args: Any) -> None:
            self._loading = True
            self.loadingChanged.emit(True)

        def on_navigation_completed(sender: Any, args: Any) -> None:
            self._loading = False
            self.loadingChanged.emit(False)
            if hasattr(self.webview, "Source"):
                self._set_url(str(self.webview.Source))

        def on_source_changed(sender: Any, args: Any) -> None:
            if hasattr(self.webview, "Source"):
                self._set_url(str(self.webview.Source))

        def on_title_changed(sender: Any, args: Any) -> None:
            if hasattr(self.webview, "DocumentTitle"):
                title = str(self.webview.DocumentTitle)
                self._title = title
                self.titleChanged.emit(title)

        def on_new_window_requested(sender: Any, args: Any) -> None:
            self.handle_new_window_request(args, self.newWindowRequested.emit)

        def on_fullscreen_changed(sender: Any, args: Any) -> None:
            if hasattr(self.webview, "ContainsFullScreenElement"):
                self.fullscreenChanged.emit(bool(self.webview.ContainsFullScreenElement))

        self.webview.NavigationStarting += on_navigation_starting
        self.webview.NavigationCompleted += on_navigation_completed
        self.webview.SourceChanged += on_source_changed
        self.webview.DocumentTitleChanged += on_title_changed
        self.webview.NewWindowRequested += on_new_window_requested
        self.webview.ContainsFullScreenElementChanged += on_fullscreen_changed

    @staticmethod
    def handle_new_window_request(args: Any, emitter: Any) -> None:
        """Route popup/new-window requests to a new Halcyon tab (§P3.1, §P3.4).

        Blocks external browser windows by setting args.Handled = True, and
        emits the requested URI so the tab model can open a new tab.
        """
        args.Handled = True
        uri = getattr(args, "Uri", None) or getattr(args, "uri", "")
        if uri:
            emitter(str(uri))

    def _set_url(self, url: str) -> None:
        if url != self._url:
            self._url = url
            self.urlChanged.emit(self._url)

    def navigate(self, url_or_search: str) -> None:
        """Navigate to a URL or perform a default Google search (§P3.1, §P3.4)."""
        resolved = webview2_runtime.resolve_url_or_search(url_or_search)
        self._set_url(resolved)

        if self.webview:
            try:
                self.webview.Navigate(resolved)
            except Exception as exc:
                logger.warning("WebView2 navigation failed for %s: %s", resolved, exc)
        else:
            self._pending_url = resolved

    def go_back(self) -> None:
        if self.webview and getattr(self.webview, "CanGoBack", False):
            try:
                self.webview.GoBack()
            except Exception as exc:
                logger.debug("go_back failed: %s", exc)

    def go_forward(self) -> None:
        if self.webview and getattr(self.webview, "CanGoForward", False):
            try:
                self.webview.GoForward()
            except Exception as exc:
                logger.debug("go_forward failed: %s", exc)

    def reload(self) -> None:
        if self.webview:
            try:
                self.webview.Reload()
            except Exception as exc:
                logger.debug("reload failed: %s", exc)

    def stop(self) -> None:
        if self.webview:
            try:
                self.webview.Stop()
            except Exception as exc:
                logger.debug("stop failed: %s", exc)

    def set_bounds(self, x: int, y: int, width: int, height: int) -> None:
        """Update native child window rectangle below Halcyon chrome (§P3.2)."""
        self._bounds = (x, y, width, height)
        if self.controller:
            self._apply_bounds_to_controller(x, y, width, height)

    def _apply_bounds_to_controller(self, x: int, y: int, width: int, height: int) -> None:
        if not self.controller or sys.platform != "win32":
            return
        try:
            import System.Drawing  # type: ignore[import-not-found]

            rect = System.Drawing.Rectangle(x, y, width, height)
            self.controller.Bounds = rect
        except Exception:
            try:
                self.controller.Bounds = (x, y, width, height)
            except Exception as exc:
                logger.debug("Failed setting controller bounds: %s", exc)

    def set_visible(self, visible: bool) -> None:
        """Show or park the child HWND when switching tabs/modes (§P3.3)."""
        self._visible = visible
        if self.controller:
            try:
                self.controller.IsVisible = visible
            except Exception as exc:
                logger.debug("set_visible failed: %s", exc)

    def close(self) -> None:
        """Close the controller and release COM references cleanly."""
        self._is_ready = False
        if self.controller:
            try:
                self.controller.Close()
            except Exception as exc:
                logger.debug("Error closing WebView2 controller: %s", exc)
            self.controller = None
            self.webview = None
