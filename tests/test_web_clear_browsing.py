"""Clean-state checks for the Clear Browsing Data dialog (§4.1).

The old clearing logic was removed entirely.  These tests verify the dialog
still opens from the bookmarks dropdown and keeps its layout: the 8 checkbox
rows, the Cancel and Clear buttons, and NO time-range dropdown.  The clearing
behaviour itself is re-tested once the new implementation lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import GUI_AVAILABLE, ROOT

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

if GUI_AVAILABLE:
    from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
    from PySide6.QtTest import QTest

from modes.web.bookmarks import BookmarksStore
from modes.web.browser import BrowserContext

CLEAR_BUTTON_TEXT = "Clear browsing data"


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------
def _build_bar(gui_app, tmp_path: Path):
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    engine = QQmlEngine()
    engine.addImportPath(str(ROOT))
    browser = BrowserContext(bookmarks=BookmarksStore(path=tmp_path / "bookmarks.json"))
    engine.rootContext().setContextProperty("modeContext_web", browser)
    component = QQmlComponent(
        engine, QUrl.fromLocalFile(str(ROOT / "modes" / "web" / "AddressBar.qml"))
    )
    assert not component.isError(), "\n".join(e.toString() for e in component.errors())
    bar = component.create()
    assert bar is not None, "\n".join(e.toString() for e in component.errors())
    bar._refs = (engine, component, browser)
    return bar, browser


def _show_in_window(gui_app, bar, browser):
    # The AddressBar is an Item; host it in a real window via QQuickView so
    # popups have a proper Window.window to anchor to, exactly like the app.
    from PySide6.QtQuick import QQuickView

    view = QQuickView()
    view.engine().addImportPath(str(ROOT))
    view.rootContext().setContextProperty("modeContext_web", browser)
    view.setSource(QUrl.fromLocalFile(str(ROOT / "modes" / "web" / "AddressBar.qml")))
    assert view.rootObject() is not None, "AddressBar did not build inside QQuickView"
    view.resize(1000, 700)
    view.show()
    QTest.qWait(50)
    return view, view.rootObject()


def _children_matching(root: QObject, class_fragment: str) -> list[QObject]:
    return [
        o
        for o in root.findChildren(QObject)
        if class_fragment in o.metaObject().className()
    ]


def _child_matching(root: QObject, class_fragment: str) -> QObject:
    matches = _children_matching(root, class_fragment)
    assert matches, f"no child matching {class_fragment!r}"
    return matches[0]


def _button_with(root: QObject, prop: str, value: str) -> QObject:
    for fragment in ("IconButton", "TextButton", "AbstractButton"):
        for obj in _children_matching(root, fragment):
            if str(obj.property(prop) or "") == value:
                return obj
    raise AssertionError(f"no button with {prop}={value!r}")


def _checkbox_rows(dialog: QObject) -> dict[str, QObject]:
    rows = {}
    for row in _children_matching(dialog, "CheckBoxRow"):
        rows[str(row.property("optionId"))] = row
    return rows


# ---------------------------------------------------------------------------
# the click path — regression for the dialog that never opened
# ---------------------------------------------------------------------------
def test_clear_button_in_dropdown_opens_the_dialog(gui_app, tmp_path: Path):
    bar, browser = _build_bar(gui_app, tmp_path)
    assert browser.addBookmark("Example", "https://example.com")
    _view, bar = _show_in_window(gui_app, bar, browser)

    qml_errors: list[str] = []

    def _collect(mode, context, message):  # noqa: ANN001 - Qt signature
        text = str(message)
        if "does only support types" in text or "Window.window" in text:
            qml_errors.append(text)

    previous_handler = qInstallMessageHandler(_collect)
    try:
        # Step 1 — open the bookmarks dropdown from the ⋯ menu button.
        menu_button = _button_with(bar, "tooltip", "Bookmarks")
        menu_button.clicked.emit()
        QTest.qWait(120)

        dropdown = _child_matching(bar, "BookmarksDropdown")
        assert dropdown.property("visible") is True, "bookmarks dropdown did not open"

        # Step 2 — click 'Clear browsing data' inside the dropdown.
        clear_button = _button_with(bar, "text", CLEAR_BUTTON_TEXT)
        clear_button.clicked.emit()
        QTest.qWait(300)
    finally:
        qInstallMessageHandler(previous_handler)

    assert not qml_errors, "QML errors while opening the dialog:\n" + "\n".join(qml_errors)
    assert dropdown.property("visible") is False, "dropdown should close when Clear opens"

    dialog = _child_matching(bar, "ClearBrowsingDataDialog")
    assert dialog.property("visible") is True, "Clear Browsing Data dialog did not open"

    bar.deleteLater()


# ---------------------------------------------------------------------------
# layout: 8 checkbox rows, Cancel + Clear buttons, NO time-range dropdown
# ---------------------------------------------------------------------------
SPEC_OPTIONS = {
    "browsingHistory": ("Browsing history", True, False),
    "downloadHistory": ("Download history", False, False),
    "cookies": ("Cookies and site data", True, True),
    "cache": ("Cached images and files", True, False),
    "passwords": ("Passwords", False, True),
    "autofill": ("Autofill form data", False, True),
    "sitePermissions": ("Site permissions", False, False),
    "serviceWorkers": ("Service workers and offline data", False, False),
}


def test_dialog_layout_has_eight_checkboxes_no_dropdown(gui_app, tmp_path: Path):
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    engine = QQmlEngine()
    engine.addImportPath(str(ROOT))
    browser = BrowserContext(bookmarks=BookmarksStore(path=tmp_path / "bookmarks.json"))
    engine.rootContext().setContextProperty("modeContext_web", browser)
    component = QQmlComponent(
        engine, QUrl.fromLocalFile(str(ROOT / "modes" / "web" / "ClearBrowsingDataDialog.qml"))
    )
    assert not component.isError(), "\n".join(e.toString() for e in component.errors())
    dialog = component.create()
    assert dialog is not None, "\n".join(e.toString() for e in component.errors())
    dialog._refs = (engine, component, browser)
    dialog.setProperty("browser", browser)

    rows = _checkbox_rows(dialog)
    assert set(rows) == set(SPEC_OPTIONS), f"expected the eight options, got {set(rows)}"
    for option_id, (label, default_tick, destructive) in SPEC_OPTIONS.items():
        row = rows[option_id]
        assert str(row.property("label")) == label
        assert bool(row.property("checked")) is default_tick
        assert bool(row.property("destructive")) is destructive

    # No time-range dropdown in the clean/rewritten dialog.
    assert not _children_matching(dialog, "ComboBox"), "dialog must have no dropdown"
    assert dialog.property("timeRanges") is None, "old timeRanges property must be gone"

    # Both footer buttons exist.
    assert _button_with(dialog, "text", "Cancel")
    assert _button_with(dialog, "text", "Clear")

    dialog.deleteLater()
