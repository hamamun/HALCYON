"""M3U favourites: per-saved-source storage and channel-model filtering."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from modes.m3u.favourites import FavouritesStore
from modes.m3u.parser import Channel
from modes.m3u.playlist import GROUPING_NONE, ChannelModel, M3UContext


def _channels() -> list[Channel]:
    return [
        Channel(name="BBC One", url="http://x/bbc", group="News"),
        Channel(name="CNN", url="http://x/cnn", group="News"),
        Channel(name="TF1", url="http://x/tf1", group="Entertainment"),
    ]


def test_favourites_store_is_per_source_and_persistent(tmp_path) -> None:
    path = tmp_path / "m3u-favourites.json"
    store = FavouritesStore(path)

    assert store.toggle("source-a", "http://x/bbc") is True
    assert store.toggle("source-a", "http://x/cnn") is True
    assert store.toggle("source-b", "http://x/tf1") is True
    assert store.toggle("source-a", "http://x/cnn") is False

    assert store.list("source-a") == {"http://x/bbc"}
    assert store.list("source-b") == {"http://x/tf1"}

    loaded = FavouritesStore(path)
    assert loaded.contains("source-a", "http://x/bbc")
    assert not loaded.contains("source-a", "http://x/cnn")
    assert loaded.remove_source("source-a")
    assert loaded.list("source-a") == set()
    assert loaded.list("source-b") == {"http://x/tf1"}


def test_channel_model_marks_and_filters_favourites() -> None:
    model = ChannelModel()
    model.set_channels(_channels())
    model.setGrouping(GROUPING_NONE)
    model.set_favourites({"http://x/bbc", "http://x/tf1"})

    assert model.totalCount == 3
    assert model.favouriteCount == 2
    assert model.data(model.index(0), model.IsFavouriteRole) is True
    assert model.data(model.index(1), model.IsFavouriteRole) is False

    model.setFavouritesOnly(True)
    assert model.count == 2
    urls = [model.data(model.index(row), model.UrlRole) for row in range(model.count)]
    assert urls == ["http://x/bbc", "http://x/tf1"]

    # Removing a favourite while in favourites-only view immediately removes it
    # from that filtered view, without touching the full parsed channel list.
    model.set_favourite_url("http://x/bbc", False)
    assert model.totalCount == 3
    assert model.count == 1
    assert model.data(model.index(0), model.UrlRole) == "http://x/tf1"


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


class _Settings:
    def __init__(self, path) -> None:
        self.path = path
        self.values = {}

    def get_mode(self, _mode: str, _key: str, default):
        return default

    def set_mode(self, mode: str, key: str, value) -> None:
        self.values[(mode, key)] = value


def test_unsaved_dropped_playlist_must_be_saved_before_favourites(tmp_path) -> None:
    playlist = tmp_path / "drop.m3u"
    playlist.write_text(
        "#EXTM3U\n"
        '#EXTINF:-1 group-title="News",BBC One\n'
        "http://x/bbc\n",
        encoding="utf-8",
    )
    context = M3UContext(_Engine(), _Controller(), _Settings(tmp_path / "settings.json"))
    context.channels.setGrouping(GROUPING_NONE)

    context.openFiles([str(playlist)])
    assert context.channels.totalCount == 1
    assert context.toggleFavourite(0) == "save-required"
    assert context.canSaveCurrentSource

    assert context.saveCurrentSourceForFavourites() == ""
    assert not context.canSaveCurrentSource
    assert context.toggleFavourite(0) == "added"

    stored = FavouritesStore(tmp_path / "m3u-favourites.json")
    source_id = context._current_source_id
    assert stored.list(source_id) == {"http://x/bbc"}
