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
    # Blanking is fullscreen-ONLY, deliberately narrower than the auto-hide gate
    # (which now also covers borderless windowed mode). Fading the chrome in a
    # borderless window is fine; blanking the pointer in a windowed frame is not,
    # so the blanker keys off `window.fullscreen` directly rather than
    # `autoHideActive`.
    assert "window.fullscreen && !window.chromeVisible" in blanker, (
        "the cursor must only vanish in fullscreen, and only with the chrome"
    )


def test_the_cursor_blanker_swallows_no_clicks():
    """It sits above everything, so it must be transparent to input.

    ``Qt.NoButton`` is what lets play/pause, the transport buttons and
    double-click-to-exit-fullscreen keep working while the cursor is hidden.
    """
    source = _main_qml()
    blanker = source.split("id: cursorBlanker", 1)[1].split("onPositionChanged", 1)[0]

    assert "acceptedButtons: Qt.NoButton" in blanker


def test_pointer_wakeups_go_through_the_movement_test():
    """Neither hover area may call wakeChrome() straight from positionChanged.

    ``positionChanged`` also fires when an area appears under a stationary
    pointer, and when the scene relayouts beneath one — both of which hiding the
    bar causes. Waking on those unconditionally makes fullscreen oscillate on a
    2.5 s cycle. ``notePointer()`` is the shared guard that only wakes on a real
    move; going around it reintroduces the flicker.

    ``test_fullscreen_chrome.py`` proves the behaviour with real events; this
    keeps the two call sites honest even where those cannot run.
    """
    source = _main_qml()

    assert "onPositionChanged: window.wakeChrome()" not in source, (
        "waking directly from positionChanged reintroduces the fullscreen "
        "hide/show flicker — route it through notePointer()"
    )
    assert source.count("window.notePointer(mouse.x, mouse.y)") >= 2, (
        "idleWatcher and cursorBlanker must use the movement test; the Turbo "
        "overlay stage-click may add a third site"
    )


def test_leaving_fullscreen_restores_the_chrome():
    """Matched on the handler existing and calling wakeChrome, not on its exact
    text — it is a block rather than a one-liner, and reformatting it is not a
    regression. ``test_fullscreen_chrome.py`` asserts the actual behaviour.
    """
    source = _main_qml()

    assert "onAutoHideActiveChanged" in source, (
        "exiting fullscreen while the bar is hidden must not leave a window "
        "with no controls and no cursor"
    )
    handler = source.split("onAutoHideActiveChanged", 1)[1].split("MouseArea", 1)[0]
    assert "wakeChrome()" in handler, (
        "the fullscreen transition must wake the chrome"
    )


def test_the_window_title_carries_the_media_title():
    source = _main_qml()

    assert "titleBar.mediaTitle" in source, (
        "the taskbar button and Alt-Tab should name the file, not just the app"
    )
