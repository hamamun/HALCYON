"""Native Windows WebView2 surface used by HALCYON's QML Web mode.

WebView2 is a windowed WinRT control.  QML supplies the rectangle it should
occupy; this class parents the native controller to HALCYON's QQuickWindow HWND
and keeps that controller clipped to the supplied rectangle.
"""
from __future__ import annotations

import logging
import sys
from typing import Callable

from PySide6.QtCore import QEventLoop, QTimer

from core import paths
from modes.web.webview_integration import WebViewBase

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"
WEBVIEW2_AVAILABLE = False

if IS_WINDOWS:
    try:
        from webview2.microsoft.web.webview2.core import (  # type: ignore[import-not-found]
            CoreWebView2ControllerWindowReference,
            CoreWebView2Environment,
        )
        WEBVIEW2_AVAILABLE = True
    except ImportError as exc:
        log.info("WebView2 projection is unavailable: %s", exc)
    except Exception as exc:
        log.warning("Could not load the WebView2 projection: %s", exc)


class WebView(WebViewBase):
    """One native WebView2 controller, parented to HALCYON's QML window."""

    # One WebView2 environment/profile for all HALCYON tabs.  Creating an
    # environment per tab races the profile lock and creates needless browser
    # processes.
    _environment = None

    def __init__(
        self,
        parent_hwnd: int,
        initial_url: str = "about:blank",
        on_title_changed: Callable[[str], None] | None = None,
        on_url_changed: Callable[[str], None] | None = None,
        on_loading_changed: Callable[[bool], None] | None = None,
        on_navigation_completed: Callable[[bool], None] | None = None,
        on_init_error: Callable[[str], None] | None = None,
    ) -> None:
        self._hwnd = int(parent_hwnd)
        self._initial_url = initial_url
        self._on_title_changed_cb = on_title_changed
        self._on_url_changed_cb = on_url_changed
        self._on_loading_changed_cb = on_loading_changed
        self._on_navigation_completed_cb = on_navigation_completed
        self._on_init_error_cb = on_init_error
        self._controller = None
        self._webview = None
        self._initialized = False
        self._closed = False
        self._bounds = (0, 0, 0, 0)
        self._visible = False
        self._event_tokens: list[tuple[object, str, object]] = []

        if not IS_WINDOWS or not WEBVIEW2_AVAILABLE or not self._hwnd:
            return
        self._run_initialization()

    def _run_initialization(self) -> None:
        """Run WinRT initialisation on Qt's GUI thread, pumping the message queue.

        Qt owns the GUI thread and its COM apartment.  We deliberately do not
        move this work to a worker thread: WebView2 controllers must belong to
        their parent window's UI thread.

        WebView2's async methods only complete while the GUI thread's message
        pump is running.  Driving them with ``asyncio.run()`` freezes the app:
        asyncio's Windows proactor loop never pumps the GUI thread's message
        queue, so the completion is never delivered and the thread deadlocks
        (the classic WebView2 hang).  We instead drive each async operation
        with a nested :class:`QEventLoop`, which keeps Qt — and therefore the
        Windows message pump — running until the operation reports done.
        """
        try:
            try:
                self._initialize_controller()
            except FileNotFoundError:
                raise
            except OSError as exc:
                # A stale QQuickWindow HWND commonly surfaces as
                # ERROR_INVALID_WINDOW_HANDLE from WebView2.  The host already
                # re-queries/validates HWNDs before constructing us, but the
                # handle can still race destruction.  Drop any partially-created
                # controller and retry once with a new environment so a poisoned
                # cached environment does not make the next attempt fail the
                # same way.  If the HWND is still bad, the outer OSError handler
                # reports the failure and the host will retry on a later sync.
                log.warning(
                    "WebView2 controller creation failed for HWND %s; retrying with a fresh environment: %s",
                    self._hwnd,
                    exc,
                )
                self._release_controller()
                WebView._environment = None
                self._initialize_controller()
        except FileNotFoundError:
            log.error("WebView2 Runtime is not installed.")
            self._report_init_error("WebView2 Runtime is not installed. Install the Microsoft Edge WebView2 Evergreen Runtime.")
        except TimeoutError as exc:
            log.error("WebView2 initialisation timed out: %s", exc)
            self._report_init_error(str(exc))
        except OSError as exc:
            log.exception("WebView2 controller initialisation failed for HWND %s: %s", self._hwnd, exc)
            self._report_init_error(f"WebView2 could not start for the current HALCYON window handle: {exc}")
        except Exception as exc:
            log.exception("WebView2 controller initialisation failed: %s", exc)
            self._report_init_error(f"WebView2 could not start: {exc}")

    @classmethod
    def _ensure_environment(cls):
        if cls._environment is None:
            data_dir = paths.data_dir() / "webview2" / "profile"
            data_dir.mkdir(parents=True, exist_ok=True)
            # This is the WinRT API, not the similarly named .NET API:
            # create_async() has *zero* parameters.  A custom data folder
            # belongs to create_with_options_async().
            cls._environment = cls._await_result(
                CoreWebView2Environment.create_with_options_async("", str(data_dir), None)
            )
        return cls._environment

    def _initialize_controller(self) -> None:
        environment = self._ensure_environment()
        parent = CoreWebView2ControllerWindowReference.create_from_window_handle(self._hwnd)
        self._controller = self._await_result(environment.create_core_webview2_controller_async(parent))
        self._webview = self._controller.core_webview2
        self._controller.default_background_color = (0xFF, 0x0E, 0x11, 0x18)
        self._controller.bounds = self._bounds
        self._controller.is_visible = self._visible
        self._install_events()
        self._initialized = True
        if self._initial_url and self._initial_url != "about:blank":
            self.navigate(self._initial_url)
        else:
            self.navigate_to_blank()
        log.info("WebView2 controller created for HALCYON window %s", self._hwnd)

    def _release_controller(self) -> None:
        for source, remove_name, token in self._event_tokens:
            try:
                getattr(source, remove_name)(token)
            except Exception:
                pass
        self._event_tokens.clear()
        if self._controller:
            try:
                self._controller.close()
            except Exception:
                pass
        self._controller = self._webview = None
        self._initialized = False

    def _report_init_error(self, message: str) -> None:
        """Surface an initialisation failure so the UI can show it.

        ``is_ready`` stays False, which hides the native browser and reveals the
        QML fallback message.  Delivering the failure text here (instead of only
        logging it) is what lets that fallback say *why* instead of the generic
        "runtime detected" line.
        """
        if self._on_init_error_cb:
            try:
                self._on_init_error_cb(message)
            except Exception:
                log.exception("error callback raised while reporting WebView2 init failure")

    @staticmethod
    def _await_result(async_op):
        """Wait for a WinRT ``IAsyncOperation`` while keeping the UI alive.

        PyWinRT delivers a WebView2 async completion through the GUI thread's
        message pump (see :meth:`_run_initialization`).  We attach a completion
        handler that quits a nested :class:`QEventLoop`, run that loop so Qt
        keeps pumping Windows messages, then fetch the operation's result.
        ``async_op`` exposes the standard ``completed`` / ``get_results()`` /
        ``status`` surface of ``IAsyncOperation``.

        A watchdog timer guarantees the nested loop cannot hang the app if a
        WebView2 operation never reports back (the class of failure that froze
        the app before).  If it fires, ``get_results()`` is not called on an
        unfinished operation; we raise instead so the caller surfaces an error
        rather than deadlocking.
        """
        loop = QEventLoop()
        state = {"done": False}
        #: How long to keep pumping before giving up on a WebView2 operation.
        timeout_ms = 30000

        def _done(_op, _result) -> None:
            state["done"] = True
            loop.quit()

        async_op.completed = _done

        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(timeout_ms)

        try:
            loop.exec_()
        finally:
            watchdog.stop()

        if not state["done"]:
            raise TimeoutError("WebView2 initialisation timed out (runtime not responding)")
        return async_op.get_results()

    def _install_events(self) -> None:
        if not self._webview:
            return
        # PyWinRT events use add_* methods; assigning callbacks to event names
        # silently does not subscribe in this projection.
        for add_name, remove_name, callback in (
            ("add_navigation_started", "remove_navigation_started", self._on_navigation_started),
            ("add_navigation_completed", "remove_navigation_completed", self._on_navigation_completed),
            ("add_source_changed", "remove_source_changed", self._on_source_changed),
            ("add_document_title_changed", "remove_document_title_changed", self._on_document_title_changed),
        ):
            try:
                token = getattr(self._webview, add_name)(callback)
                self._event_tokens.append((self._webview, remove_name, token))
            except Exception as exc:
                log.warning("Could not subscribe to WebView2 event %s: %s", add_name, exc)

    def set_bounds(self, x: int, y: int, width: int, height: int, visible: bool) -> None:
        self._bounds = (max(0, x), max(0, y), max(0, width), max(0, height))
        self._visible = bool(visible and width > 0 and height > 0)
        if self._controller:
            try:
                self._controller.bounds = self._bounds
                self._controller.is_visible = self._visible
            except Exception as exc:
                log.warning("Could not update WebView2 bounds: %s", exc)

    def set_visible(self, visible: bool) -> None:
        self.set_bounds(*self._bounds, visible)

    def _on_navigation_started(self, _sender, _args) -> None:
        if self._on_loading_changed_cb:
            self._on_loading_changed_cb(True)

    def _on_navigation_completed(self, _sender, args) -> None:
        if self._on_loading_changed_cb:
            self._on_loading_changed_cb(False)
        if self._on_navigation_completed_cb:
            self._on_navigation_completed_cb(bool(args.is_success))

    def _on_source_changed(self, sender, _args) -> None:
        if self._on_url_changed_cb:
            self._on_url_changed_cb(str(sender.source))

    def _on_document_title_changed(self, sender, _args) -> None:
        if self._on_title_changed_cb:
            self._on_title_changed_cb(str(sender.document_title))

    def navigate(self, url: str) -> None:
        if not url:
            return
        self._initial_url = url
        if not self._initialized or not self._webview:
            return
        try:
            if url == "about:blank":
                self.navigate_to_blank()
            else:
                self._webview.navigate(url)
        except Exception as exc:
            log.error("WebView2 navigation failed for %s: %s", url, exc)

    def navigate_to_blank(self) -> None:
        if self._initialized and self._webview:
            self._webview.navigate_to_string("<html><body style='margin:0;background:#0E1118'></body></html>")

    def go_back(self) -> None:
        if self._webview and self._webview.can_go_back:
            self._webview.go_back()

    def go_forward(self) -> None:
        if self._webview and self._webview.can_go_forward:
            self._webview.go_forward()

    def reload(self) -> None:
        if self._webview:
            self._webview.reload()

    def stop(self) -> None:
        if self._webview:
            self._webview.stop()

    @property
    def can_go_back(self) -> bool:
        return bool(self._webview and self._webview.can_go_back)

    @property
    def can_go_forward(self) -> bool:
        return bool(self._webview and self._webview.can_go_forward)

    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def current_url(self) -> str:
        return str(self._webview.source) if self._webview else self._initial_url

    @property
    def current_title(self) -> str:
        return str(self._webview.document_title) if self._webview else ""

    def update_bounds(self, x: int, y: int, width: int, height: int) -> None:
        self.set_bounds(x, y, width, height, self._visible)

    def close(self) -> None:
        self._closed = True
        self._release_controller()
