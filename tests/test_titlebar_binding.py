"""The title bar's ``mediaTitle`` binding, against the real QML.

``test_chrome_behaviour.py`` checks the *rules* in Main.qml as text. This file
checks the one piece of real logic — how a title, an artist and the player's
current media combine into the line the user reads — by loading
``ui/shell/TitleBar.qml`` into a live QQmlEngine and driving it with fake
Metadata and Player objects.

That needs QtGui, so the module skips on a headless box (see tests/conftest.py)
rather than failing there. On Windows, where Halcyon actually runs, it always
executes.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Property, QObject, QUrl, Signal

from tests.conftest import GUI_AVAILABLE, ROOT

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

if GUI_AVAILABLE:
    from PySide6.QtQml import QQmlComponent, QQmlEngine


class FakeMetadata(QObject):
    changed = Signal()

    def __init__(self, title="", artist="", album=""):
        super().__init__()
        self._t, self._a, self._al = title, artist, album

    def update(self, title, artist="", album=""):
        self._t, self._a, self._al = title, artist, album
        self.changed.emit()

    @Property(str, notify=changed)
    def title(self):
        return self._t

    @Property(str, notify=changed)
    def artist(self):
        return self._a

    @Property(str, notify=changed)
    def album(self):
        return self._al

    @Property(str, notify=changed)
    def artworkUrl(self):
        return ""


class FakePlayer(QObject):
    mediaChanged = Signal(str)

    def __init__(self, mrl=""):
        super().__init__()
        self._mrl = mrl

    def set_media(self, mrl):
        self._mrl = mrl
        self.mediaChanged.emit(mrl)

    @Property(str, notify=mediaChanged)
    def currentMedia(self):
        return self._mrl


@pytest.fixture()
def title_bar(gui_app):
    """The real TitleBar.qml, with fake Metadata/Player injected."""
    engine = QQmlEngine()
    engine.addImportPath(str(ROOT))

    meta = FakeMetadata()
    player = FakePlayer()

    component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "ui" / "shell" / "TitleBar.qml")))
    if component.isError():
        pytest.fail("TitleBar.qml did not compile:\n"
                    + "\n".join(e.toString() for e in component.errors()))

    item = component.create()
    assert item is not None, "TitleBar.qml failed to instantiate"
    item.setProperty("meta", meta)
    item.setProperty("player", player)
    # Keep the Python owners alive for the life of the test.
    item._refs = (engine, component, meta, player)
    return item, meta, player


# ------------------------------------------------------------- title bar ---
def test_nothing_playing_shows_no_title(title_bar):
    item, _meta, _player = title_bar

    assert item.property("mediaTitle") == "", (
        "with nothing loaded the bar must fall back to the bare wordmark, not "
        "show a stray separator"
    )


def test_the_playing_title_is_shown(title_bar):
    item, meta, player = title_bar
    player.set_media("file:///m/Arrival.mkv")
    meta.update("Arrival")

    assert item.property("mediaTitle") == "Arrival"


def test_artist_and_title_are_combined(title_bar):
    item, meta, player = title_bar
    player.set_media("file:///m/song.flac")
    meta.update("Weightless", artist="Marconi Union")

    assert item.property("mediaTitle") == "Marconi Union  \u2014  Weightless"


def test_a_title_with_no_artist_stands_alone(title_bar):
    """Most video files carry a title and no artist tag."""
    item, meta, player = title_bar
    player.set_media("file:///m/Arrival.mkv")
    meta.update("Arrival", artist="")

    assert item.property("mediaTitle") == "Arrival", "no leading em-dash"


def test_the_title_updates_when_the_track_changes(title_bar):
    """It is a binding, not a one-shot read."""
    item, meta, player = title_bar
    player.set_media("file:///m/a.mp3")
    meta.update("First", artist="A")
    assert item.property("mediaTitle") == "A  \u2014  First"

    player.set_media("file:///m/b.mp3")
    meta.update("Second", artist="B")

    assert item.property("mediaTitle") == "B  \u2014  Second"


def test_stopping_clears_the_title(title_bar):
    """Metadata keeps the last track's tags until the next parse lands.

    Keying off the player's current media as well is what stops the bar
    advertising a track that has already been stopped.
    """
    item, meta, player = title_bar
    player.set_media("file:///m/a.mp3")
    meta.update("First", artist="A")
    assert item.property("mediaTitle") != ""

    player.set_media("")

    assert item.property("mediaTitle") == ""


def test_an_untagged_file_shows_nothing_rather_than_a_separator(title_bar):
    item, meta, player = title_bar
    player.set_media("file:///m/raw.wav")
    meta.update("", artist="Someone")

    assert item.property("mediaTitle") == ""


