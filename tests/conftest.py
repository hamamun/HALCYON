"""Shared test setup.

**The one thing this file exists for: create the Qt application *once*, and make
it a QGuiApplication if it possibly can be.**

Qt allows exactly one application object per process, and it cannot be swapped.
Most tests here need nothing more than an event loop, so they open with the
usual ``QCoreApplication.instance() or QCoreApplication([])``. That is correct
in isolation — and fatal in a full run, because a QCoreApplication cannot serve
a QML scene. Anything that later builds a QML component gets

    QFontDatabase: Must construct a QGuiApplication before accessing QFontDatabase

followed by an abort that takes the whole pytest process with it, so the
remaining tests do not merely fail, they never run. Which module happens to go
first decides whether the suite passes, and ``pytest tests/test_titlebar_binding.py``
on its own passes while ``pytest tests`` dies.

Creating the QGuiApplication here, at conftest import time, settles it before
any test module is imported. The existing ``... .instance() or ...`` idioms then
find it and reuse it, exactly as intended, and a GUI-capable object satisfies
both kinds of test.

Where QtGui cannot be imported at all — a container with no GL library, which is
a normal CI box — we fall back to a QCoreApplication so the ~140 pure-logic
tests still run, and the QML tests skip themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: True when a real QGuiApplication is up, so QML can be instantiated. Test
#: modules that build QML components skip on this rather than guessing.
GUI_AVAILABLE = False


def _make_application():
    """Build the process-wide Qt application, preferring the GUI flavour."""
    global GUI_AVAILABLE

    from PySide6.QtCore import QCoreApplication

    existing = QCoreApplication.instance()
    if existing is not None:
        GUI_AVAILABLE = type(existing).__name__ != "QCoreApplication"
        return existing

    try:
        # Not importorskip: the failure on a headless box is a missing *shared
        # library* (libGL.so.1) surfacing as an ImportError from an installed
        # module, which importorskip re-raises rather than treating as absent.
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return QCoreApplication([])

    app = QGuiApplication([])
    GUI_AVAILABLE = True
    return app


#: Module level, deliberately. A fixture would run too late — pytest imports
#: every test module before the first fixture executes, and an import-time
#: QCoreApplication in any of them would already have won.
_APP = _make_application()


@pytest.fixture(scope="session")
def qt_application():
    """The shared application object, for tests that want it explicitly."""
    return _APP


@pytest.fixture(scope="session")
def gui_app(qt_application):
    """Like :func:`qt_application`, but skips when QML cannot be built."""
    if not GUI_AVAILABLE:
        pytest.skip("QtGui is unavailable — QML cannot be instantiated here")
    return qt_application
