"""Auto-hide behaviour, driven by real pointer events against the real window.

``test_chrome_behaviour.py`` reads the rules out of Main.qml as text. That
catches a rule being deleted; it cannot catch the rules being *right* and the
behaviour still being wrong. This file builds the actual window and delivers
actual ``QMouseEvent``s through it.

The bug that made this file necessary
-------------------------------------
Gating auto-hide on fullscreen and blanking the cursor both looked correct, and
a test that called ``wakeChrome()`` directly agreed. But ``positionChanged``
does not mean "the user moved the mouse" — it also fires when a MouseArea
appears under a stationary pointer, and when the scene relayouts beneath one.
Hiding the bar does both at once (the blanker appears, the stage resizes), so
the hide immediately produced a synthetic move, which woke the chrome, which
2.5 s later hid it again: a permanent 2.5 s flicker in fullscreen, and the
cursor never actually staying hidden.

Only an event-level test sees that, which is why these drive the window rather
than the functions. The "still hidden 1.5 s later" assertion is the specific one
that fails on a flicker.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Property, QEvent, QObject, QPointF, Qt, QTimer, QUrl, Signal

from tests.conftest import GUI_AVAILABLE, ROOT

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

if GUI_AVAILABLE:
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtQml import QQmlApplicationEngine


#: The bar hides ``ui.autoHideDelayMs`` (2.5 s) after the last real move. Waits
#: are that plus a margin, so these tests are inherently a few seconds long.
AUTO_HIDE_MS = 2500
SETTLE_MS = 1200


class _Stub(QObject):
    """Stands in for App, Player, Metadata, Library, Lyrics and Equalizer.

    One object for all of them: the window only ever reads properties off these,
    and an unknown attribute resolving to a no-op callable is closer to the real
    thing than six hand-written doubles would be.
    """

    changed = Signal()
    mediaChanged = Signal(str)
    stateChanged = Signal(int)
    tracksChanged = Signal()
    timeChanged = Signal(int)
    durationChanged = Signal(int)
    positionChanged = Signal(float)
    volumeChanged = Signal(int)
    mutedChanged = Signal(bool)
    rateChanged = Signal(float)
    endReached = Signal()
    errorOccurred = Signal(str)
    subtitleDelayChanged = Signal()
    activeModeChanged = Signal()
    resumePrompted = Signal(str, int)
    playlistPlaybackCleared = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.playing = True

    def __getattr__(self, name):
        return lambda *a, **k: None

    def set_playing(self, playing: bool) -> None:
        self.playing = playing
        self.stateChanged.emit(3 if playing else 4)

    @Property(bool, notify=stateChanged)
    def isPlaying(self):
        return self.playing

    @Property(int, notify=stateChanged)
    def state(self):
        return 3 if self.playing else 4

    @Property(str, notify=changed)
    def title(self):
        return "Test Track"

    @Property(str, notify=changed)
    def artist(self):
        return "Test Artist"

    @Property(str, notify=changed)
    def album(self):
        return ""

    @Property(str, notify=changed)
    def artworkUrl(self):
        return ""

    @Property(str, notify=mediaChanged)
    def currentMedia(self):
        return "file:///test.mkv"

    @Property(float, notify=positionChanged)
    def position(self):
        return 0.3

    @Property(int, notify=timeChanged)
    def time(self):
        return 1000

    @Property(int, notify=durationChanged)
    def duration(self):
        return 10000

    @Property(int, notify=volumeChanged)
    def volume(self):
        return 80

    @Property(bool, notify=mutedChanged)
    def muted(self):
        return False

    @Property(float, notify=rateChanged)
    def rate(self):
        return 1.0

    @Property(str, notify=activeModeChanged)
    def activeMode(self):
        return "local"

    @Property("QVariantList", notify=tracksChanged)
    def audioTracks(self):
        return []

    @Property("QVariantList", notify=tracksChanged)
    def subtitleTracks(self):
        return []

    @Property("QVariantList", notify=changed)
    def details(self):
        return []

    @Property(int, notify=subtitleDelayChanged)
    def subtitleDelayMs(self):
        return 0


class Harness:
    """The live window, plus the few things a test needs to poke at it."""

    def __init__(self, app):
        self.app = app
        self.engine = QQmlApplicationEngine()
        self.engine.addImportPath(str(ROOT))

        from core.app import ModeList
        from core.settings import Settings
        from modes.local.playlist import PlaylistModel

        import engine.surface  # noqa: F401 - registers VideoSurface with QML

        self.stub = _Stub()
        self.settings = Settings()
        self.modes = ModeList()
        self.playlist = PlaylistModel()

        ctx = self.engine.rootContext()
        for name in ("App", "Player", "Metadata", "Lyrics", "Library", "Equalizer"):
            ctx.setContextProperty(name, self.stub)
        ctx.setContextProperty("Settings", self.settings)
        ctx.setContextProperty("Modes", self.modes)
        ctx.setContextProperty("LocalPlaylist", self.playlist)

        self.warnings: list[str] = []
        self.engine.warnings.connect(
            lambda ws: self.warnings.extend(w.toString() for w in ws)
        )
        self.engine.load(QUrl.fromLocalFile(str(ROOT / "ui" / "Main.qml")))
        roots = self.engine.rootObjects()
        assert roots, "ui/Main.qml failed to load"
        self.window = roots[0]

    # -- driving ----------------------------------------------------------
    def move_mouse(self, x: float, y: float) -> None:
        """A genuine pointer move, delivered the way the OS delivers one.

        Calling ``wakeChrome()`` instead is what let the flicker bug through:
        it bypasses precisely the handler that was wrong.
        """
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(x, y),
            QPointF(x, y),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.app.sendEvent(self.window, event)
        self.app.processEvents()

    def wait(self, ms: int) -> None:
        """Spin the real event loop, so QML Timers actually fire."""
        done = []
        QTimer.singleShot(ms, lambda: done.append(True))
        while not done:
            self.app.processEvents()

    def set_fullscreen(self, on: bool) -> None:
        self.window.setFullscreen(on)
        self.app.processEvents()

    # -- reading ----------------------------------------------------------
    @property
    def chrome_visible(self) -> bool:
        return bool(self.window.property("chromeVisible"))

    @property
    def cursor_hidden(self) -> bool:
        """True when the blanking MouseArea is live (Qt.BlankCursor == 10)."""
        for child in self.window.findChildren(QObject):
            if not child.metaObject().className().startswith("QQuickMouseArea"):
                continue
            shape = child.property("cursorShape")
            if getattr(shape, "value", shape) == 10:
                return bool(child.property("visible"))
        return False

    @property
    def binding_loops(self) -> list[str]:
        return [w for w in self.warnings if "loop" in w.lower()]


@pytest.fixture(scope="module")
def harness(gui_app):
    h = Harness(gui_app)
    yield h

    # Tear the playlist's probe workers down explicitly.
    #
    # PlaylistModel.shutdown() sets the flag that stops queued duration probes,
    # and the app calls it on quit. A test that builds a model and just drops it
    # leaves those QRunnables live in the global pool; each one spins up a real
    # libVLC instance, so on a machine without libVLC they crash a pool thread
    # after the run has finished — an intermittent segfault with a passing
    # result line above it. Waiting for the pool to drain makes it deterministic.
    from PySide6.QtCore import QThreadPool

    h.playlist.shutdown()
    QThreadPool.globalInstance().waitForDone(5000)


@pytest.fixture(autouse=True)
def _reset(harness):
    """Every test starts windowed, playing, chrome up."""
    harness.stub.set_playing(True)
    harness.set_fullscreen(False)
    harness.move_mouse(400, 300)
    harness.app.processEvents()
    yield


# ------------------------------------------------------------- windowed ---
def test_the_bar_never_hides_in_windowed_mode(harness):
    """The reported bug. Windowed playback must keep its controls."""
    harness.move_mouse(400, 300)
    harness.wait(AUTO_HIDE_MS + SETTLE_MS)

    assert harness.chrome_visible, "the transport bar hid in windowed mode"
    assert not harness.cursor_hidden, "the cursor was blanked in windowed mode"


# ----------------------------------------------------------- fullscreen ---
def test_the_bar_and_cursor_hide_in_fullscreen(harness):
    harness.set_fullscreen(True)
    harness.move_mouse(400, 300)
    harness.wait(AUTO_HIDE_MS + SETTLE_MS)

    assert not harness.chrome_visible, "the bar should hide in fullscreen"
    assert harness.cursor_hidden, "the cursor should be blanked in fullscreen"


def test_the_chrome_stays_hidden_and_does_not_flicker(harness):
    """The regression guard for the synthetic-positionChanged loop.

    Hiding the bar makes a MouseArea appear under the pointer and relayouts the
    stage beneath it. Both emit positionChanged with the mouse untouched, and
    waking on those re-showed the chrome immediately — so fullscreen oscillated
    on a 2.5 s cycle instead of settling.
    """
    harness.set_fullscreen(True)
    harness.move_mouse(400, 300)
    harness.wait(AUTO_HIDE_MS + SETTLE_MS)
    assert not harness.chrome_visible, "precondition: the bar hid"

    harness.wait(1500)

    assert not harness.chrome_visible, (
        "the chrome came back on its own — a synthetic pointer event is waking "
        "it, which means fullscreen flickers forever"
    )
    assert harness.cursor_hidden, "the cursor reappeared on its own"


def test_a_real_mouse_move_brings_everything_back(harness):
    harness.set_fullscreen(True)
    harness.move_mouse(400, 300)
    harness.wait(AUTO_HIDE_MS + SETTLE_MS)
    assert not harness.chrome_visible

    harness.move_mouse(700, 500)

    assert harness.chrome_visible, "a real move must wake the chrome"
    assert not harness.cursor_hidden, "a real move must restore the cursor"


def test_it_hides_again_after_the_pointer_settles(harness):
    """Waking must re-arm the timer, not disable auto-hide for good."""
    harness.set_fullscreen(True)
    harness.move_mouse(400, 300)
    harness.wait(AUTO_HIDE_MS + SETTLE_MS)
    harness.move_mouse(700, 500)
    assert harness.chrome_visible

    harness.wait(AUTO_HIDE_MS + SETTLE_MS)

    assert not harness.chrome_visible, "the bar must hide again once idle"


def test_pausing_reveals_the_chrome(harness):
    """Never leave a paused player with no visible controls."""
    harness.set_fullscreen(True)
    harness.move_mouse(400, 300)
    harness.wait(AUTO_HIDE_MS + SETTLE_MS)
    assert not harness.chrome_visible

    harness.stub.set_playing(False)
    harness.wait(300)

    assert harness.chrome_visible, "pausing must bring the bar back"
    assert not harness.cursor_hidden, "pausing must bring the cursor back"


def test_leaving_fullscreen_restores_the_chrome(harness):
    """Exiting while hidden must not leave a window with no controls."""
    harness.set_fullscreen(True)
    harness.move_mouse(400, 300)
    harness.wait(AUTO_HIDE_MS + SETTLE_MS)
    assert not harness.chrome_visible

    harness.set_fullscreen(False)

    assert harness.chrome_visible, "left a window with no transport bar"
    assert not harness.cursor_hidden, "left a window with no cursor"

    harness.wait(AUTO_HIDE_MS + SETTLE_MS)
    assert harness.chrome_visible, "and it must stay visible once windowed"


# ---------------------------------------------------------------- sanity ---
def test_the_window_produces_no_binding_loops(harness):
    """The title bar measures itself against the mode chips, which is exactly
    the shape of layout that produces one if it is written carelessly."""
    assert harness.binding_loops == [], harness.binding_loops
