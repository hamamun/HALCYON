"""The OSD must be visible, not merely instantiated — §6.2, §P1.4.

The resume toast was reported as "nothing appears". It *was* appearing: `Osd`
lived inside `Stage`, a z:0 sibling of the two z:10 panel docks, and z only
orders siblings. The left dock is 300 px wide, open by default and anchored to
the same top-left origin as the pills, so every OSD message — status, volume
level and the resume toast alike — was painted underneath it in windowed mode.
It only ever looked right in fullscreen, where both docks are forced shut.

These tests assert on **scene coordinates**, because that is the thing that was
wrong. A test that only checked `osdLayer !== null`, or that `showResume()` set
`visible: true`, passed happily throughout the entire bug.

Skipped where QtGui/QML cannot be instantiated (headless CI without libGL), the
same rule the other QML tests here follow.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QUrl

from tests.conftest import GUI_AVAILABLE

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def window(gui_app):
    """The real ui/Main.qml, wired with the same stubs the chrome tests use."""
    from PySide6.QtQml import QQmlApplicationEngine

    import engine.surface  # noqa: F401 - registers VideoSurface with QML
    from core.app import ModeList
    from core.settings import Settings
    from modes.local.playlist import PlaylistModel
    from tests.test_fullscreen_chrome import _Stub

    qml_engine = QQmlApplicationEngine()
    qml_engine.addImportPath(str(ROOT))

    stub = _Stub()
    settings = Settings()
    ctx = qml_engine.rootContext()
    for name in ("App", "Player", "Metadata", "Lyrics", "Library", "Equalizer"):
        ctx.setContextProperty(name, stub)
    modes = ModeList()
    playlist = PlaylistModel()
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("Modes", modes)
    ctx.setContextProperty("LocalPlaylist", playlist)

    qml_engine.load(QUrl.fromLocalFile(str(ROOT / "ui" / "Main.qml")))
    roots = qml_engine.rootObjects()
    assert roots, "ui/Main.qml failed to load"
    # Let PanelHost's documented 220 ms open animation settle before measuring
    # scene coordinates.  Without this a just-created window is sampled at its
    # animation's initial zero width rather than its requested open state.
    from PySide6.QtTest import QTest
    QTest.qWait(260)
    # Context properties are non-owning references.  Retain the Python objects
    # for the test's entire QML lifetime, exactly as main.py does in
    # _KEEP_ALIVE; otherwise Modes can be collected and turn the dock test into
    # a null-context race.
    roots[0]._refs = (qml_engine, stub, settings, modes, playlist)
    yield roots[0]
    del qml_engine


def _find(root, object_name_or_id):
    """Locate a child by its QML id, which Qt exposes as the object name only
    when set — so fall back to walking for the property signature instead."""
    for child in root.findChildren(object):
        meta = child.metaObject()
        if meta and meta.className().startswith("Osd"):
            return child
    return None


def test_osd_is_not_a_child_of_the_stage(window):
    """The structural fix. Inside Stage it can never outrank a z:10 dock."""
    osd = _find(window, "osdLayer")
    assert osd is not None, "the OSD layer is missing from the window"

    ancestors = []
    parent = osd.parent()
    while parent is not None:
        ancestors.append(parent.metaObject().className())
        parent = parent.parent()

    assert not any(name.startswith("Stage") for name in ancestors), (
        "the OSD is inside Stage again — it will be painted under the panel "
        f"docks. Ancestors: {ancestors}"
    )


def test_osd_outranks_the_panel_docks(window):
    osd = _find(window, "osdLayer")
    assert osd.property("z") > 10, (
        "the OSD must sit above the z:10 docks, not level with or below them"
    )


def test_osd_clears_the_open_left_dock(window, gui_app):
    """The symptom itself: the toast's origin must not be under the queue."""
    from PySide6.QtCore import QPointF

    osd = _find(window, "osdLayer")
    # Theme.spaceXl — where every pill is positioned inside the OSD item.
    pill_origin = osd.mapToScene(QPointF(24.0, 24.0))

    # The left dock is open by default (window.leftPanelVisible).
    assert pill_origin.x() >= 300.0 - 1.0, (
        f"the OSD pill starts at scene x={pill_origin.x():.0f}, inside the "
        "300px playlist dock — it will be invisible in windowed mode"
    )


# ---------------------------------------------------------------------------
# Mode-switch cleanup — the OSD is shared by Local, M3U and Web. A mode switch
# stops the current player but usually does not open new media, so no
# mediaChanged arrives to retire a visible toast; without App.activeModeChanged
# wiring, an old mode's Resume / Now Playing / volume pill keeps floating over
# the new mode until its own timer runs out.
# ---------------------------------------------------------------------------


def _pill_containing(osd, marker_text):
    """The direct child of the OSD that contains an item whose `text` property
    equals marker_text — i.e. the pill (or centre glyph) itself. Walks up from
    the text until the parent is the OSD root, which is where every pill lives.
    """
    from PySide6.QtQuick import QQuickItem

    target = None
    for child in osd.findChildren(QQuickItem):
        if child.property("text") == marker_text:
            target = child
            break
    assert target is not None, f"marker text {marker_text!r} not found in the OSD"

    node = target
    while node is not None and node.parent() is not osd:
        node = node.parent()
    assert node is not None and node is not osd, (
        f"could not find the pill owning {marker_text!r}"
    )
    return node


def test_mode_switch_clears_every_osd_pill(window, gui_app):
    """The reported bug: a Local Resume toast must not survive into M3U.

    Drives the real window; shows every kind of toast the OSD owns, emits
    App.activeModeChanged (the signal App.setActiveMode fires), and asserts
    each pill left the scene graph at once and its timers cannot resurrect it.
    """
    from PySide6.QtTest import QTest

    osd = _find(window, "osdLayer")
    stub = window._refs[1]           # the App/Player stand-in from the fixture

    osd.showResume("/tmp/film.mkv", 867_000)
    osd.show("Now Playing: film.mkv", "st-marker")
    osd.showLevel("Volume 80%", "lv-marker", 0.8)
    osd.showGlyph("bg-marker")

    resume_pill = _pill_containing(osd, "Start Over")
    status_pill = _pill_containing(osd, "Now Playing: film.mkv")
    level_pill = _pill_containing(osd, "Volume 80%")
    big_glyph = _pill_containing(osd, "bg-marker")

    for pill in (resume_pill, status_pill, level_pill, big_glyph):
        assert pill.property("visible") is True, "toast failed to show"
    assert osd.property("resumePath") == "/tmp/film.mkv"

    # App.setActiveMode() emits activeModeChanged; the shell clears the OSD.
    stub.activeModeChanged.emit()

    for pill in (resume_pill, status_pill, level_pill, big_glyph):
        assert pill.property("visible") is False, (
            "an OSD pill survived the mode switch"
        )
    assert osd.property("resumePath") == "", (
        "the stored resume path survived the mode switch — Start Over could "
        "rewind another mode's media"
    )

    # The fade-completion timers were stopped too: nothing may pop a pill back
    # into the scene, and the fade runs out to opacity 0.
    QTest.qWait(400)
    for pill in (resume_pill, status_pill, level_pill, big_glyph):
        assert pill.property("visible") is False
        assert pill.property("opacity") == 0.0


def test_new_toasts_work_after_a_mode_switch(window, gui_app):
    """Test case 7: after switching modes, the new mode may show its own
    correct Now Playing or Resume toast — the cleanup must not disable the OSD.
    """
    from PySide6.QtTest import QTest

    osd = _find(window, "osdLayer")
    stub = window._refs[1]

    osd.show("Now Playing: old.mkv", "st-marker")
    stub.activeModeChanged.emit()
    assert _pill_containing(osd, "Now Playing: old.mkv").property("visible") is False

    osd.show("Now Playing: channel.m3u8", "st-marker")
    osd.showResume("/tmp/new.mkv", 12_000)
    QTest.qWait(10)
    assert _pill_containing(osd, "Now Playing: channel.m3u8").property("visible") is True
    assert _pill_containing(osd, "Start Over").property("visible") is True
    assert osd.property("resumePath") == "/tmp/new.mkv"


def test_playlist_playback_clear_retires_start_over_toast(window, gui_app):
    """Removing the current/last item has no following mediaChanged event.

    Drive the controller's dedicated lifecycle edge and verify the real OSD
    immediately removes both the visible prompt and its stored click target.
    Its stopped timers must not resurrect the prompt afterwards.
    """
    from PySide6.QtTest import QTest

    osd = _find(window, "osdLayer")
    stub = window._refs[1]

    # Begin from a clean OSD even if this module-scoped window was left with a
    # toast by the preceding test.
    osd.clear()
    osd.showResume("/tmp/deleted.mkv", 867_000)
    resume_pill = _pill_containing(osd, "Start Over")
    assert resume_pill.property("visible") is True
    assert osd.property("resumePath") == "/tmp/deleted.mkv"

    stub.playlistPlaybackCleared.emit()

    # visible:false removes the toast and button immediately.  Opacity still
    # completes its declared Behavior animation while the item is off-scene.
    assert resume_pill.property("visible") is False
    assert osd.property("resumePath") == ""

    QTest.qWait(400)
    assert resume_pill.property("visible") is False
    assert resume_pill.property("opacity") == 0.0
    assert osd.property("resumePath") == ""

