"""A single native Edge WebView2 controller hosted inside Halcyon's window.

``WebViewHost`` deliberately knows nothing about tabs, bookmarks or QML.  It
owns one controller and turns .NET events into ordinary Qt signals; the
``BrowserContext`` owns the tab model and decides which host is visible.

The controller's native child HWND is bounded only to the browser page area.
That is essential: a native child is always above Qt Quick scene-graph content,
so it must never overlap Halcyon's title bar, tab strip, address bar or menus.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, Signal

from modes.web import webview2_runtime

logger = logging.getLogger("modes.web.webview2_host")


class WebViewHost(QObject):
    """One WebView2 controller and its event bridge.

    All public methods are safe when the Windows runtime is absent.  That lets
    the same BrowserContext run on Linux CI and lets the QML stage show a clear
    unavailable message rather than crashing at import time.
    """

    urlChanged = Signal(str)
    titleChanged = Signal(str)
    loadingChanged = Signal(bool)
    historyChanged = Signal(bool, bool)
    readyChanged = Signal(bool)
    newWindowRequested = Signal(str)
    errorOccurred = Signal(str)
    faviconChanged = Signal(str)
    fullscreenChanged = Signal(bool)
    downloadRequested = Signal(str)
    certificateError = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = ""
        self._title = ""
        self._loading = False
        self._is_ready = False
        self._error_message = ""
        self._pending_url = ""
        self._parent_hwnd = 0
        self._bounds = (0, 0, 1, 1)
        self._visible = False

        self.controller: Any = None
        self.webview: Any = None
        # Pythonnet event delegates must remain strongly referenced.  Without
        # this list, a garbage collection can silently disconnect events or
        # crash later in a .NET callback.
        self._event_handlers: list[tuple[Any, str, Callable[..., None]]] = []
        self._pending_tasks: list[Any] = []

    @Property(str, notify=urlChanged)
    def url(self) -> str:
        return self._url

    @Property(str, notify=titleChanged)
    def title(self) -> str:
        return self._title

    @Property(bool, notify=loadingChanged)
    def loading(self) -> bool:
        return self._loading

    @Property(bool, notify=readyChanged)
    def isReady(self) -> bool:  # noqa: N802 - QML API
        return self._is_ready

    @Property(str, notify=errorOccurred)
    def errorMessage(self) -> str:  # noqa: N802 - QML API
        return self._error_message

    @property
    def parent_hwnd(self) -> int:
        return self._parent_hwnd

    # ------------------------------------------------------------------ setup
    def init_controller(self, parent_hwnd: int, env: Any = None) -> bool:
        """Create a controller as a child of ``parent_hwnd``.

        The BrowserContext calls this only after the QQuickWindow has a native
        HWND.  Repeated calls for the same handle are harmless; a changed parent
        closes the old controller before creating a new one.
        """
        try:
            hwnd = int(parent_hwnd)
        except (TypeError, ValueError):
            hwnd = 0
        if hwnd <= 0:
            self._fail(webview2_runtime.get_stage_error_message())
            return False

        if self.controller is not None and self._parent_hwnd == hwnd:
            return True
        if self.controller is not None:
            self.release_controller()

        if sys.platform != "win32":
            self._fail(webview2_runtime.get_stage_error_message())
            return False
        if env is None and not webview2_runtime.is_webview2_available():
            self._fail(webview2_runtime.get_stage_error_message())
            return False

        try:
            environment = env if env is not None else webview2_runtime.get_shared_environment()
            if environment is None:
                self._fail(webview2_runtime.get_stage_error_message())
                return False

            import System  # type: ignore[import-not-found]
            task = environment.CreateCoreWebView2ControllerAsync(System.IntPtr(hwnd))
            controller = webview2_runtime._wait_for_task(task)
            self.controller = controller
            self.webview = controller.CoreWebView2
            self._parent_hwnd = hwnd

            self._configure_webview()
            self._connect_webview_events()
            self._apply_bounds_to_controller(*self._bounds)
            self.controller.IsVisible = bool(self._visible)

            self._set_ready(True)
            if self._pending_url:
                pending = self._pending_url
                self._pending_url = ""
                self.navigate(pending)
            return True
        except Exception as exc:
            logger.warning("failed to initialize WebView2 controller: %s", exc, exc_info=True)
            self.release_controller()
            self._fail(webview2_runtime.get_stage_error_message())
            return False

    def _configure_webview(self) -> None:
        """Apply only settings exposed by the installed SDK/runtime version."""
        if self.webview is None:
            return

        settings = self.webview.Settings
        default_ua = ""
        try:
            default_ua = str(settings.UserAgent or "")
        except Exception:
            pass
        self._set_setting(settings, "UserAgent", webview2_runtime.get_anti_bot_user_agent(default_ua))
        self._set_setting(settings, "IsScriptEnabled", True)
        self._set_setting(settings, "IsWebMessageEnabled", True)
        self._set_setting(settings, "IsStatusBarEnabled", False)
        self._set_setting(settings, "AreDefaultContextMenusEnabled", True)
        self._set_setting(settings, "IsZoomControlEnabled", True)
        self._set_setting(settings, "AreDevToolsEnabled", True)
        self._set_setting(settings, "IsGeneralAutofillEnabled", True)
        self._set_setting(settings, "IsPasswordAutosaveEnabled", True)

        try:
            task = self.webview.AddScriptToExecuteOnDocumentCreatedAsync(
                webview2_runtime.get_anti_bot_init_script()
            )
            self._pending_tasks.append(task)
        except Exception as exc:
            # Hiding webdriver is useful but must never make a valid browser
            # controller disappear on an older WebView2 runtime.
            logger.debug("could not install webdriver compatibility script: %s", exc)

    @staticmethod
    def _set_setting(settings: Any, name: str, value: Any) -> None:
        try:
            if hasattr(settings, name):
                setattr(settings, name, value)
        except Exception as exc:
            logger.debug("WebView2 setting %s was rejected: %s", name, exc)

    # ------------------------------------------------------------------ events
    def _connect_webview_events(self) -> None:
        if self.webview is None:
            return

        def navigation_starting(_sender: Any, _args: Any) -> None:
            self._set_loading(True)

        def navigation_completed(_sender: Any, args: Any) -> None:
            self._set_loading(False)
            self._update_source()
            try:
                if not bool(args.IsSuccess):
                    logger.info("WebView2 navigation did not complete: %s", args.WebErrorStatus)
            except Exception:
                pass
            self._emit_history()

        def source_changed(_sender: Any, _args: Any) -> None:
            self._update_source()
            self._emit_history()

        def title_changed(_sender: Any, _args: Any) -> None:
            try:
                self._set_title(str(self.webview.DocumentTitle or ""))
            except Exception:
                pass

        def history_changed(_sender: Any, _args: Any) -> None:
            self._emit_history()

        def new_window_requested(_sender: Any, args: Any) -> None:
            self.handle_new_window_request(args, self.newWindowRequested.emit)

        def fullscreen_changed(_sender: Any, _args: Any) -> None:
            try:
                self.fullscreenChanged.emit(bool(self.webview.ContainsFullScreenElement))
            except Exception:
                pass

        def favicon_changed(_sender: Any, _args: Any) -> None:
            try:
                self.faviconChanged.emit(str(self.webview.FaviconUri or ""))
            except Exception:
                pass

        def download_starting(_sender: Any, args: Any) -> None:
            # Do not suppress WebView2's own save prompt.  It is the secure
            # fallback for v1: users choose the target through Edge's runtime
            # UI, while the request remains inside this controller.
            try:
                self.downloadRequested.emit(str(args.DownloadOperation.Uri or ""))
            except Exception:
                self.downloadRequested.emit("")

        def certificate_error(_sender: Any, args: Any) -> None:
            # Never auto-accept a bad certificate.  Leaving Action untouched
            # preserves Edge/WebView2's secure error page/default decision.
            try:
                self.certificateError.emit(str(args.RequestUri or ""))
            except Exception:
                self.certificateError.emit("")

        self._subscribe("NavigationStarting", navigation_starting)
        self._subscribe("NavigationCompleted", navigation_completed)
        self._subscribe("SourceChanged", source_changed)
        self._subscribe("DocumentTitleChanged", title_changed)
        self._subscribe("HistoryChanged", history_changed)
        self._subscribe("NewWindowRequested", new_window_requested)
        self._subscribe("ContainsFullScreenElementChanged", fullscreen_changed)
        self._subscribe("FaviconChanged", favicon_changed)
        self._subscribe("DownloadStarting", download_starting)
        self._subscribe("ServerCertificateErrorDetected", certificate_error)

    def _subscribe(self, event_name: str, callback: Callable[..., None]) -> None:
        """Subscribe when an event exists in this SDK version and retain it."""
        if self.webview is None or not hasattr(self.webview, event_name):
            return
        try:
            event = getattr(self.webview, event_name)
            event += callback
            self._event_handlers.append((self.webview, event_name, callback))
        except Exception as exc:
            logger.debug("could not subscribe to WebView2 %s: %s", event_name, exc)

    def _unsubscribe_events(self) -> None:
        for owner, event_name, callback in reversed(self._event_handlers):
            try:
                getattr(owner, event_name).__isub__(callback)
            except Exception:
                # Some pythonnet event wrappers do not expose __isub__ after
                # their controller was closed.  The controller owns the event
                # source, so closing it still releases the delegate.
                pass
        self._event_handlers.clear()

    @staticmethod
    def handle_new_window_request(args: Any, emitter: Callable[[str], None]) -> None:
        """Block an outside Edge window and route its URL to Halcyon's tab model."""
        try:
            args.Handled = True
        except Exception:
            logger.debug("could not mark NewWindowRequested as handled", exc_info=True)
        uri = getattr(args, "Uri", None) or getattr(args, "uri", "")
        if uri:
            emitter(str(uri))

    # --------------------------------------------------------------- state sync
    def _update_source(self) -> None:
        try:
            self._set_url(str(self.webview.Source or ""))
        except Exception:
            pass

    def _emit_history(self) -> None:
        try:
            self.historyChanged.emit(
                bool(getattr(self.webview, "CanGoBack", False)),
                bool(getattr(self.webview, "CanGoForward", False)),
            )
        except Exception:
            self.historyChanged.emit(False, False)

    def _set_url(self, value: str) -> None:
        if value != self._url:
            self._url = value
            self.urlChanged.emit(value)

    def _set_title(self, value: str) -> None:
        if value != self._title:
            self._title = value
            self.titleChanged.emit(value)

    def _set_loading(self, value: bool) -> None:
        if value != self._loading:
            self._loading = value
            self.loadingChanged.emit(value)

    def _set_ready(self, value: bool) -> None:
        if value != self._is_ready:
            self._is_ready = value
            self.readyChanged.emit(value)

    def _fail(self, message: str) -> None:
        self._error_message = message
        self._set_ready(False)
        self.errorOccurred.emit(message)

    # --------------------------------------------------------------- commands
    def navigate(self, url_or_search: str) -> None:
        resolved = webview2_runtime.resolve_url_or_search(url_or_search)
        self._set_url(resolved)
        if self.webview is None:
            self._pending_url = resolved
            return
        try:
            self.webview.Navigate(resolved)
        except Exception as exc:
            logger.warning("WebView2 navigation failed for %s: %s", resolved, exc)

    def go_back(self) -> None:
        try:
            if self.webview is not None and bool(self.webview.CanGoBack):
                self.webview.GoBack()
        except Exception as exc:
            logger.debug("WebView2 back failed: %s", exc)

    def go_forward(self) -> None:
        try:
            if self.webview is not None and bool(self.webview.CanGoForward):
                self.webview.GoForward()
        except Exception as exc:
            logger.debug("WebView2 forward failed: %s", exc)

    def reload(self) -> None:
        try:
            if self.webview is not None:
                self.webview.Reload()
        except Exception as exc:
            logger.debug("WebView2 reload failed: %s", exc)

    def stop(self) -> None:
        try:
            if self.webview is not None:
                self.webview.Stop()
        except Exception as exc:
            logger.debug("WebView2 stop failed: %s", exc)

    # -------------------------------------------------------------- placement
    def set_bounds(self, x: int, y: int, width: int, height: int) -> None:
        self._bounds = (int(x), int(y), max(0, int(width)), max(0, int(height)))
        if self.controller is not None:
            self._apply_bounds_to_controller(*self._bounds)

    def _apply_bounds_to_controller(self, x: int, y: int, width: int, height: int) -> None:
        if self.controller is None or sys.platform != "win32":
            return
        try:
            from System.Drawing import Rectangle  # type: ignore[import-not-found]

            self.controller.Bounds = Rectangle(x, y, width, height)
        except Exception as exc:
            logger.debug("could not set WebView2 bounds: %s", exc)

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        if self.controller is not None:
            try:
                self.controller.IsVisible = self._visible
            except Exception as exc:
                logger.debug("could not set WebView2 visibility: %s", exc)

    # --------------------------------------------------------------- teardown
    def release_controller(self, *, preserve_navigation: bool = True) -> None:
        """Close the native controller while optionally preserving its URL.

        A controller is tied to one parent HWND.  If Qt recreates that window,
        BrowserContext releases and reattaches the host; retaining the current
        URL lets the new controller restore the tab instead of becoming blank.
        """
        if preserve_navigation and self._url:
            self._pending_url = self._url
        self._unsubscribe_events()
        controller = self.controller
        self.controller = None
        self.webview = None
        self._parent_hwnd = 0
        self._pending_tasks.clear()
        self._set_ready(False)
        if controller is not None:
            try:
                controller.Close()
            except Exception as exc:
                logger.debug("WebView2 controller close failed: %s", exc)

    def close(self) -> None:
        """Permanently close the controller and discard pending navigation."""
        self._pending_url = ""
        self.release_controller(preserve_navigation=False)
