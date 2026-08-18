"""Small, failure-safe startup splash lifecycle.

The splash shares Halcyon's existing QML engine but is deliberately standalone:
it imports no application modules, reads one local image, and has no network or
service dependencies.  A failure here must never prevent the player starting.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Slot

log = logging.getLogger(__name__)


def show_startup_splash(qml_engine, qml_path: Path):
    """Load, centre, and show the splash; return ``None`` on any failure."""
    splash = None
    try:
        # Kept local so importing the lifecycle helper remains safe in a
        # headless test process that only has QtCore available.
        from PySide6.QtGui import QCursor, QGuiApplication

        before = len(qml_engine.rootObjects())
        qml_engine.load(QUrl.fromLocalFile(str(Path(qml_path))))
        roots = qml_engine.rootObjects()
        if len(roots) <= before:
            log.warning("startup splash failed to load")
            return None

        splash = roots[-1]
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            splash.setScreen(screen)
            area = screen.availableGeometry()
            splash.setPosition(
                area.x() + (area.width() - splash.width()) // 2,
                area.y() + (area.height() - splash.height()) // 2,
            )

        splash.show()
        splash.raise_()
        # Startup has not entered app.exec() yet.  One bounded event pass lets
        # Qt expose and paint this local-only window before heavier services are
        # constructed; there is no nested event loop and no artificial delay.
        QGuiApplication.processEvents()
        return splash
    except Exception:
        log.debug("startup splash unavailable", exc_info=True)
        if splash is not None:
            try:
                splash.close()
            except Exception:
                log.debug("partially-created startup splash could not close", exc_info=True)
        return None


def close_startup_splash(splash, *, immediate: bool = False) -> None:
    """Dismiss the splash without ever allowing it to affect startup."""
    if splash is None:
        return
    try:
        if immediate:
            splash.close()
            return
        dismiss = getattr(splash, "dismiss", None)
        if callable(dismiss):
            dismiss()
        else:
            splash.close()
    except Exception:
        log.debug("startup splash close failed", exc_info=True)
        try:
            splash.close()
        except Exception:
            log.debug("startup splash fallback close failed", exc_info=True)


class FirstFrameSplashCloser(QObject):
    """Close the splash after the main QQuickWindow presents its first frame."""

    def __init__(self, splash, main_window, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._splash = splash
        self._main_window = main_window
        self._done = splash is None or main_window is None
        if self._done:
            return
        # frameSwapped may originate from Qt's render thread.  A queued
        # connection guarantees the QML dismiss function runs on the GUI thread.
        main_window.frameSwapped.connect(
            self._on_first_frame, Qt.ConnectionType.QueuedConnection
        )

    @Slot()
    def _on_first_frame(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            self._main_window.frameSwapped.disconnect(self._on_first_frame)
        except (RuntimeError, TypeError):
            pass
        close_startup_splash(self._splash)
        self._splash = None
        self._main_window = None
        log.debug("startup splash dismissed after first main-window frame")
