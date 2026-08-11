"""The shared OSD must be cleared on every mode switch — source-level checks.

A mode switch stops the current player but usually does not open new media, so
no ``mediaChanged`` arrives to retire a visible toast. The OSD is one shared
layer for Local, M3U and Web, so an old mode's Resume / Start Over, Now Playing,
volume or glyph toast keeps floating over the new mode until its own timer runs
out — and Start Over would act on media that belongs to another mode.

The fix is one central cleanup (``Osd.clear()``) wired to
``App.activeModeChanged`` in the shared shell, keeping the existing
``mediaChanged`` cleanup intact: clear the OSD on both media changes and mode
changes.

These are source-level checks on ``ui/Main.qml`` and ``ui/overlay/Osd.qml``.
They deliberately need no Qt: a wiring rule that is only verified on a
developer's desktop is a rule that quietly rots (test_chrome_behaviour.py makes
the same argument). The behavioural companion test lives in
test_osd_layering.py.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OSD_QML = ROOT / "ui" / "overlay" / "Osd.qml"
MAIN_QML = ROOT / "ui" / "Main.qml"


def _osd_source() -> str:
    return OSD_QML.read_text(encoding="utf-8")


def _main_source() -> str:
    return MAIN_QML.read_text(encoding="utf-8")


def _clear_body() -> str:
    """The body of Osd.clear(), up to the next function in the file."""
    source = _osd_source()
    assert "function clear()" in source, "the shared OSD has no clear()"
    body = source.split("function clear()", 1)[1]
    # clear() sits between hideResume() and _can(); cut at the next function.
    return body.split("\n    function _can", 1)[0]


def test_osd_clear_is_one_central_function() -> None:
    """One cleanup for every pill — not separate Local/M3U/Web variants."""
    source = _osd_source()
    assert source.count("function clear()") == 1, (
        "there must be exactly one OSD-wide cleanup function"
    )


def test_clear_stops_every_osd_timer() -> None:
    """A stopped timer must not pop a pill back up mid-mode-switch."""
    body = _clear_body()
    for timer in ("resumeTimer", "statusTimer", "levelTimer", "bigTimer"):
        assert f"{timer}.stop()" in body, f"clear() must stop {timer}"
    # The fade-completion timers too, or the pill lingers in the scene.
    for timer in ("resumeHideDelay", "hideDelay", "levelHide", "bigHide"):
        assert f"{timer}.stop()" in body, f"clear() must stop {timer}"


def test_clear_hides_every_pill_immediately() -> None:
    """visible: false removes the pill (and its Start Over button) from the
    scene graph at once, not after the fade — so it cannot be clicked."""
    body = _clear_body()
    for pill in ("resumePill", "statusPill", "levelPill"):
        assert f"{pill}.opacity = 0" in body, f"clear() must fade {pill}"
        assert f"{pill}.visible = false" in body, f"clear() must hide {pill}"
    assert "bigGlyph.opacity = 0" in body
    assert "bigGlyph.visible = false" in body


def test_clear_forgets_the_resume_path() -> None:
    """A stale Start Over click must not rewind another mode's media."""
    body = _clear_body()
    assert 'root.resumePath = ""' in body, (
        "clear() must drop the stored resume path so Start Over cannot act "
        "on media from another mode"
    )


def test_main_qml_clears_the_osd_on_mode_change() -> None:
    """The cleanup hangs off the shared signal, in the shared shell."""
    source = _main_source()
    assert "function onActiveModeChanged()" in source, (
        "Main.qml must react to App.activeModeChanged"
    )
    handler = source.split("function onActiveModeChanged()", 1)[1]
    handler = handler.split("\n    }", 1)[0]
    assert "osdLayer.clear()" in handler, (
        "the mode-change handler must call the one OSD-wide cleanup"
    )


def test_media_change_cleanup_is_retained() -> None:
    """mediaChanged cleanup is still needed when switching media items."""
    source = _main_source()
    assert "function onMediaChanged() { osdLayer.hideResume() }" in source, (
        "the existing media-change resume cleanup must stay in place"
    )


def test_modes_add_no_osd_cleanup_of_their_own() -> None:
    """Local and M3U must not grow separate cleanup logic — the OSD is shared,
    so one shell-side call covers every mode."""
    for directory in ("modes/local", "modes/m3u", "modes/web"):
        for qml in sorted((ROOT / directory).rglob("*.qml")):
            source = qml.read_text(encoding="utf-8")
            assert "osdLayer.hideResume" not in source, (
                f"{qml} adds mode-local resume cleanup"
            )
            assert "osdLayer.clear" not in source and "osdLayer.hideAll" not in source, (
                f"{qml} adds mode-local OSD cleanup"
            )
