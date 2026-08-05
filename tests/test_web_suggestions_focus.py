"""Regression test: typing in the address bar must survive the suggestions popup.

The "only one letter typed" bug: the suggestions dropdown is a native window,
and on Windows a Qt.Popup window grabs keyboard focus the moment it is shown —
so the first keystroke opened the dropdown and every later keystroke went
nowhere.  The fix makes the suggestions popup a tooltip-style, non-activating
window and re-secures focus in the address bar whenever the popup becomes
visible (Edge keeps focus in the bar while typing).

These tests instantiate the real QML (AddressBar + UrlSuggestionsDropdown) and
verify, without needing Windows/WebView2:
  * the suggestions popup window is flagged non-activating (Qt.ToolTip),
    not Qt.Popup;
  * showing the popup leaves `activeFocus` with the address bar, and a second
    keystroke still lands in the field (the exact regression this guards).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest

from tests.conftest import GUI_AVAILABLE, ROOT

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

from modes.web.bookmarks import BookmarksStore
from modes.web.browser import BrowserContext


def _build(gui_app, tmp_path: Path) -> tuple[QQuickItem, BrowserContext]:
    engine = QQmlEngine()
    engine.addImportPath(str(ROOT))
    browser = BrowserContext(bookmarks=BookmarksStore(path=tmp_path / "bookmarks.json"))
    engine.rootContext().setContextProperty("modeContext_web", browser)
    component = QQmlComponent(
        engine, QUrl.fromLocalFile(str(ROOT / "modes" / "web" / "AddressBar.qml"))
    )
    assert not component.isError(), "\n".join(e.toString() for e in component.errors())
    bar = component.create()
    assert bar is not None
    bar._refs = (engine, component, browser)
    return bar, browser


def _find(bar: QQuickItem, class_fragment: str) -> QObject | None:
    return next(
        (
            o
            for o in bar.findChildren(QObject)
            if class_fragment in o.metaObject().className()
        ),
        None,
    )


def _show_in_window(gui_app, bar: QQuickItem, browser: BrowserContext) -> QQuickWindow:
    window = QQuickWindow()
    bar.setParentItem(window.contentItem())
    bar.setProperty("browser", browser)
    bar.setProperty("width", 900)
    bar.setProperty("height", 48)
    window.resize(1000, 700)
    window.show()
    QTest.qWait(50)
    return window


def test_suggestions_popup_is_non_activating_tooltip_window(gui_app, tmp_path: Path):
    """The dropdown must be a tooltip-style window, never a focus-grabbing Qt.Popup."""
    bar, _browser = _build(gui_app, tmp_path)
    popup = _find(bar, "UrlSuggestionsDropdown")
    assert popup is not None, "UrlSuggestionsDropdown not instantiated inside AddressBar"
    flags = int(getattr(popup, "flags")())
    # Qt.ToolTip (0xD) shares the popup type bit with Qt.Popup (0x9), so compare
    # the whole window-type mask: the suggestions window must be TOOLTIP, not
    # pure Qt.Popup — a plain Qt.Popup grabs keyboard focus on Windows when
    # shown (the "only one letter typed" bug).
    type_mask = 0xFF
    assert flags & type_mask == int(Qt.ToolTip), (
        f"suggestions window must be tooltip-style (never activates); flags={flags:#x}"
    )
    assert flags & Qt.WindowDoesNotAcceptFocus, "suggestions window must never accept focus"
    assert flags & Qt.WindowStaysOnTopHint, "suggestions window must stay above the web view"
    bar.deleteLater()


def test_typing_continues_while_suggestions_are_visible(gui_app, tmp_path: Path):
    """After the first letter opens the popup, the next letters still land in the bar."""
    bar, browser = _build(gui_app, tmp_path)
    # A bookmark that matches the letter we will type, so the dropdown has
    # local results and actually becomes visible on the first keystroke.
    assert browser.addBookmark("Hello Example", "https://hello.example.com")
    window = _show_in_window(gui_app, bar, browser)

    url_input = _find(bar, "GlassField")
    assert url_input is not None, "address bar GlassField not found"
    url_input.forceActiveFocus()
    QTest.qWait(30)
    assert url_input.hasActiveFocus(), "address bar should hold focus before typing"

    # First letter: the field's onTextChanged opens the suggestions popup.
    QTest.keyClick(window, Qt.Key_H)
    QTest.qWait(100)  # let the popup show/position

    popup = _find(bar, "UrlSuggestionsDropdown")
    assert popup.property("visible") is True, "suggestions popup should be visible"
    assert url_input.property("text") == "h", "first letter must remain in the field"
    assert url_input.hasActiveFocus(), (
        "suggestions popup stole focus from the address bar — "
        "this is the 'only one letter typed' bug"
    )

    # Second letter: must still land in the field while the popup stays open.
    QTest.keyClick(window, Qt.Key_E)
    QTest.qWait(50)
    assert url_input.property("text") == "he", (
        "second letter was swallowed — typing must continue while suggestions show"
    )
    assert popup.property("visible") is True, "suggestions must remain visible while typing"
    bar.deleteLater()
