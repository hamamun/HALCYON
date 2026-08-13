"""§S — QML side of the scrub preview: the seek bar publishes its hover
position, and the popup's visibility logic behaves.

GUI-gated like the other QML tests (test_fullscreen_chrome.py): skipped where
QtGui cannot be constructed (headless boxes), exercised for real on Windows.

These tests instantiate the components directly — no Main.qml, no engine —
so they pin the two contracts LocalTransport relies on:
  1. ``SeekBar.hoverFraction`` follows the pointer and returns to -1 on exit.
  2. ``ScrubPreview`` (pure display) shows only when enabled + hovered +
     a known fraction + a known duration, and formats its time label.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import GUI_AVAILABLE

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

if GUI_AVAILABLE:
    from PySide6.QtCore import QEvent, QObject, QPointF, QUrl, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickWindow

ROOT = Path(__file__).resolve().parent.parent


def _make_item(qml: str):
    engine = QQmlEngine()
    engine.addImportPath(str(ROOT))
    component = QQmlComponent(engine)
    component.setData(qml.encode("utf-8"), QUrl())
    item = component.create()
    assert item is not None, "component failed to load:\n" + "".join(
        e.toString() for e in component.errors()
    )
    return item


def _send_move(app, window, x: float, y: float) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(window, event)
    app.processEvents()


def test_seekbar_hover_fraction_follows_the_pointer_and_clears(qt_application) -> None:
    bar = _make_item(
        "import QtQuick\n"
        "import Halcyon.Transport\n"
        "SeekBar { width: 1000; height: 24 }\n"
    )
    window = QQuickWindow()
    bar.setParentItem(window.contentItem())
    window.resize(1000, 100)
    window.show()
    qt_application.processEvents()

    assert bar.property("hoverFraction") == -1, "away from the bar → -1"
    assert bar.property("hovering") is False

    # Pointer over the bar (its hover area extends 6px beyond each edge).
    _send_move(qt_application, window, 250, 12)
    fraction = bar.property("hoverFraction")
    assert 0.24 < fraction < 0.26, f"hover at 25% → {fraction}"
    assert bar.property("hovering") is True

    _send_move(qt_application, window, 900, 12)
    fraction = bar.property("hoverFraction")
    assert 0.89 < fraction < 0.91, f"hover at 90% → {fraction}"

    # Pointer leaves the bar (same window, below its hover envelope).
    _send_move(qt_application, window, 900, 90)
    assert bar.property("hoverFraction") == -1, "away → -1"
    assert bar.property("hovering") is False


def test_popup_shown_logic_and_time_label(qt_application) -> None:
    popup = _make_item(
        "import QtQuick\n"
        "import Halcyon.Overlay\n"
        "ScrubPreview {}\n"
    )
    qt_application.processEvents()

    assert popup.property("shown") is False, "nothing set → hidden"

    popup.setProperty("enabled", True)
    popup.setProperty("hovered", True)
    popup.setProperty("fraction", 0.5)
    popup.setProperty("duration", 60000)
    qt_application.processEvents()
    assert popup.property("shown") is True

    # Time label formats like the seek bar's tooltip: 30 s of 60 s → "0:30".
    texts = [
        child.property("text")
        for child in popup.findChildren(QObject)
        if child.metaObject().className() == "QQuickText"
    ]
    assert "0:30" in texts, texts

    # Leaving the bar hides it; the master switch hides it too.
    popup.setProperty("fraction", -1)
    qt_application.processEvents()
    assert popup.property("shown") is False

    popup.setProperty("fraction", 0.5)
    popup.setProperty("enabled", False)
    qt_application.processEvents()
    assert popup.property("shown") is False
