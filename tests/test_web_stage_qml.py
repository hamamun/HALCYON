"""Live QML checks for the browser-only Web stage.

The old Web implementation registered a chip but could still leave the stage
blank because the browser QML was only exercised as text.  These tests compile
and instantiate the actual chrome whenever QtGui is available; they do not need
Windows/WebView2 because no controller is created until a QQuickWindow page area
is attached.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QUrl

from tests.conftest import GUI_AVAILABLE, ROOT

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

if GUI_AVAILABLE:
    from PySide6.QtQml import QQmlComponent, QQmlEngine

from modes.web.bookmarks import BookmarksStore
from modes.web.browser import BrowserContext


@pytest.mark.parametrize(
    "name",
    [
        "BrowserPopup.qml",
        "CheckBoxRow.qml",
        "ClearBrowsingDataDialog.qml",
        "TabsRow.qml",
        "AddressBar.qml",
        "BookmarksDropdown.qml",
        "BookmarksManagerTab.qml",
        "WebStage.qml",
    ],
)
def test_web_qml_components_compile_and_instantiate(gui_app, tmp_path: Path, name: str):
    engine = QQmlEngine()
    engine.addImportPath(str(ROOT))
    browser = BrowserContext(bookmarks=BookmarksStore(path=tmp_path / "bookmarks.json"))
    engine.rootContext().setContextProperty("modeContext_web", browser)

    component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "modes" / "web" / name)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())

    item = component.create()
    assert item is not None, f"{name} did not instantiate: " + "\n".join(
        error.toString() for error in component.errors()
    )
    # Retain all Python/QML owners until assertions are complete; context
    # properties are intentionally non-owning in Qt.
    item._refs = (engine, component, browser)
    item.deleteLater()
