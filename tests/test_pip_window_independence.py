"""The PiP window must not be transient for the main window — §P2.5.

Why this file exists
--------------------
QML automatically makes a ``Window`` declared inside another ``Window`` (or
inside an Item of its scene) *transient* for it: the inner window's
``transientParent`` is auto-assigned to the outer window. On Windows that is
an *owned* window relationship, and the platform then minimises the owned
window together with its owner. So the checklist item "Main window can
minimise while PiP keeps playing" silently failed: pressing the main window's
minimise button also minimised the PiP.

The fix is a single explicit line in ``ui/overlay/PipWindow.qml``::

    transientParent: null

(Qt docs, ``Window.transientParent``: "minimizing the parent window will also
minimize the transient window ... Setting the transientParent to null will
override this behavior".)

These tests load the **real** ``ui/overlay/PipWindow.qml`` into a live QML
engine and pin the contract:

* the PiP window has **no** transient parent (the fix — without it the
  auto-assignment returns and the bug comes back);
* the auto-assignment mechanism itself exists, so the test above actually
  has teeth (a control nested window, no explicit ``null``, *does* get the
  main window as its transient parent);
* after the main window is minimised, the PiP window stays visible.

The third test is best-effort: some platforms cannot model ``showMinimized``
at all (e.g. the offscreen QPA in a bare container), so it skips itself
rather than fail. The first two are deterministic everywhere QML can
instantiate.

The engine module is imported for its side effect only: it registers
``Halcyon.Engine.VideoSurface`` via ``@QmlElement``, which PipWindow.qml
instantiates. Fakes stand in for the ``Settings``/``Player``/``Actions``
context properties the real app injects (see main.py).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from tests.conftest import GUI_AVAILABLE, ROOT

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

if GUI_AVAILABLE:
    from PySide6.QtQml import QQmlComponent, QQmlEngine


class FakeSettings(QObject):
    """Minimal stand-in for core/settings.py — get/set, nothing else."""

    def __init__(self):
        super().__init__()
        self.store: dict = {}

    @Slot(str, "QVariant", result="QVariant")
    def get(self, key: str, default=None):
        return self.store.get(key, default)

    @Slot(str, "QVariant")
    def set(self, key: str, value) -> None:
        self.store[key] = value


class FakePlayer(QObject):
    isPlayingChanged = Signal()

    def __init__(self):
        super().__init__()
        self._playing = False

    @Property(bool, notify=isPlayingChanged)
    def isPlaying(self):
        return self._playing


class FakeActions(QObject):
    @Slot()
    def playPause(self) -> None:
        pass


#: The host scene: a main Window whose scene contains a Loader instantiating
#: the real PipWindow.qml, exactly like M3UTransport.qml does (§P2.3). The
#: window is hidden again immediately after load so the test never needs a
#: rendering context; `showForMinimize` is used by the visibility test.
HOST_QML = """
import QtQuick

Window {
    id: mainWin
    width: 1200
    height: 800
    visible: false

    Loader {
        id: pipLoader
        active: true
        source: "%(pip)s"
        onLoaded: {
            item.mainWindow = mainWin;
            item.visible = false;      // contract test: no rendering needed
        }
    }

    Component.onCompleted: pipLoader.item.objectName = "pipUnderTest"
}
"""


@pytest.fixture()
def pip_env(gui_app):
    """A QML engine with the real PipWindow.qml loaded beside a main window.

    Returns ``(main_window, pip_window, refs)``; ``refs`` must stay alive for
    the duration of the test (QML object lifetime is owned by the engine).
    """
    from engine import surface as _surface  # noqa: F401  (@QmlElement side effect)

    engine = QQmlEngine()
    engine.addImportPath(str(ROOT))

    ctx = engine.rootContext()
    settings, player, actions = FakeSettings(), FakePlayer(), FakeActions()
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("Player", player)
    ctx.setContextProperty("Actions", actions)

    qml = HOST_QML % {"pip": (ROOT / "ui" / "overlay" / "PipWindow.qml").as_uri()}
    component = QQmlComponent(engine)
    component.setData(qml.encode("utf-8"), QUrl("host.qml"))
    if component.isError():
        pytest.fail(
            "host scene did not compile:\n"
            + "\n".join(e.toString() for e in component.errors())
        )

    main_win = component.create()
    assert main_win is not None, "host scene failed to instantiate"

    pip = main_win.findChild(type(main_win), "pipUnderTest")
    if pip is None:
        pytest.fail("PipWindow.qml was not instantiated by the Loader")

    refs = (engine, component, settings, player, actions)
    return main_win, pip, refs


def test_pip_window_has_no_transient_parent(pip_env):
    """The fix: the PiP is an independent top-level window.

    If someone deletes ``transientParent: null`` from PipWindow.qml, QML
    auto-assigns the main window here and this test fails.
    """
    _main, pip, _refs = pip_env
    assert pip.property("transientParent") is None, (
        "PipWindow.qml must declare `transientParent: null` — otherwise the "
        "PiP is an owned window of the main window and minimising Halcyon "
        "minimises the PiP too (§P2.5)."
    )


def test_nested_window_gets_transient_parent_by_default(gui_app):
    """Control: without the explicit null, QML auto-assigns the parent.

    Proves the mechanism the fix defends against, and therefore that
    test_pip_window_has_no_transient_parent can actually fail.
    """
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    component.setData(
        b"""
        import QtQuick
        Window {
            id: mainWin
            width: 800; height: 600
            visible: false
            Window {
                id: nested
                objectName: "nested"
                width: 200; height: 100
                visible: false
            }
        }
        """,
        QUrl("control.qml"),
    )
    main_win = component.create()
    assert main_win is not None
    nested = main_win.findChild(type(main_win), "nested")
    assert nested is not None
    assert nested.property("transientParent") is main_win, (
        "QML auto-assigns the containing window as transientParent — this "
        "control must hold or the main regression test has no teeth."
    )


def test_minimizing_main_window_keeps_pip_visible(pip_env):
    """The user-visible contract: minimise Halcyon, the PiP keeps playing.

    Best-effort: platforms that cannot model ``showMinimized`` (offscreen QPA
    in a bare container) skip rather than fail.
    """
    main_win, pip, _refs = pip_env

    main_win.show()
    pip.show()
    if not pip.isVisible():
        pytest.skip("platform cannot show the PiP window — nothing to assert")

    main_win.showMinimized()
    if main_win.visibility() != main_win.Visibility.Minimized:
        pytest.skip("platform does not propagate the minimized state")

    assert pip.isVisible(), (
        "Minimising the main window hid the PiP — the PiP must be an "
        "independent window (`transientParent: null`), not an owned one."
    )
    assert pip.visibility() != pip.Visibility.Minimized, (
        "Minimising the main window minimised the PiP (§P2.5)."
    )
