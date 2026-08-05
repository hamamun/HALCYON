"""Tab model and QML-facing controller for Halcyon's Web mode.

This is the missing join between browser chrome and ``WebViewHost``: every
external tab owns one native controller, while this object owns visibility,
geometry, history state, popup routing and bookmark state.  QML only receives
plain QVariant maps; it never has to know about pythonnet or HWNDs.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from modes.web import webview2_runtime
from modes.web.bookmarks import BookmarksStore
from modes.web.webview2_host import WebViewHost

logger = logging.getLogger("modes.web.browser")

MAX_TABS = 15
BOOKMARKS_URL = "halcyon://bookmarks"

# Popup burst protection — prevents ad-heavy sites (e.g. bilibili.tv) from
# spawning 10+ tabs in one click and crashing WebView2 controller creation.
#
# Two tiers: popups from the same domain as the active tab (legitimate video
# pages, "watch next" links) get a generous allowance, while cross-domain
# ad popups are throttled hard (1 per burst window).
POPUP_BURST_WINDOW_S = 3.0
POPUP_MAX_PER_BURST = 1
POPUP_MIN_INTERVAL_S = 0.8
POPUP_SAME_DOMAIN_MAX_PER_BURST = 4
POPUP_SAME_DOMAIN_MIN_INTERVAL_S = 0.3
POPUP_BLOCKED_MESSAGE_DURATION_MS = 4000


@dataclass
class _BrowserTab:
    id: str
    url: str = ""
    title: str = "New Tab"
    loading: bool = False
    can_go_back: bool = False
    can_go_forward: bool = False
    host: WebViewHost | None = None

    @property
    def internal(self) -> bool:
        return self.url == BOOKMARKS_URL

    def as_map(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title or self.url or "New Tab",
            "url": self.url,
            "loading": self.loading,
            "canGoBack": self.can_go_back,
            "canGoForward": self.can_go_forward,
            "internal": self.internal,
        }


class BrowserContext(QObject):
    """The complete browser state exposed as ``modeContext_web``.

    ``host_factory`` and ``runtime_check`` are injectable for deterministic
    non-Windows tests.  Production uses the direct WebView2 host and the real
    registry/CLR probe.
    """

    tabsChanged = Signal()
    activeTabIndexChanged = Signal()
    activeTabChanged = Signal()
    tabLimitMessageVisibleChanged = Signal()
    popupBlockedMessageVisibleChanged = Signal()
    popupBlockedCountChanged = Signal()
    bookmarksChanged = Signal()
    runtimeAvailableChanged = Signal()
    runtimeMessageChanged = Signal()
    runtimeCheckedChanged = Signal()
    addressFocusRequested = Signal()
    windowTitleChanged = Signal()

    def __init__(
        self,
        bookmarks: BookmarksStore | None = None,
        parent: QObject | None = None,
        *,
        host_factory: Callable[..., WebViewHost] | None = None,
        runtime_check: Callable[[], tuple[bool, str]] | None = None,
        environment_getter: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._tabs: list[_BrowserTab] = []
        self._active_index = -1
        self._tab_limit_message_visible = False
        self._bookmarks = bookmarks or BookmarksStore(parent=self)
        if self._bookmarks.parent() is None:
            self._bookmarks.setParent(self)
        self._bookmarks.bookmarksChanged.connect(self._on_bookmarks_changed)

        self._host_factory = host_factory or WebViewHost
        self._runtime_check = runtime_check or webview2_runtime.check_webview2_available
        self._environment_getter = environment_getter or webview2_runtime.get_shared_environment
        self._runtime_checked = False
        self._runtime_available = False
        self._runtime_message = "Starting WebView2…"

        self._host_window: QObject | None = None
        self._parent_hwnd = 0
        self._attach_attempts = 0
        self._stage_active = False
        # Physical pixels relative to the QQuickWindow client area.  QML passes
        # device-pixel-ratio-adjusted values, so WebView2 receives the same
        # coordinate system as Win32 Bounds.
        self._viewport = (0, 0, 0, 0)

        self._limit_timer = QTimer(self)
        self._limit_timer.setSingleShot(True)
        self._limit_timer.setInterval(3500)
        self._limit_timer.timeout.connect(self.dismissTabLimitMessage)

        # Popup burst protection state — throttles NewWindowRequested storms.
        self._popup_times: list[float] = []
        self._last_popup_time: float = 0.0
        self._popup_blocked_count: int = 0
        self._popup_blocked_visible: bool = False
        self._popup_blocked_timer = QTimer(self)
        self._popup_blocked_timer.setSingleShot(True)
        self._popup_blocked_timer.setInterval(POPUP_BLOCKED_MESSAGE_DURATION_MS)
        self._popup_blocked_timer.timeout.connect(self.dismissPopupBlockedMessage)

    # ---------------------------------------------------------------- QML data
    @Property(int, notify=tabsChanged)
    def tabCount(self) -> int:  # noqa: N802 - QML API
        return len(self._tabs)

    @Property(int, notify=activeTabIndexChanged)
    def activeTabIndex(self) -> int:  # noqa: N802 - QML API
        return self._active_index

    @Property("QVariantMap", notify=activeTabChanged)
    def activeTab(self) -> dict[str, Any]:  # noqa: N802 - QML API
        tab = self._active_tab()
        if tab is not None:
            return tab.as_map()
        return {
            "id": "",
            "title": "",
            "url": "",
            "loading": False,
            "canGoBack": False,
            "canGoForward": False,
            "internal": False,
        }

    @Property(str, notify=windowTitleChanged)
    def windowTitle(self) -> str:  # noqa: N802 - QML API
        return self.window_title()

    def window_title(self) -> str:
        """Title contribution consumed by the generic AppController protocol."""
        tab = self._active_tab()
        if tab is None:
            return ""
        return tab.title or tab.url or "New Tab"

    @Property("QVariantList", notify=tabsChanged)
    def tabs(self) -> list[dict[str, Any]]:
        return [tab.as_map() for tab in self._tabs]

    @Property(bool, notify=tabsChanged)
    def isAtMaxTabs(self) -> bool:  # noqa: N802 - QML API
        return len(self._tabs) >= MAX_TABS

    @Property(bool, notify=tabLimitMessageVisibleChanged)
    def tabLimitMessageVisible(self) -> bool:  # noqa: N802 - QML API
        return self._tab_limit_message_visible

    @Property(int, notify=popupBlockedCountChanged)
    def popupBlockedCount(self) -> int:  # noqa: N802 - QML API
        return self._popup_blocked_count

    @Property(bool, notify=popupBlockedMessageVisibleChanged)
    def popupBlockedMessageVisible(self) -> bool:  # noqa: N802 - QML API
        return self._popup_blocked_visible

    @Property(QObject, notify=bookmarksChanged)
    def bookmarks(self) -> BookmarksStore:
        return self._bookmarks

    @Property("QVariantList", notify=bookmarksChanged)
    def bookmarkItems(self) -> list[dict[str, Any]]:  # noqa: N802 - QML API
        return self._bookmarks.getAll()

    @Property(bool, notify=activeTabChanged)
    def activeTabBookmarked(self) -> bool:  # noqa: N802 - QML API
        tab = self._active_tab()
        return bool(tab and tab.url and not tab.internal and self._bookmarks.isBookmarked(tab.url))

    @Property(bool, notify=runtimeAvailableChanged)
    def runtimeAvailable(self) -> bool:  # noqa: N802 - QML API
        return self._runtime_available

    @Property(bool, notify=runtimeCheckedChanged)
    def runtimeChecked(self) -> bool:  # noqa: N802 - QML API
        return self._runtime_checked

    @Property(str, notify=runtimeMessageChanged)
    def runtimeMessage(self) -> str:  # noqa: N802 - QML API
        return self._runtime_message

    # -------------------------------------------------------- stage attachment
    @Slot(QObject)
    def attachToWindow(self, window: QObject | None) -> None:  # noqa: N802 - QML API
        """Attach controllers to the main QQuickWindow once it owns an HWND."""
        if window is None:
            return

        changed_window = window is not self._host_window
        if changed_window:
            self._host_window = window
            self._parent_hwnd = 0
            self._attach_attempts = 0
            try:
                window.destroyed.connect(self._on_host_window_destroyed)
            except Exception:
                pass
            # A controller cannot be rebound to another parent HWND.  Preserve
            # URLs/tabs but release any old native children before retrying.
            for tab in self._tabs:
                if tab.host is not None:
                    tab.host.release_controller()

        self.ensureRuntime()
        self._attach_when_window_is_ready()

    @Slot(int, int, int, int)
    def setViewport(self, x: int, y: int, width: int, height: int) -> None:  # noqa: N802
        """Receive the page rectangle in physical pixels from WebStage.qml."""
        rect = (int(x), int(y), max(0, int(width)), max(0, int(height)))
        if rect != self._viewport:
            self._viewport = rect
            self._sync_hosts()

    @Slot(bool)
    def setStageActive(self, active: bool) -> None:  # noqa: N802 - QML API
        active = bool(active)
        if active != self._stage_active:
            self._stage_active = active
            self._sync_hosts()

    @Slot()
    def detachStage(self) -> None:  # noqa: N802 - QML API
        """Hide every native child before a non-Web stage becomes visible."""
        self.setStageActive(False)

    @Slot()
    def ensureRuntime(self) -> None:  # noqa: N802 - QML API
        """Run the actual WebView2 bridge probe once per application session."""
        if self._runtime_checked:
            return
        try:
            available, message = self._runtime_check()
        except Exception as exc:
            logger.warning("WebView2 availability check raised unexpectedly: %s", exc)
            available, message = False, webview2_runtime.get_stage_error_message()

        self._runtime_checked = True
        self._set_runtime_available(bool(available), str(message or ""))
        self.runtimeCheckedChanged.emit()
        if self._runtime_available:
            self._attach_when_window_is_ready()

    def _attach_when_window_is_ready(self) -> None:
        if not self._runtime_available or self._host_window is None:
            return
        hwnd = self._window_hwnd(self._host_window)
        if hwnd <= 0:
            if self._attach_attempts < 20:
                self._attach_attempts += 1
                QTimer.singleShot(50, self._attach_when_window_is_ready)
            return

        self._parent_hwnd = hwnd
        self._attach_attempts = 0
        self._ensure_controllers()
        self._sync_hosts()

    @staticmethod
    def _window_hwnd(window: QObject) -> int:
        try:
            win_id = getattr(window, "winId")
            return int(win_id() if callable(win_id) else win_id)
        except Exception:
            return 0

    def _on_host_window_destroyed(self, *_args: Any) -> None:
        self._stage_active = False
        self._parent_hwnd = 0
        self._host_window = None
        for tab in self._tabs:
            if tab.host is not None:
                tab.host.set_visible(False)

    # --------------------------------------------------------------- tab model
    @Slot(str, result=bool)
    def addTab(self, url: str = "") -> bool:  # noqa: N802 - QML API
        """Add an empty, internal, or ordinary browser tab (maximum 15)."""
        if len(self._tabs) >= MAX_TABS:
            self._show_tab_limit_message()
            return False

        raw = (url or "").strip()
        if raw == BOOKMARKS_URL:
            tab = _BrowserTab(id=uuid.uuid4().hex, url=BOOKMARKS_URL, title="Bookmarks Manager")
        elif raw:
            resolved = webview2_runtime.resolve_url_or_search(raw)
            tab = _BrowserTab(id=uuid.uuid4().hex, url=resolved, title=resolved)
        else:
            tab = _BrowserTab(id=uuid.uuid4().hex)

        self._tabs.append(tab)
        self._set_active_index(len(self._tabs) - 1, emit_tabs=True)
        if tab.url and not tab.internal:
            self._navigate_tab(tab, tab.url, emit=False)
        else:
            self._sync_hosts()
            self.addressFocusRequested.emit()
        return True

    @Slot(int, result=bool)
    def closeTab(self, index: int) -> bool:  # noqa: N802 - QML API
        if not 0 <= index < len(self._tabs):
            return False

        removed = self._tabs.pop(index)
        if removed.host is not None:
            removed.host.close()

        if not self._tabs:
            next_index = -1
        elif index < self._active_index:
            next_index = self._active_index - 1
        elif index == self._active_index:
            next_index = min(index, len(self._tabs) - 1)
        else:
            next_index = self._active_index

        if len(self._tabs) < MAX_TABS:
            self.dismissTabLimitMessage()
        self._set_active_index(next_index, emit_tabs=True)
        self._sync_hosts()
        return True

    @Slot(int)
    def setActiveTab(self, index: int) -> None:  # noqa: N802 - QML API
        if 0 <= index < len(self._tabs) and index != self._active_index:
            self._set_active_index(index)
            self._sync_hosts()

    @Slot(str)
    def navigateActive(self, url_or_search: str) -> None:  # noqa: N802 - QML API
        raw = (url_or_search or "").strip()
        if raw == BOOKMARKS_URL:
            self.openBookmarksManager()
            return
        resolved = webview2_runtime.resolve_url_or_search(raw)
        tab = self._active_tab()
        if tab is None:
            self.addTab(resolved)
            return
        self._navigate_tab(tab, resolved)

    @Slot()
    def navigateHome(self) -> None:  # noqa: N802 - QML API
        tab = self._active_tab()
        if tab is None or tab.internal or not tab.url:
            self.navigateActive("https://www.google.com")
            return
        try:
            parts = urllib.parse.urlsplit(tab.url)
            home = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
        except Exception:
            home = ""
        self.navigateActive(home or "https://www.google.com")

    @Slot()
    def goBack(self) -> None:  # noqa: N802 - QML API
        tab = self._active_tab()
        if tab is not None and tab.host is not None:
            tab.host.go_back()

    @Slot()
    def goForward(self) -> None:  # noqa: N802 - QML API
        tab = self._active_tab()
        if tab is not None and tab.host is not None:
            tab.host.go_forward()

    @Slot()
    def reloadOrStop(self) -> None:  # noqa: N802 - QML API
        tab = self._active_tab()
        if tab is None or tab.host is None:
            return
        if tab.loading:
            tab.host.stop()
        else:
            tab.host.reload()

    @Slot(str)
    def onPopupRequested(self, url: str) -> None:  # noqa: N802 - QML API
        # Burst protection for ad-heavy sites like bilibili.tv:
        # A single click can spawn 10+ NewWindowRequested events.  Creating a
        # controller per request overloads WebView2 and ends in a blank stage,
        # so popups are rate-limited with two tiers: same-domain video pages
        # get a generous allowance, cross-domain ad popups are throttled hard.
        now = time.monotonic()
        # prune old timestamps outside the burst window
        self._popup_times = [t for t in self._popup_times if now - t < POPUP_BURST_WINDOW_S]

        raw = (url or "").strip()
        if not raw or raw.lower().startswith("about:"):
            self._handle_blocked_popup(f"blank popup blocked: {url!r}")
            return

        popup_domain = self._extract_domain(raw)
        active = self._active_tab()
        active_domain = self._extract_domain(active.url if active else "")
        same_domain = bool(active_domain and popup_domain) and self._is_same_domain_or_subdomain(
            active_domain, popup_domain
        )

        if same_domain:
            burst_max = POPUP_SAME_DOMAIN_MAX_PER_BURST
            min_interval = POPUP_SAME_DOMAIN_MIN_INTERVAL_S
            kind = "same-domain"
        else:
            burst_max = POPUP_MAX_PER_BURST
            min_interval = POPUP_MIN_INTERVAL_S
            kind = "cross-domain"

        # too fast since the last allowed popup?
        if self._last_popup_time and (now - self._last_popup_time) < min_interval and len(self._popup_times) >= 1:
            # Same-domain popups may arrive back-to-back until the per-burst
            # allowance is exhausted; cross-domain ones are blocked as spam.
            if not same_domain or len(self._popup_times) >= burst_max:
                self._handle_blocked_popup(f"popup throttled too fast ({kind}): {url}")
                return

        if len(self._popup_times) >= burst_max:
            self._handle_blocked_popup(
                f"popup burst blocked ({kind}, {len(self._popup_times) + 1} in {POPUP_BURST_WINDOW_S}s): {url}",
            )
            return

        self._popup_times.append(now)
        self._last_popup_time = now

        # WebViewHost already marked the .NET request as handled.
        # We must defer creating the tab to break a native WebView2 COM deadlock:
        # Edge fires NewWindowRequested and pauses waiting for us to return. If we
        # synchronously create the controller here, we wait for Edge while Edge
        # waits for us, resulting in a TimeoutError. Deferring lets Edge resume.
        QTimer.singleShot(1, lambda: self.addTab(url))

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Return the bare host of a URL: lowercase, no port, no 'www.' prefix.

        Used to classify popups as same-domain (video pages) vs cross-domain
        (ad networks) without being confused by scheme, port or subdomain.
        """
        raw = (url or "").strip()
        if not raw:
            return ""
        try:
            netloc = urllib.parse.urlsplit(raw).netloc
            if not netloc:
                netloc = urllib.parse.urlsplit("//" + raw).netloc
        except Exception:
            netloc = ""
        host = (netloc or "").split("@")[-1]  # strip any userinfo
        if ":" in host:  # strip port (IPv6 literals are an accepted loss)
            host = host.split(":", 1)[0]
        host = host.lower().strip(".")
        if host.startswith("www."):
            host = host[4:]
        return host

    @staticmethod
    def _is_same_domain_or_subdomain(a: str, b: str) -> bool:
        """True when both domains are equal or one is a subdomain of the other."""
        a = (a or "").lower().strip(".")
        b = (b or "").lower().strip(".")
        if not a or not b:
            return False
        if a == b:
            return True
        if b.endswith("." + a) or a.endswith("." + b):
            return True
        return False

    @Slot()
    def openBookmarksManager(self) -> None:  # noqa: N802 - QML API
        for index, tab in enumerate(self._tabs):
            if tab.internal:
                self.setActiveTab(index)
                return
        self.addTab(BOOKMARKS_URL)

    @Slot()
    def dismissTabLimitMessage(self) -> None:  # noqa: N802 - QML API
        self._limit_timer.stop()
        if self._tab_limit_message_visible:
            self._tab_limit_message_visible = False
            self.tabLimitMessageVisibleChanged.emit()

    @Slot()
    def dismissPopupBlockedMessage(self) -> None:  # noqa: N802 - QML API
        self._popup_blocked_timer.stop()
        if self._popup_blocked_visible:
            self._popup_blocked_visible = False
            self.popupBlockedMessageVisibleChanged.emit()

    def _show_tab_limit_message(self) -> None:
        if not self._tab_limit_message_visible:
            self._tab_limit_message_visible = True
            self.tabLimitMessageVisibleChanged.emit()
        self._limit_timer.start()
        logger.info("Web tab cap (%d) reached", MAX_TABS)

    def _handle_blocked_popup(self, log_msg: str) -> None:
        """Record a throttled popup: bump counter, surface toast, restart timer.

        Blocked popups do NOT enter ``_popup_times``, so a storm can never
        extend the per-burst allowance on its own.
        """
        self._popup_blocked_count += 1
        self.popupBlockedCountChanged.emit()
        self._show_popup_blocked_message()
        logger.info("Popup blocked (%d total): %s", self._popup_blocked_count, log_msg)

    def _show_popup_blocked_message(self) -> None:
        if not self._popup_blocked_visible:
            self._popup_blocked_visible = True
            self.popupBlockedMessageVisibleChanged.emit()
        self._popup_blocked_timer.start()

    def _set_active_index(self, index: int, *, emit_tabs: bool = False) -> None:
        changed = index != self._active_index
        self._active_index = index
        if emit_tabs:
            self.tabsChanged.emit()
        if changed:
            self.activeTabIndexChanged.emit()
        # A changed tab snapshot must be published both for a new tab and after
        # a close where the numeric index happens to remain the same.
        self.activeTabChanged.emit()
        self.windowTitleChanged.emit()

    def _active_tab(self) -> _BrowserTab | None:
        if 0 <= self._active_index < len(self._tabs):
            return self._tabs[self._active_index]
        return None

    def _tab_by_id(self, tab_id: str) -> _BrowserTab | None:
        return next((tab for tab in self._tabs if tab.id == tab_id), None)

    # -------------------------------------------------------------- WebView2 IO
    def _navigate_tab(self, tab: _BrowserTab, resolved: str, *, emit: bool = True) -> None:
        tab.url = resolved
        tab.title = resolved
        tab.loading = False
        tab.can_go_back = False
        tab.can_go_forward = False
        host = self._ensure_tab_host(tab)
        if host is not None:
            host.navigate(resolved)
        if emit:
            self._emit_tab_change(tab)
        self._sync_hosts()

    def _ensure_tab_host(self, tab: _BrowserTab) -> WebViewHost | None:
        if tab.internal:
            return None
        if tab.host is None:
            try:
                tab.host = self._host_factory(parent=self)
            except TypeError:
                # Tiny fake hosts in unit tests may not accept a QObject parent.
                tab.host = self._host_factory()  # type: ignore[call-arg]
                if tab.host.parent() is None:
                    tab.host.setParent(self)
            self._connect_host(tab.id, tab.host)
        if self._runtime_available and self._parent_hwnd > 0 and not tab.host.isReady:
            self._init_host(tab)
        return tab.host

    def _ensure_controllers(self) -> None:
        for tab in self._tabs:
            if tab.internal:
                continue
            host = self._ensure_tab_host(tab)
            if host is not None:
                self._init_host(tab)

    def _init_host(self, tab: _BrowserTab) -> bool:
        host = tab.host
        if host is None or self._parent_hwnd <= 0:
            return False
        if host.isReady and host.parent_hwnd == self._parent_hwnd:
            return True
        if getattr(host, "is_initializing", False):
            return True
        environment = self._environment_getter()
        if environment is None:
            self._set_runtime_available(False, webview2_runtime.get_stage_error_message())
            return False
        ok = host.init_controller(self._parent_hwnd, environment)
        if not ok:
            self._set_runtime_available(False, host.errorMessage or webview2_runtime.get_stage_error_message())
            return False
        # A host created before the stage acquired an HWND already holds its
        # URL as pending navigation; init_controller flushes it exactly once.
        # The caller that creates a host after attachment performs navigation
        # immediately after this method returns.
        return True

    def _sync_hosts(self) -> None:
        active = self._active_tab()
        x, y, width, height = self._viewport
        usable = self._stage_active and self._runtime_available and width > 0 and height > 0
        for tab in self._tabs:
            host = tab.host
            if host is None:
                continue
            should_show = bool(usable and tab is active and not tab.internal)
            if should_show:
                if not host.isReady and not getattr(host, "is_initializing", False):
                    self._init_host(tab)
                host.set_bounds(x, y, width, height)
            host.set_visible(should_show and host.isReady)

    def _connect_host(self, tab_id: str, host: WebViewHost) -> None:
        host.urlChanged.connect(lambda url, ident=tab_id: self._on_host_url(ident, url))
        host.titleChanged.connect(lambda title, ident=tab_id: self._on_host_title(ident, title))
        host.loadingChanged.connect(lambda loading, ident=tab_id: self._on_host_loading(ident, loading))
        host.historyChanged.connect(
            lambda back, forward, ident=tab_id: self._on_host_history(ident, back, forward)
        )
        host.newWindowRequested.connect(self.onPopupRequested)
        host.errorOccurred.connect(lambda message, ident=tab_id: self._on_host_error(ident, message))

    def _on_host_url(self, tab_id: str, url: str) -> None:
        tab = self._tab_by_id(tab_id)
        if tab is None:
            return
        tab.url = url
        if not tab.title or tab.title == "New Tab" or tab.title.startswith(("http://", "https://")):
            tab.title = url
        self._emit_tab_change(tab)

    def _on_host_title(self, tab_id: str, title: str) -> None:
        tab = self._tab_by_id(tab_id)
        if tab is None:
            return
        tab.title = title or tab.url or "New Tab"
        self._emit_tab_change(tab)

    def _on_host_loading(self, tab_id: str, loading: bool) -> None:
        tab = self._tab_by_id(tab_id)
        if tab is None:
            return
        tab.loading = bool(loading)
        self._emit_tab_change(tab)

    def _on_host_history(self, tab_id: str, back: bool, forward: bool) -> None:
        tab = self._tab_by_id(tab_id)
        if tab is None:
            return
        tab.can_go_back = bool(back)
        tab.can_go_forward = bool(forward)
        self._emit_tab_change(tab)

    def _on_host_error(self, _tab_id: str, message: str) -> None:
        # A controller failure after a positive registry/CLR probe still needs a
        # user-visible stage, not a black rectangle.  Hiding every child makes
        # the QML fallback immediately visible.
        self._set_runtime_available(False, message or webview2_runtime.get_stage_error_message())
        self._sync_hosts()

    def _emit_tab_change(self, tab: _BrowserTab) -> None:
        self.tabsChanged.emit()
        if tab is self._active_tab():
            self.activeTabChanged.emit()
            self.windowTitleChanged.emit()

    def _set_runtime_available(self, available: bool, message: str) -> None:
        if available != self._runtime_available:
            self._runtime_available = available
            self.runtimeAvailableChanged.emit()
        message = message or ("OK" if available else webview2_runtime.get_stage_error_message())
        if message != self._runtime_message:
            self._runtime_message = message
            self.runtimeMessageChanged.emit()

    # --------------------------------------------------------------- bookmarks
    @staticmethod
    def _bookmark_url(url: str) -> str:
        text = (url or "").strip()
        return webview2_runtime.resolve_url_or_search(text) if text else ""

    @Slot(str, str, result=bool)
    def addBookmark(self, title: str, url: str) -> bool:  # noqa: N802 - QML API
        return self._bookmarks.addBookmark(title, self._bookmark_url(url))

    @Slot(str, str, str, result=bool)
    def updateBookmark(self, old_url: str, title: str, url: str) -> bool:  # noqa: N802
        return self._bookmarks.updateBookmark(old_url, title, self._bookmark_url(url))

    @Slot(str, result=bool)
    def removeBookmark(self, url: str) -> bool:  # noqa: N802 - QML API
        return self._bookmarks.removeBookmark(url)

    @Slot(int, int, result=bool)
    def reorderBookmarks(self, from_index: int, to_index: int) -> bool:  # noqa: N802
        return self._bookmarks.reorder(from_index, to_index)

    def _on_bookmarks_changed(self) -> None:
        self.bookmarksChanged.emit()
        self.activeTabChanged.emit()

    # --------------------------------------------------------------- lifecycle
    def reset_for_restart(self) -> None:
        """Clear session-only tabs; bookmark storage intentionally remains."""
        for tab in self._tabs:
            if tab.host is not None:
                tab.host.close()
        self._tabs.clear()
        self._active_index = -1
        self.dismissTabLimitMessage()
        self.dismissPopupBlockedMessage()
        self._popup_times.clear()
        self._last_popup_time = 0.0
        self._popup_blocked_count = 0
        self.popupBlockedCountChanged.emit()
        self.tabsChanged.emit()
        self.activeTabIndexChanged.emit()
        self.activeTabChanged.emit()
        self.windowTitleChanged.emit()

    def shutdown(self) -> None:
        """Close every native child before Qt destroys the parent window."""
        self.reset_for_restart()
        webview2_runtime.shutdown_pythonnet_com()
