"""Unit tests for Web mode browser context and tab manager (§P3.1, §P3.4)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from modes.web.browser import BOOKMARKS_URL, BrowserContext


class FakeHost(QObject):
    """A no-Windows WebViewHost stand-in for BrowserContext wiring tests."""

    urlChanged = Signal(str)
    titleChanged = Signal(str)
    loadingChanged = Signal(bool)
    historyChanged = Signal(bool, bool)
    newWindowRequested = Signal(str)
    errorOccurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.isReady = False
        self.parent_hwnd = 0
        self.navigated: list[str] = []
        self.visible_values: list[bool] = []
        self.bounds: list[tuple[int, int, int, int]] = []
        self.back_calls = 0
        self.forward_calls = 0
        self.reload_calls = 0
        self.stop_calls = 0
        self.errorMessage = ""

    def init_controller(self, hwnd, _environment):
        self.parent_hwnd = int(hwnd)
        self.isReady = True
        return True

    def navigate(self, url):
        self.navigated.append(url)

    def set_visible(self, value):
        self.visible_values.append(bool(value))

    def set_bounds(self, x, y, width, height):
        self.bounds.append((x, y, width, height))

    def go_back(self):
        self.back_calls += 1

    def go_forward(self):
        self.forward_calls += 1

    def reload(self):
        self.reload_calls += 1

    def stop(self):
        self.stop_calls += 1

    def release_controller(self):
        self.isReady = False

    def close(self):
        self.isReady = False


class FakeWindow(QObject):
    def winId(self):  # noqa: N802 - mirrors QWindow's Qt API
        return 4242


def test_browser_context_starts_no_tabs_creates_on_navigate():
    """No tabs on entry; typing/navigating creates first tab (§P3.1)."""
    browser = BrowserContext()
    assert browser.tabCount == 0
    assert browser.activeTabIndex == -1

    browser.navigateActive("example.com")
    assert browser.tabCount == 1
    assert browser.activeTabIndex == 0
    assert browser.activeTab["url"] == "https://example.com"


def test_browser_context_max_15_tabs_cap_and_message():
    """Max 15 tabs; 16th attempt blocked and displays in-chrome message (§P3.1, §P3.4)."""
    browser = BrowserContext()

    for idx in range(15):
        ok = browser.addTab(f"https://example.com/{idx}")
        assert ok is True

    assert browser.tabCount == 15
    assert browser.isAtMaxTabs is True
    assert browser.tabLimitMessageVisible is False

    # Try to open 16th tab
    ok_16 = browser.addTab("https://example.com/16")
    assert ok_16 is False
    assert browser.tabCount == 15
    assert browser.tabLimitMessageVisible is True

    # Closing a tab should clear the limit state
    browser.closeTab(14)
    assert browser.tabCount == 14
    assert browser.isAtMaxTabs is False
    assert browser.tabLimitMessageVisible is False


def test_browser_context_navigate_home():
    """Home button navigates to site homepage or Google on blank tab (§P3.4)."""
    browser = BrowserContext()
    browser.navigateHome()
    assert browser.tabCount == 1
    assert browser.activeTab["url"] == "https://www.google.com"

    # Now navigate to a deep page on wikipedia
    browser.navigateActive("https://en.wikipedia.org/wiki/Halcyon")
    browser.navigateHome()
    assert browser.activeTab["url"] == "https://en.wikipedia.org"


def test_browser_context_popup_routing():
    """Popup/new-window requests must route to new tabs (§P3.4)."""
    browser = BrowserContext()
    browser.onPopupRequested("https://www.example.org/popup")
    assert browser.tabCount == 1
    assert browser.activeTab["url"] == "https://www.example.org/popup"


def test_browser_context_reset_for_restart():
    """Tabs must not be saved across restart (§P3.1)."""
    browser = BrowserContext()
    browser.addTab("https://example.com")
    assert browser.tabCount == 1
    browser.reset_for_restart()
    assert browser.tabCount == 0
    assert browser.activeTabIndex == -1


def test_external_tab_is_wired_to_a_host_and_native_viewport():
    """Address navigation must drive a real per-tab host, not only a dict."""
    hosts: list[FakeHost] = []

    def make_host(parent=None):
        host = FakeHost(parent)
        hosts.append(host)
        return host

    browser = BrowserContext(
        host_factory=make_host,
        runtime_check=lambda: (True, "OK"),
        environment_getter=lambda: object(),
    )
    browser.attachToWindow(FakeWindow())
    browser.setStageActive(True)
    browser.setViewport(10, 54, 900, 620)
    browser.navigateActive("example.com")

    assert len(hosts) == 1
    host = hosts[0]
    assert host.parent_hwnd == 4242
    assert host.navigated[-1] == "https://example.com"
    assert host.bounds[-1] == (10, 54, 900, 620)
    assert host.visible_values[-1] is True

    host.titleChanged.emit("Example title")
    host.historyChanged.emit(True, False)
    assert browser.activeTab["title"] == "Example title"
    assert browser.windowTitle == "Example title"
    assert browser.activeTab["canGoBack"] is True
    assert browser.activeTab["canGoForward"] is False

    browser.goBack()
    assert host.back_calls == 1


def test_internal_bookmarks_tab_hides_native_page_and_does_not_create_host():
    """Bookmarks manager is a Halcyon page, never a navigated WebView2 URL."""
    hosts: list[FakeHost] = []

    def make_host(parent=None):
        host = FakeHost(parent)
        hosts.append(host)
        return host

    browser = BrowserContext(host_factory=make_host)
    browser.navigateActive("example.com")
    assert len(hosts) == 1
    browser.openBookmarksManager()

    assert browser.activeTab["url"] == BOOKMARKS_URL
    assert browser.activeTab["internal"] is True
    assert len(hosts) == 1
    assert hosts[0].visible_values[-1] is False


def test_popup_requests_create_a_normal_halcyon_tab_with_its_own_host():
    hosts: list[FakeHost] = []

    def make_host(parent=None):
        host = FakeHost(parent)
        hosts.append(host)
        return host

    browser = BrowserContext(host_factory=make_host)
    browser.navigateActive("https://example.com")
    browser.onPopupRequested("https://example.org/popup")

    assert browser.tabCount == 2
    assert browser.activeTab["url"] == "https://example.org/popup"
    assert len(hosts) == 2
