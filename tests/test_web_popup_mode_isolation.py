"""Web popups must disappear when Web is parked for Local/M3U."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import GUI_AVAILABLE, ROOT

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

if GUI_AVAILABLE:
    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest

from modes.web.bookmarks import BookmarksStore
from modes.web.browser import BrowserContext


def _build_address_bar(gui_app, tmp_path: Path):
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

    window = QQuickWindow()
    bar.setParentItem(window.contentItem())
    bar.setProperty("browser", browser)
    bar.setProperty("width", 900)
    bar.setProperty("height", 48)
    window.resize(1000, 700)
    window.show()
    QTest.qWait(50)
    return bar, browser, window


def _object(root: QObject, name: str) -> QObject:
    obj = root.findChild(QObject, name)
    assert obj is not None, f"{name} not found"
    return obj


def _button(root: QObject, tooltip: str) -> QObject:
    for obj in root.findChildren(QObject):
        if str(obj.property("tooltip") or "") == tooltip:
            return obj
    raise AssertionError(f"button with tooltip {tooltip!r} not found")


def _assert_all_web_popups_hidden(bar):
    assert _object(bar, "addBookmarkPopup").property("visible") is False
    assert _object(bar, "editBookmarkPopup").property("visible") is False
    assert _object(bar, "bookmarksDropdown").property("visible") is False
    assert _object(bar, "clearBrowsingDataDialog").property("visible") is False
    assert _object(bar, "urlSuggestions").property("visible") is False


def _open_bookmark_ui(bar, browser):
    browser.addTab("https://example.com")
    QTest.qWait(50)

    add_popup = _object(bar, "addBookmarkPopup")
    edit_popup = _object(bar, "editBookmarkPopup")
    dropdown = _object(bar, "bookmarksDropdown")

    # The current page is not bookmarked yet, so the star opens Add Bookmark.
    _button(bar, "Bookmark this page").clicked.emit()
    QTest.qWait(50)
    assert add_popup.property("visible") is True
    assert edit_popup.property("visible") is False

    _button(bar, "Bookmarks").clicked.emit()
    QTest.qWait(50)
    assert dropdown.property("visible") is True


def test_bookmark_popups_close_when_web_stage_becomes_inactive(gui_app, tmp_path: Path):
    bar, browser, window = _build_address_bar(gui_app, tmp_path)
    _open_bookmark_ui(bar, browser)

    bar.setProperty("stageActive", False)
    QTest.qWait(50)

    _assert_all_web_popups_hidden(bar)

    bar.deleteLater()
    window.deleteLater()


def test_bookmark_popups_close_when_address_bar_hides(gui_app, tmp_path: Path):
    bar, browser, window = _build_address_bar(gui_app, tmp_path)
    _open_bookmark_ui(bar, browser)

    bar.setProperty("visible", False)
    QTest.qWait(50)

    _assert_all_web_popups_hidden(bar)

    bar.deleteLater()
    window.deleteLater()
