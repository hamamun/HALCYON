"""Startup splash contract — minimal content, no delay, first-frame handoff."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from core.splash import FirstFrameSplashCloser

ROOT = Path(__file__).resolve().parent.parent
SPLASH = (ROOT / "ui" / "Splash.qml").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
HELPER = (ROOT / "core" / "splash.py").read_text(encoding="utf-8")


def test_splash_contains_only_the_approved_user_facing_copy():
    assert 'text: "HALCYON"' in SPLASH
    assert 'text: "Loading\\u2026"' in SPLASH
    assert 'Qt.resolvedUrl("../assets/halcyon.png")' in SPLASH

    # No version, progress percentage, rotating startup status, or remote URL.
    for unwanted in ("Version", "Starting player", "Loading interface", "%", "http://", "https://"):
        assert unwanted not in SPLASH


def test_splash_is_a_non_taskbar_local_window():
    assert "Qt.SplashScreen" in SPLASH
    assert "Qt.FramelessWindowHint" in SPLASH
    assert "Qt.WindowDoesNotAcceptFocus" in SPLASH
    assert "asynchronous: false" in SPLASH


def test_splash_handoff_is_first_frame_driven_not_timer_driven():
    assert "frameSwapped.connect" in HELPER
    assert "QueuedConnection" in HELPER
    assert "FirstFrameSplashCloser(startup_splash, main_window" in MAIN
    assert "singleShot" not in HELPER


def test_main_window_is_distinguished_from_the_splash_root():
    assert "roots_before_main = len(qml_engine.rootObjects())" in MAIN
    assert "len(roots_after_main) <= roots_before_main" in MAIN
    assert "main_window = roots_after_main[-1]" in MAIN


def test_first_frame_closer_dismisses_once_on_the_queued_gui_slot(qt_application):
    class Window(QObject):
        frameSwapped = Signal()

    class Splash:
        def __init__(self) -> None:
            self.dismissals = 0

        def dismiss(self) -> None:
            self.dismissals += 1

    window = Window()
    splash = Splash()
    closer = FirstFrameSplashCloser(splash, window)

    window.frameSwapped.emit()
    qt_application.processEvents()
    assert splash.dismissals == 1

    # The slot disconnects itself; later frames do not touch the retired splash.
    window.frameSwapped.emit()
    qt_application.processEvents()
    assert splash.dismissals == 1
    assert closer._done is True
