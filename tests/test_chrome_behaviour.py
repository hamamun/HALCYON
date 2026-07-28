"""Chrome behaviour: what the title bar says, and when the bar hides.

Two reported bugs live here.

**The title bar never said what was playing.** It showed the "Halcyon" wordmark
and nothing else, so with the info dock closed (the default) and a video on the
stage there was no way to tell which file was on air, and the taskbar button was
identical for every window.

**The transport bar auto-hid in windowed mode.** Auto-hide exists to get the
chrome out of the way of an immersive fullscreen picture. In a window there is
nothing to be immersed in — the window has borders, a title bar and a desktop
around it — so hiding the controls out from under a pointer that is *in the
window* is just the controls disappearing when the user stops moving for two and
a half seconds.

These are source-level checks on ``ui/Main.qml``. They deliberately need no Qt:
building a real window pulls in QtGui and a GL driver, which a CI box or a
container does not have, and a chrome-visibility rule that is only verified on a
developer's desktop is a rule that quietly rots. The companion file
``test_titlebar_binding.py`` does instantiate the real component, and skips
where it cannot.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _main_qml() -> str:
    return (ROOT / "ui" / "Main.qml").read_text(encoding="utf-8")
def _main_qml() -> str:
    return (ROOT / "ui" / "Main.qml").read_text(encoding="utf-8")


def test_auto_hide_is_gated_on_fullscreen():
    """The gate must be a single named property, not a condition per call site.

    Re-testing ``fullscreen`` at each place that reads ``chromeVisible`` is how
    one of them gets missed.
    """
    source = _main_qml()

    assert "readonly property bool autoHideActive: fullscreen" in source, (
        "auto-hide must be gated on fullscreen in exactly one place"
    )


def test_the_idle_timer_cannot_hide_the_bar_in_a_window():
    source = _main_qml()
    body = source.split("id: idleTimer", 1)[1]

    assert "if (!window.autoHideActive)" in body, (
        "the idle timer must bail out when not fullscreen, or the transport bar "
        "fades away in windowed mode"
    )


def test_the_cursor_is_blanked_only_in_fullscreen():
    source = _main_qml()

    assert "Qt.BlankCursor" in source, "fullscreen must hide the mouse cursor"
    blanker = source.split("id: cursorBlanker", 1)[1]
    assert "window.autoHideActive && !window.chromeVisible" in blanker, (
        "the cursor must only vanish in fullscreen, and only with the chrome"
    )


def test_the_cursor_blanker_swallows_no_clicks():
    """It sits above everything, so it must be transparent to input.

    ``Qt.NoButton`` is what lets play/pause, the transport buttons and
    double-click-to-exit-fullscreen keep working while the cursor is hidden.
    """
    source = _main_qml()
    blanker = source.split("id: cursorBlanker", 1)[1].split("}", 1)[0]

    assert "acceptedButtons: Qt.NoButton" in blanker
    assert "onPositionChanged: window.wakeChrome()" in blanker, (
        "moving the mouse must bring the cursor and chrome straight back"
    )


def test_leaving_fullscreen_restores_the_chrome():
    source = _main_qml()

    assert "onAutoHideActiveChanged: wakeChrome()" in source, (
        "exiting fullscreen while the bar is hidden must not leave a window "
        "with no controls and no cursor"
    )


def test_the_window_title_carries_the_media_title():
    source = _main_qml()

    assert "titleBar.mediaTitle" in source, (
        "the taskbar button and Alt-Tab should name the file, not just the app"
    )
