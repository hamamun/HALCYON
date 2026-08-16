"""A playlist you removed must stay removed — including after a restart.

Two user-visible failures are pinned here.

**Clear playlist.** The panel button (and the Delete key, and the mobile
remote) emptied the channel list but left ``mode.m3u.lastSource`` pointing at
it. That setting is what M3U reloads the first time it is opened, so the
cleared playlist came back on the next launch.

**Delete playlist.** Confirming a delete in the sources dialog removed the
saved entry, but deliberately kept its channels on screen and re-offered them
as an unsaved "(not saved)" list — which one bookmark click would save again.
A confirmed delete that leaves the thing on screen does not look like it
happened.

Both paths also flush the settings write immediately: these are actions people
take seconds before closing the app, which is exactly when a 400 ms debounced
write is lost.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from modes.m3u.playlist import GROUPING_NONE, M3UContext


class _Engine(QObject):
    errorOccurred = Signal(str)
    currentMedia = ""

    def stop(self) -> None:
        pass

    def open(self, _url: str) -> None:
        pass


class _Controller(QObject):
    activeModeChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.activeMode = "m3u"
        self.stops = 0

    def stop(self) -> None:
        self.stops += 1


class _Settings:
    def __init__(self, path) -> None:
        self.path = path
        self.values: dict[tuple[str, str], object] = {}
        self.flushes = 0

    def get_mode(self, mode: str, key: str, default=None):
        return self.values.get((mode, key), default)

    def set_mode(self, mode: str, key: str, value) -> None:
        self.values[(mode, key)] = value

    def flush(self) -> None:
        self.flushes += 1


def _playlist(tmp_path, name: str = "list.m3u"):
    path = tmp_path / name
    path.write_text(
        "#EXTM3U\n"
        '#EXTINF:-1 group-title="News",BBC One\n'
        "http://x/bbc\n"
        '#EXTINF:-1 group-title="News",CNN\n'
        "http://x/cnn\n",
        encoding="utf-8",
    )
    return path


def _loaded_context(tmp_path, settings):
    """A context with one saved source, loaded — the normal starting state."""
    path = _playlist(tmp_path)
    context = M3UContext(_Engine(), _Controller(), settings)
    context.channels.setGrouping(GROUPING_NONE)
    assert context.addSource("My list", str(path), "file") == ""
    source_id = context.sources[0]["id"]
    context.loadSource(source_id)
    context._pool.waitForDone(5000)   # the load runs on the context's own pool
    context._on_load_succeeded(source_id, path.read_text(encoding="utf-8"))
    assert context.channels.totalCount == 2
    return context, source_id


def test_clearing_the_playlist_also_forgets_it(tmp_path) -> None:
    settings = _Settings(tmp_path / "settings.json")
    context, source_id = _loaded_context(tmp_path, settings)
    assert settings.get_mode("m3u", "lastSource", "") == source_id

    context.clear()

    assert context.channels.totalCount == 0
    # The pointer that a restart would follow is gone, and written out now.
    assert settings.get_mode("m3u", "lastSource", "") == ""
    assert settings.flushes >= 1
    # Nothing is left that a bookmark click could resurrect.
    assert not context.canSaveCurrentSource
    assert context.currentSourceName == ""


def test_a_cleared_playlist_does_not_come_back_next_launch(tmp_path) -> None:
    settings = _Settings(tmp_path / "settings.json")
    context, _ = _loaded_context(tmp_path, settings)
    context.clear()
    context.shutdown()

    # A fresh session, same settings and same stores: opening M3U restores the
    # last source, and there must no longer be one.
    reborn = M3UContext(_Engine(), _Controller(), settings)
    reborn._restore_last_source()
    reborn._pool.waitForDone(5000)
    assert reborn.channels.totalCount == 0
    # The saved playlist itself is untouched — clearing is not deleting.
    assert len(reborn.sources) == 1


def test_deleting_the_loaded_playlist_empties_the_panel(tmp_path) -> None:
    settings = _Settings(tmp_path / "settings.json")
    context, source_id = _loaded_context(tmp_path, settings)

    assert context.removeSource(source_id) is True

    assert context.sources == []
    assert context.channels.totalCount == 0          # gone from the screen too
    assert not context.canSaveCurrentSource          # and not resurrectable
    assert context.currentSourceName == ""
    assert settings.get_mode("m3u", "lastSource", "") == ""
    assert settings.flushes >= 1


def test_deleting_a_different_playlist_leaves_the_loaded_one_alone(tmp_path) -> None:
    """The delete must be surgical: only the loaded list clears the panel."""
    settings = _Settings(tmp_path / "settings.json")
    context, loaded_id = _loaded_context(tmp_path, settings)
    other = _playlist(tmp_path, "other.m3u")
    assert context.addSource("Other", str(other), "file") == ""
    other_id = [s["id"] for s in context.sources if s["id"] != loaded_id][0]

    assert context.removeSource(other_id) is True

    assert context.channels.totalCount == 2
    assert settings.get_mode("m3u", "lastSource", "") == loaded_id
    assert [s["id"] for s in context.sources] == [loaded_id]
