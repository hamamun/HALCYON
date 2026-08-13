"""The Video mode control, and what Turbo must not break — §V.1 / §V.3.

Two halves:

* **source-level** checks on the Settings dialog and the shell. They need no
  display, so the rules that say "the old Turbo checkbox is gone" and "the Soft
  path is untouched" are verified everywhere, including on a CI box with no GL.
  The same discipline as ``test_chrome_behaviour.py``.
* **live** checks that instantiate the real ``ui/Main.qml`` and read the actual
  ComboBox, because "there is a dropdown" is exactly the kind of claim that a
  text search can pass while the control is missing, disabled or empty.

Nothing here can verify Windows-native HWND embedding; see
``test_turbo_surface.py``'s module docstring.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SETTINGS_QML = ROOT / "ui" / "panels" / "SettingsDialog.qml"
MAIN_QML = ROOT / "ui" / "Main.qml"
VIDEO_STAGE_QML = ROOT / "ui" / "shell" / "VideoStage.qml"
TURBO_HOST_QML = ROOT / "ui" / "shell" / "TurboSurfaceHost.qml"
TURBO_CHROME_QML = ROOT / "ui" / "shell" / "TurboChromeWindow.qml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The legacy controls are gone (§V.1)
# ---------------------------------------------------------------------------
def test_the_turbo_checkbox_is_gone_from_settings():
    source = _read(SETTINGS_QML)
    assert "playback.turboMode" not in source, (
        "the Turbo checkbox was replaced by the Video mode dropdown (§V.1) and "
        "must never reappear as a user-facing control"
    )
    assert "Turbo Mode" not in source


def test_the_video_backend_dropdown_is_gone_from_settings():
    source = _read(SETTINGS_QML)
    assert "video.backend" not in source, (
        "the technical backend selector is removed from normal Settings (§V.1); "
        "it stays an internal Soft-chroma switch only"
    )
    assert "Video backend" not in source


def test_no_qml_still_reads_the_legacy_turbo_key():
    offenders = [
        qml.relative_to(ROOT)
        for d in ("ui", "modes")
        for qml in (ROOT / d).rglob("*.qml")
        if "playback.turboMode" in _read(qml)
    ]
    assert not offenders, f"legacy Turbo setting still read by: {offenders}"


def test_mini_mode_no_longer_saves_and_restores_a_turbo_checkbox():
    source = _read(MAIN_QML)
    assert "wasTurbo" not in source, (
        "Mini's old save/restore of playback.turboMode is replaced by the "
        "video-mode policy (App.setMiniMode)"
    )
    assert "App.setMiniMode(true)" in source
    assert "App.setMiniMode(false)" in source


# ---------------------------------------------------------------------------
# The dropdown is a real select with the right choices
# ---------------------------------------------------------------------------
def test_the_control_is_a_combobox_not_radios_or_icons():
    source = _read(SETTINGS_QML)
    assert "ComboBox {" in source
    block = source.split("id: videoModeCombo", 1)[1].split("\n                }\n", 1)[0]
    assert "RadioButton" not in block
    assert "IconButton" not in block


def test_the_label_is_video_mode():
    assert 'text: "Video mode"' in _read(SETTINGS_QML)


def test_the_choices_are_auto_soft_turbo_in_order():
    source = _read(SETTINGS_QML)
    assert 'readonly property var values: ["auto", "soft", "turbo"]' in source
    assert 'readonly property var labels: ["Auto", "Soft", "Turbo"]' in source


def test_the_dropdown_writes_the_new_setting_and_tells_the_controller():
    block = _read(SETTINGS_QML).split("id: videoModeCombo", 1)[1]
    assert 'Settings.set("playback.videoMode", value)' in block
    assert "App.setVideoMode(value)" in block


def test_a_mode_that_cannot_use_turbo_shows_a_disabled_soft():
    block = _read(SETTINGS_QML).split("id: videoModeRow", 1)[1]
    assert "App.videoModeEnabled" in block, "the enabled state comes from the mode"
    assert 'model: videoModeRow.interactive ? labels : ["Soft"]' in block, (
        "M3U must visibly display Soft rather than the stored Local preference"
    )
    assert "enabled: videoModeRow.interactive" in block


# ---------------------------------------------------------------------------
# Contrast (§V.1 — "clearly contrasting readable colours")
# ---------------------------------------------------------------------------
def test_the_closed_dropdown_has_an_opaque_backing():
    """A translucent glass tint over an animated background is exactly the
    low-contrast result §V.1 rules out."""
    block = _read(SETTINGS_QML).split("id: videoModeCombo", 1)[1]
    background = block.split("background: Rectangle", 1)[1].split("}", 1)[0]
    assert "Theme.baseElevated" in background
    assert "Theme.glassFill" not in background


def test_disabled_state_has_its_own_readable_pair():
    block = _read(SETTINGS_QML).split("id: videoModeCombo", 1)[1]
    assert "videoModeCombo.enabled ? Theme.text : Theme.textMuted" in block, (
        "disabled text must stay readable, not fade to Theme.textFaint"
    )
    assert "Qt.darker(Theme.baseElevated" in block, (
        "the disabled surface must be visibly different but still solid"
    )


def test_the_selected_item_is_marked_in_the_popup():
    block = _read(SETTINGS_QML).split("id: videoModePopupList", 1)[1]
    assert "videoModeCombo.currentIndex === index" in block, (
        "the current choice must read as chosen even when the pointer is "
        "somewhere else"
    )
    assert "Theme.accent" in block


# ---------------------------------------------------------------------------
# Soft is untouched (§V.2 — "forced Soft keeps the current path")
# ---------------------------------------------------------------------------
def test_the_soft_stage_is_unchanged():
    source = _read(VIDEO_STAGE_QML)
    assert "VideoSurface {" in source, "the callback surface is still the Soft path"
    assert "yuv420p.frag.qsb" in source, "the I420 shader path survives"
    assert "visible: !isPlanar" in source, "the RV32 fallback survives"
    assert "WindowContainer" not in source, (
        "Turbo must not be bolted onto the shared Soft stage — M3U uses this "
        "file too and never creates a native route (§V.3)"
    )


def test_soft_keeps_the_full_qml_blur():
    main = _read(MAIN_QML)
    assert "blurSource: window.chromeBlurSource" in main
    assert "readonly property var chromeBlurSource: (turboActive || chromeInOverlay) ? null : stage" in main, (
        "Soft must keep the Stage as a real backdrop; only Turbo — whose "
        "picture MultiEffect cannot sample — drops to a plain tint (§V.3). "
        "Blur must also stay off while chrome is still on the overlay, or "
        "turning Soft back on recreates MultiEffect across two windows."
    )
    glass = _read(ROOT / "ui" / "components" / "GlassPanel.qml")
    assert "MultiEffect" in glass and "blurEnabled: true" in glass
    assert "active: root.blurActive" in glass, (
        "MultiEffect must be destroyed when there is nothing to blur, so the "
        "chrome can move into the Turbo overlay without a cross-window sample"
    )
    assert "solidIfUnblurred" in glass
    assert "Theme.glassFillSolid" in glass


def test_the_engine_still_boots_on_the_soft_callbacks():
    source = (ROOT / "engine" / "vlc_engine.py").read_text(encoding="utf-8")
    assert "self.video_output.attach(self._player)" in source
    assert '"--avcodec-hw=none"' in source, (
        "the instance-wide guard for the vmem path must stay; Turbo overrides "
        "it per media, not globally"
    )


def test_the_hardware_override_is_scoped_to_one_media():
    source = (ROOT / "engine" / "vlc_engine.py").read_text(encoding="utf-8")
    assert 'self._set_player_option("avcodec-hw", "d3d11va")' in source
    assert "media.add_option(option)" in source


# ---------------------------------------------------------------------------
# The Turbo boundary in QML (§V.3)
# ---------------------------------------------------------------------------
def test_turbo_is_embedded_with_a_window_container():
    source = _read(TURBO_HOST_QML)
    assert "WindowContainer {" in source
    assert "container.window = w" in source
    assert "App.noteTurboEmbedded" in source
    assert "readonly property rect pictureRect" in source, (
        "the native HWND must cover only the picture so the letterbox is "
        "QML black, not a hole through to the desktop"
    )
    assert "x: root.pictureRect.x" in source
    assert "anchors.fill: parent" not in source.split("WindowContainer {", 1)[1]


def test_the_turbo_host_reports_every_embedding_failure():
    source = _read(TURBO_HOST_QML)
    assert source.count("root.failed(") >= 4, (
        "no window, a raising provider, a rejecting container and a silent "
        "non-adoption must each be reported so the engine can fall back (§V.4)"
    )
    main = _read(MAIN_QML)
    assert "onFailed: function(reason) { window.reportTurboFailure(reason) }" in main
    assert "App.reportTurboFailure" in main


def test_the_turbo_host_releases_the_child_before_it_goes_away():
    source = _read(TURBO_HOST_QML)
    assert "Component.onDestruction: detach()" in source
    assert "container.window = null" in source


def test_turbo_only_exists_while_the_engine_says_it_is_running():
    main = _read(MAIN_QML)
    assert 'readonly property bool turboActive: effectiveVideoMode === "turbo"' in main
    assert "turboActive: window.turboActive" in main
    assert "active: window.turboActive && !window.miniModeActive" in main, (
        "Mini Mode runs on Soft, so the overlay must not be built there either"
    )


def test_transparent_quick_windows_request_an_alpha_buffer_before_startup():
    """The Turbo overlay's D3D swapchain and QQuickWindow must agree on alpha."""
    bootstrap = _read(ROOT / "main.py")
    alpha_policy = bootstrap.index("QQuickWindow.setDefaultAlphaBuffer(True)")
    app_creation = bootstrap.index("app = QGuiApplication(argv)")
    assert alpha_policy < app_creation, (
        "QQuickWindow's alpha policy must be set before any window can be "
        "created, otherwise TurboChromeWindow gets an incompatible swapchain"
    )
    assert "surface_format.setAlphaBufferSize(8)" in bootstrap


def test_overlay_stage_click_only_runs_while_chrome_is_in_the_turbo_overlay():
    """The catcher is Turbo-overlay furniture, not a permanent shell sheet."""
    main = _read(MAIN_QML)
    block = main.split("id: overlayStageClick", 1)[1].split("onClicked", 1)[0]
    assert "enabled: window.chromeInOverlay" in block
    assert "visible: window.chromeInOverlay" in block
    assert "hoverEnabled: window.chromeInOverlay" in block


def test_move_chrome_home_drops_the_catcher_before_reparenting():
    """chromeInOverlay must go false before chromeLayer returns to body."""
    main = _read(MAIN_QML)
    body = main.split("function moveChromeHome()", 1)[1].split("function ", 1)[0]
    drop = body.index("chromeInOverlay = false")
    reparent = body.index("chromeLayer.parent = body")
    assert drop < reparent, (
        "the video click catcher must turn off before chrome re-enters "
        "the main window, or Web takes a frame of stolen clicks"
    )


def test_settings_is_seated_on_the_turbo_overlay_not_under_the_hwnd():
    """A Dialog left on the shell Overlay paints under the native HWND (§V.3).

    The chrome overlay already sits above that HWND. Settings must open
    there while Turbo is live, and must come home before the overlay
    Window is destroyed — otherwise the gear buries the dialog, or
    leaving Turbo destroys an open Settings with the overlay.
    """
    main = _read(MAIN_QML)
    assert "function settingsHostWindow()" in main
    assert "function seatSettingsDialog()" in main
    assert "objectName: \"settingsDialog\"" in main

    # The gear path must seat first; opening on the shell is the bug.
    window_show = None
    for chunk in main.split("function showSettings()"):
        if "seatSettingsDialog" in chunk and "settingsDialog.open()" in chunk:
            window_show = chunk
            break
    assert window_show is not None, "window.showSettings() must seat then open"
    assert window_show.index("seatSettingsDialog") < window_show.index(
        "settingsDialog.open()"
    )
    assert "function showSettings()    { window.showSettings() }" in main, (
        "the Actions gear must use the seating path, not open() directly"
    )

    to_overlay = main.split("function moveChromeToOverlay()", 1)[1].split(
        "function ", 1
    )[0]
    assert "seatSettingsDialog()" in to_overlay, (
        "Settings already open on the shell must move up with the chrome"
    )

    home = main.split("function moveChromeHome()", 1)[1].split("function ", 1)[0]
    seat = home.index("seatSettingsDialog()")
    reparent = home.index("chromeLayer.parent = body")
    assert reparent < seat, (
        "bring chrome home first, then seat Settings, while the overlay "
        "Window still exists (Loader.onActiveChanged is before destroy)"
    )


def test_the_chrome_moves_into_a_transparent_overlay_window():
    """QML siblings cannot paint over a native child window (§V.3)."""
    chrome = _read(TURBO_CHROME_QML)
    assert 'color: "transparent"' in chrome
    assert "transientParent: hostWindow" in chrome
    main = _read(MAIN_QML)
    assert "chromeLayer.parent = overlay.hostItem" in main
    assert "function moveChromeHome()" in main
    assert "window.moveChromeHome()" in main, (
        "the controls must come home before the overlay window is destroyed"
    )
    assert "chromeMoveTimer" in main, (
        "the chrome must not reparent on the same frame the overlay is built "
        "— MultiEffect has to be destroyed first"
    )
    assert "chromeInOverlay = true" in main
    assert "chromeInOverlay = false" in main
    assert "turboLetterbox" in main, (
        "the body must paint an opaque letterbox behind the native surface "
        "so a gap never shows the desktop"
    )
    assert 'color: (turboActive && !miniModeActive) ? "#000000" : "transparent"' in main, (
        "a layered transparent window plus a native HWND punches through to "
        "the desktop — Turbo must make the shell opaque"
    )
    assert "App.sealTurboHost" in main, (
        "painting the window black is not enough — the Win32 layered style "
        "must come off while Turbo is on"
    )
    assert "App.unsealTurboHost" in main, (
        "Soft must get the glass/layered shell back when Turbo ends"
    )
    assert "videoWidth: window.turboVideoWidth" in main


def test_there_is_still_exactly_one_transport_bar_and_one_osd():
    """The overlay hosts the *same* chrome, it does not clone it (§4.1)."""
    main = _read(MAIN_QML)
    assert main.count("id: transportLoader") == 1
    assert main.count("id: osdLayer") == 1
    assert main.count("id: panelHost") == 1
    assert main.count("id: infoPanel") == 1


def test_no_second_player_is_ever_created():
    for module in ("engine/vlc_engine.py", "engine/turbo_surface.py"):
        source = (ROOT / module).read_text(encoding="utf-8")
        assert source.count("media_player_new()") <= 1, (
            f"{module} creates more than one media player — §V.2 allows exactly one"
        )
    assert "media_player_new" not in _read(TURBO_HOST_QML)


def test_docks_ask_for_a_solid_fill_when_unblurred():
    """Turbo has no blur backdrop; 6% glass would be invisible over video."""
    panel = _read(ROOT / "ui" / "shell" / "PanelHost.qml")
    info = _read(ROOT / "ui" / "panels" / "InfoPanel.qml")
    theme = _read(ROOT / "ui" / "Theme.qml")
    assert "solidIfUnblurred: true" in panel
    assert "solidIfUnblurred: true" in info
    assert "property color glassFillSolid" in theme


def test_the_new_shell_types_are_registered():
    qmldir = (ROOT / "Halcyon" / "Shell" / "qmldir").read_text(encoding="utf-8")
    assert "TurboSurfaceHost 1.0 ../../ui/shell/TurboSurfaceHost.qml" in qmldir
    assert "TurboChromeWindow 1.0 ../../ui/shell/TurboChromeWindow.qml" in qmldir


# ---------------------------------------------------------------------------
# Live: the control really exists, in the states §V.1 describes
# ---------------------------------------------------------------------------
from tests.conftest import GUI_AVAILABLE  # noqa: E402


gui_only = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)


def _controller_stub(base, *, available: bool, enabled: bool, mode: str):
    """An App double whose video-mode answers are real Qt properties.

    ``_Stub.__getattr__`` resolves anything unknown to a no-op callable, which
    is convenient for the dozens of actions the window calls — but QML reads
    properties through the meta-object, where a plain Python attribute is
    simply absent. An absent property makes `App.videoModeEnabled !== undefined`
    false and the dialog falls back to its "assume Local" default, so a test
    written that way would pass no matter what the dialog does. These have to be
    declared properties.
    """
    from PySide6.QtCore import Property

    class _ControllerStub(base):
        @Property(bool, constant=True)
        def videoModeAvailable(self):
            return available

        @Property(bool, constant=True)
        def videoModeEnabled(self):
            return enabled

        @Property(str, constant=True)
        def videoMode(self):
            return mode

        @Property(str, constant=True)
        def effectiveVideoMode(self):
            return "soft"

    return _ControllerStub


@pytest.fixture(scope="module")
def settings_dialog(gui_app):
    """The real Settings dialog, built the way the window builds it."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine

    from core.settings import Settings
    from tests.test_fullscreen_chrome import _Stub

    _App = _controller_stub(_Stub, available=True, enabled=True, mode="auto")

    qml_engine = QQmlApplicationEngine()
    qml_engine.addImportPath(str(ROOT))
    stub = _App()
    settings = Settings()
    ctx = qml_engine.rootContext()
    for name in ("App", "Player", "Metadata", "Lyrics", "Library", "Equalizer",
                 "Subs", "UpdateChecker", "RemoteBridge"):
        ctx.setContextProperty(name, stub)
    ctx.setContextProperty("Settings", settings)

    qml_engine.loadData(
        b"""
        import QtQuick
        import QtQuick.Controls.Basic
        import Halcyon.Panels
        Window { width: 600; height: 700; SettingsDialog { id: dlg; visible: true } }
        """,
        QUrl.fromLocalFile(str(ROOT / "inline.qml")),
    )
    roots = qml_engine.rootObjects()
    assert roots, "the Settings dialog failed to load"
    roots[0]._refs = (qml_engine, stub, settings)
    yield roots[0]
    del qml_engine


def _combo(root):
    from PySide6.QtQuick import QQuickItem

    for child in root.findChildren(QQuickItem):
        if child.objectName() == "videoModeCombo":
            return child
    return None


@gui_only
def test_the_dropdown_is_really_there_and_enabled_in_local(settings_dialog):
    combo = _combo(settings_dialog)
    assert combo is not None, "no Video mode dropdown in the Settings dialog"
    assert combo.property("enabled") is True
    assert combo.property("visible") is True


@gui_only
def test_the_dropdown_really_offers_three_choices(settings_dialog):
    combo = _combo(settings_dialog)
    assert list(combo.property("model")) == ["Auto", "Soft", "Turbo"]


@gui_only
def test_the_dropdown_shows_the_stored_choice(settings_dialog):
    combo = _combo(settings_dialog)
    assert combo.property("displayText") in ("Auto", "Soft", "Turbo")


@gui_only
def test_the_default_selection_is_auto(settings_dialog):
    from core.settings import DEFAULTS

    assert DEFAULTS["playback.videoMode"] == "auto"
    combo = _combo(settings_dialog)
    settings = settings_dialog._refs[2]
    if settings.get("playback.videoMode") == "auto":
        assert combo.property("currentIndex") == 0
        assert combo.property("displayText") == "Auto"


@pytest.fixture(scope="module")
def m3u_settings_dialog(gui_app):
    """The same dialog with a controller that answers the way M3U does.

    A stored preference of "turbo" on purpose: §V.1's rule is that M3U shows
    Soft *regardless* of it.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine

    from core.settings import Settings
    from tests.test_fullscreen_chrome import _Stub

    _M3UApp = _controller_stub(_Stub, available=True, enabled=False, mode="turbo")

    qml_engine = QQmlApplicationEngine()
    qml_engine.addImportPath(str(ROOT))
    stub = _M3UApp()
    settings = Settings()
    settings.set("playback.videoMode", "turbo")
    ctx = qml_engine.rootContext()
    for name in ("App", "Player", "Metadata", "Lyrics", "Library", "Equalizer",
                 "Subs", "UpdateChecker", "RemoteBridge"):
        ctx.setContextProperty(name, stub)
    ctx.setContextProperty("Settings", settings)

    qml_engine.loadData(
        b"""
        import QtQuick
        import QtQuick.Controls.Basic
        import Halcyon.Panels
        Window { width: 600; height: 700; SettingsDialog { id: dlg; visible: true } }
        """,
        QUrl.fromLocalFile(str(ROOT / "inline_m3u.qml")),
    )
    roots = qml_engine.rootObjects()
    assert roots, "the Settings dialog failed to load"
    roots[0]._refs = (qml_engine, stub, settings)
    yield roots[0]
    settings.set("playback.videoMode", "auto")
    del qml_engine


@gui_only
def test_in_m3u_the_dropdown_is_visible_but_disabled(m3u_settings_dialog):
    combo = _combo(m3u_settings_dialog)
    assert combo is not None, "the row must not disappear in M3U — it is informational"
    assert combo.property("visible") is True
    assert combo.property("enabled") is False


@gui_only
def test_in_m3u_the_dropdown_reads_soft_despite_a_stored_turbo(m3u_settings_dialog):
    combo = _combo(m3u_settings_dialog)
    assert list(combo.property("model")) == ["Soft"]
    assert combo.property("displayText") == "Soft"


# ---------------------------------------------------------------------------
# Live: the Soft <-> Turbo transition in the real window
#
# The structural checks above read the file; these drive it. What they catch
# that a text search cannot: the chrome failing to come back out of the overlay
# window (controls stranded in a window that is being destroyed), and the
# container never actually adopting the native child.
#
# This exercises the *shell's* half of Turbo — reparenting and embedding — with
# a plain QWindow standing in for libVLC's child. It does not, and cannot,
# verify Windows HWND embedding.
# ---------------------------------------------------------------------------
@pytest.fixture
def turbo_window(gui_app):
    from PySide6.QtCore import Property, QUrl, Qt, Signal, Slot
    from PySide6.QtGui import QWindow
    from PySide6.QtQml import QQmlApplicationEngine

    import engine.surface  # noqa: F401 - registers VideoSurface
    from core.app import ModeList
    from core.settings import Settings
    from modes.local.playlist import PlaylistModel
    from tests.test_fullscreen_chrome import _Stub

    class _RouteApp(_Stub):
        routeChanged = Signal()

        def __init__(self) -> None:
            super().__init__()
            self._route = "soft"
            self._native = None
            self.failures: list[str] = []

        @Property(str, notify=routeChanged)
        def effectiveVideoMode(self):
            return self._route

        def go(self, route: str) -> None:
            self._route = route
            self.routeChanged.emit()

        @Slot(result="QVariant")
        def turboWindow(self):
            if self._native is None:
                self._native = QWindow()
                self._native.setFlags(Qt.FramelessWindowHint)
                self._native.create()
            return self._native

        @Slot(str)
        def reportTurboFailure(self, reason):
            self.failures.append(reason)

        @Property(int, constant=True)
        def videoWidth(self):
            return 1920

        @Property(int, constant=True)
        def videoHeight(self):
            return 1080

        @Slot("QVariant")
        def sealTurboHost(self, _window):
            self.sealed = getattr(self, "sealed", 0) + 1

        @Slot("QVariant")
        def unsealTurboHost(self, _window):
            self.unsealed = getattr(self, "unsealed", 0) + 1

    qml_engine = QQmlApplicationEngine()
    qml_engine.addImportPath(str(ROOT))
    stub = _RouteApp()
    settings = Settings()
    modes = ModeList()
    playlist = PlaylistModel()
    ctx = qml_engine.rootContext()
    for name in ("App", "Player", "Metadata", "Lyrics", "Library", "Equalizer"):
        ctx.setContextProperty(name, stub)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("Modes", modes)
    ctx.setContextProperty("LocalPlaylist", playlist)

    qml_engine.load(QUrl.fromLocalFile(str(ROOT / "ui" / "Main.qml")))
    roots = qml_engine.rootObjects()
    assert roots, "ui/Main.qml failed to load"
    window = roots[0]
    window._refs = (qml_engine, stub, settings, modes, playlist)
    yield window, stub
    stub.go("soft")
    del qml_engine


def _named(root, name):
    from PySide6.QtCore import QObject

    for child in root.findChildren(QObject):
        if child.objectName() == name:
            return child
    return None


@gui_only
def test_the_shell_starts_on_soft_with_no_native_container(turbo_window):
    window, _stub = turbo_window
    assert window.property("turboActive") is False
    container = _named(window, "turboWindowContainer")
    if container is not None:
        assert container.property("window") is None


@gui_only
def test_turbo_embeds_the_native_child_and_moves_the_chrome(turbo_window):
    from PySide6.QtTest import QTest

    window, stub = turbo_window
    chrome = _named(window, "chromeLayer")
    home = chrome.parentItem()

    stub.go("turbo")
    QTest.qWait(300)

    assert window.property("turboActive") is True
    container = _named(window, "turboWindowContainer")
    assert container is not None, "no WindowContainer was created for Turbo"
    assert container.property("window") is not None, (
        "the container did not adopt the native child — Turbo would show "
        "nothing (§V.3)"
    )
    assert chrome.parentItem() is not home, "the chrome stayed under the native surface"
    assert chrome.parentItem().objectName() == "turboChromeHost"
    assert window.property("chromeInOverlay") is True
    letterbox = _named(window, "turboLetterbox")
    assert letterbox is not None and letterbox.property("visible") is True
    shell_color = window.color() if callable(getattr(window, "color", None)) else window.color
    assert shell_color.alpha() == 255, (
        "Turbo must make the shell opaque so the native HWND cannot punch "
        "through to the desktop"
    )
    assert not stub.failures, f"unexpected Turbo failures: {stub.failures}"
    assert getattr(stub, "sealed", 0) >= 1, "windowed Turbo must seal the host HWND"


@gui_only
def test_returning_to_soft_brings_the_chrome_home_intact(turbo_window):
    from PySide6.QtTest import QTest

    window, stub = turbo_window
    chrome = _named(window, "chromeLayer")
    home = chrome.parentItem()

    stub.go("turbo")
    QTest.qWait(300)
    stub.go("soft")
    QTest.qWait(300)

    assert window.property("turboActive") is False
    assert getattr(stub, "unsealed", 0) >= 1, "leaving Turbo must restore the glass shell"
    assert chrome.parentItem() is home, (
        "the transport bar, docks and OSD must come back to the main window — "
        "leaving them in a destroyed overlay is a window with no controls"
    )
    assert chrome.width() > 0 and chrome.height() > 0, (
        "the chrome came home with no size; its anchors did not survive the "
        "round trip"
    )
    assert window.property("chromeInOverlay") is False


@gui_only
def test_a_missing_native_window_is_reported_not_silently_blank(turbo_window):
    from PySide6.QtTest import QTest

    window, stub = turbo_window
    stub.turboWindow = lambda: None      # the engine produced nothing

    stub.go("turbo")
    QTest.qWait(300)

    assert stub.failures, (
        "an un-embeddable Turbo must be reported so the engine can continue "
        "the media on Soft (§V.4), not leave a blank stage"
    )


def _settings_dialog(root):
    return _named(root, "settingsDialog")


@gui_only
def test_settings_on_soft_stays_on_the_main_window(turbo_window):
    """Soft has no HWND. Settings must keep opening on the shell Overlay."""
    from PySide6.QtCore import QMetaObject, Qt
    from PySide6.QtTest import QTest

    window, _stub = turbo_window
    assert window.property("turboActive") is False
    assert QMetaObject.invokeMethod(window, "showSettings", Qt.DirectConnection)
    QTest.qWait(50)

    dlg = _settings_dialog(window)
    assert dlg is not None
    assert dlg.property("visible") is True
    assert dlg.window() is window


@gui_only
def test_settings_on_turbo_opens_in_the_chrome_overlay(turbo_window):
    """The reported bug: gear during Turbo buried Settings under the video."""
    from PySide6.QtCore import QMetaObject, Qt
    from PySide6.QtTest import QTest

    window, stub = turbo_window
    stub.go("turbo")
    QTest.qWait(300)

    assert window.property("chromeInOverlay") is True
    assert QMetaObject.invokeMethod(window, "showSettings", Qt.DirectConnection)
    QTest.qWait(50)

    dlg = _settings_dialog(window)
    assert dlg is not None, "Settings vanished after seating on the overlay"
    assert dlg.property("visible") is True
    host = _named(window, "turboChromeHost")
    assert host is not None
    assert dlg.window() is host.window(), (
        "Settings must open in the stay-on-top chrome overlay, not under "
        "the native video HWND"
    )
    assert dlg.window() is not window


@gui_only
def test_settings_returns_home_when_turbo_ends(turbo_window):
    """An open dialog must not be destroyed with the overlay Window."""
    from PySide6.QtCore import QMetaObject, Qt
    from PySide6.QtTest import QTest

    window, stub = turbo_window
    stub.go("turbo")
    QTest.qWait(300)
    assert QMetaObject.invokeMethod(window, "showSettings", Qt.DirectConnection)
    QTest.qWait(50)
    assert _settings_dialog(window).window() is not window

    stub.go("soft")
    QTest.qWait(300)

    dlg = _settings_dialog(window)
    assert dlg is not None, "leaving Turbo destroyed Settings with the overlay"
    assert dlg.property("visible") is True, (
        "an already-open Settings must come back with the chrome, not close"
    )
    assert dlg.window() is window
