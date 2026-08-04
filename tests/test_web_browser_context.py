"""Unit tests for Web mode browser context and tab manager (§P3.1, §P3.4)."""

from __future__ import annotations

from modes.web.browser import BrowserContext


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
