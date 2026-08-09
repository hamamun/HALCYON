"""Remote bridge — the safety keystone (§R.4).

Commands are queued onto the Qt thread (never executed on the server thread);
status snapshots are built from live state on the Qt thread and published to
the thread-safe store. All fakes below are plain Python so the tests run
headless.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QCoreApplication, QObject

from remote.bridge import RemoteBridge


def _app() -> QCoreApplication:
    return QCoreApplication.instance()


def pump(ms: int = 400) -> None:
    app = _app()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


class FakeEngine(QObject):
    def __init__(self):
        super().__init__()
        self._playing = True
        self._muted = False
        self._volume = 80
        self._rate = 1.0
        self._time = 12345
        self.calls = []

    def isPlaying(self): return self._playing
    def time(self): return self._time
    def duration(self): return 60000
    def position(self): return 0.2
    def volume(self): return self._volume
    def muted(self): return self._muted
    def rate(self): return self._rate
    def seek(self, ms): self.calls.append(("seek", ms))
    def seek_relative(self, ms): self.calls.append(("seek_relative", ms))
    def set_position(self, f): self.calls.append(("set_position", f))
    def set_rate(self, r): self.calls.append(("set_rate", r))
    def set_volume(self, v): self._volume = v; self.calls.append(("set_volume", v))
    def toggle_mute(self): self._muted = not self._muted; self.calls.append(("toggle_mute",))


class FakeController(QObject):
    def __init__(self):
        super().__init__()
        self.mode = "local"
        self.calls = []
        self._stem = "song.mp3"

    def activeMode(self): return self.mode
    def setActiveMode(self, mode): self.mode = mode; self.calls.append(("setActiveMode", mode))
    def playPause(self): self.calls.append(("playPause",))
    def play(self): self.calls.append(("play",))
    def pause(self): self.calls.append(("pause",))
    def stop(self): self.calls.append(("stop",))
    def next(self): self.calls.append(("next",))
    def previous(self): self.calls.append(("previous",))
    def currentPlaybackLabel(self): return "Fake Song"
    @property
    def currentFileStem(self): return self._stem
    def audioTracks(self): return [{"id": -1, "label": "Default"}]
    def subtitleTracks(self): return []
    def currentAudioId(self): return -1
    def currentSubtitleId(self): return -1
    def subtitleDelayMs(self): return 0
    def openPath(self, p): self.calls.append(("openPath", p))
    def addPaths(self, paths): self.calls.append(("addPaths", paths))
    def playIndex(self, i): self.calls.append(("playIndex", i))
    def moveItem(self, f, t): self.calls.append(("moveItem", f, t))
    def clearSelected(self, rows): self.calls.append(("clearSelected", rows))
    def clearPlaylist(self): self.calls.append(("clearPlaylist",))
    def cycleRepeat(self): self.calls.append(("cycleRepeat",))
    def toggleShuffle(self): self.calls.append(("toggleShuffle",))
    def setAudioTrack(self, i): self.calls.append(("setAudioTrack", i))
    def setSubtitleTrack(self, i): self.calls.append(("setSubtitleTrack", i))
    def adjustSubtitleDelay(self, d): self.calls.append(("adjustSubtitleDelay", d))
    def loadSubtitle(self, p): self.calls.append(("loadSubtitle", p))


@pytest.fixture()
def bridge():
    b = RemoteBridge(controller=FakeController(), engine=FakeEngine(), settings=None)
    yield b
    b._timer.stop()


def test_command_runs_on_qt_thread(bridge):
    bridge.request("playPause", {})
    pump()
    assert bridge._controller.calls[-1] == ("playPause",)


def test_unknown_action_ignored(bridge):
    bridge.request("totally.bogus", {})
    pump()
    assert not bridge._controller.calls


def test_payload_actions(bridge):
    bridge.request("seekTo", {"ms": 5000})
    bridge.request("setVolume", {"volume": 42})
    bridge.request("setRate", {"rate": 1.5})
    bridge.request("openPath", {"path": "C:/x.mp4"})
    bridge.request("addPaths", {"paths": ["a", "b"]})
    bridge.request("switchMode", {"id": "m3u"})
    pump()
    c = bridge._controller
    assert ("seek", 5000) in bridge._engine.calls
    assert ("set_volume", 42) in bridge._engine.calls
    assert ("set_rate", 1.5) in bridge._engine.calls
    assert ("openPath", "C:/x.mp4") in c.calls
    assert ("addPaths", ["a", "b"]) in c.calls
    assert c.mode == "m3u"


def test_volume_clamped(bridge):
    bridge.request("setVolume", {"volume": 500})
    pump()
    assert bridge._engine._volume == 100


def test_power_commands_are_mapped(bridge, monkeypatch):
    import remote.bridge as bridge_module
    import remote.power as power_module

    calls = []

    def fake_sleep():
        calls.append("sleep")
        return True

    def fake_shutdown():
        calls.append("shutdown")
        return True

    # patch on the module so the bridge's dispatch sees the fakes, and let
    # monkeypatch restore the real functions afterwards (global module state
    # must not leak into the sibling test_remote_power.py tests).
    monkeypatch.setattr(power_module, "sleep_pc", fake_sleep)
    monkeypatch.setattr(power_module, "shutdown_pc", fake_shutdown)
    assert bridge_module.power_actions is power_module
    bridge.request("power.sleep", {})
    bridge.request("power.shutdown", {})
    pump()
    assert calls == ["sleep", "shutdown"]


def test_snapshot_build(bridge):
    bridge.set_server_url("http://192.168.1.5:8765")
    bridge.publish_now()
    snap = bridge.store.snapshot()
    assert snap["app"] == "halcyon"
    assert snap["serverUrl"] == "http://192.168.1.5:8765"
    assert snap["mode"] == "local"
    assert snap["player"]["playing"] is True
    assert snap["player"]["time"] == 12345
    assert snap["nowPlaying"]["label"] == "Fake Song"
    assert snap["playlist"]["count"] == 0


def test_m3u_snapshot(bridge):
    class FakeChannel:
        def __init__(self, name, url, group):
            self.name, self.url, self.group = name, url, group
            self.country = self.language = ""
            self.logo = ""

    class FakeModel:
        def grouping(self): return "category"
        def favouritesOnly(self): return False
        def expandedGroup(self): return "News"
        def count(self): return 2
        def currentIndex(self): return 0
        def channel_at(self, i):
            return [FakeChannel("News1", "http://x/1", "News"),
                    FakeChannel("Sport1", "http://x/2", "Sport")][i]
        def is_favourite(self, url): return url.endswith("/1")

    class FakeM3UContext(QObject):
        def sources(self): return [{"id": "s1", "name": "Pack"}]
        def sourcesFull(self): return False
        def currentSourceName(self): return "Pack"
        def loading(self): return False
        def statusMessage(self): return "ok"
        def statusIsError(self): return False
        def currentChannelName(self): return "News1"
        def channels(self): return FakeModel()

    bridge.register_context("m3u", FakeM3UContext())
    bridge._controller.mode = "m3u"
    bridge.publish_now()
    snap = bridge.store.snapshot()
    m3u = snap["m3u"]
    assert m3u["sources"][0]["name"] == "Pack"
    assert m3u["channelCount"] == 2
    assert m3u["channels"][0]["name"] == "News1"
    assert m3u["channels"][0]["fav"] is True
    assert m3u["channels"][0]["current"] is True


def test_m3u_snapshot_and_commands_with_property_context(bridge):
    class FakeChannel:
        def __init__(self, name, url, group):
            self.name, self.url, self.group = name, url, group
            self.country = self.language = ""
            self.logo = ""

    class FakeModel:
        def __init__(self):
            self.calls = []
        def grouping(self): return "category"
        def favouritesOnly(self): return False
        def expandedGroup(self): return "News"
        def count(self): return 2
        def currentIndex(self): return 0
        def channel_at(self, i):
            return [FakeChannel("News1", "http://x/1", "News"),
                    FakeChannel("Sport1", "http://x/2", "Sport")][i]
        def is_favourite(self, url): return url.endswith("/1")
        def play_index(self, row): self.calls.append(("play_index", row))
        def set_favourite_url(self, url, on): self.calls.append(("set_favourite_url", url, on))
        def setFilter(self, text): self.calls.append(("setFilter", text))
        def setGrouping(self, mode): self.calls.append(("setGrouping", mode))
        def setFavouritesOnly(self, on): self.calls.append(("setFavouritesOnly", on))
        def toggleGroup(self, key): self.calls.append(("toggleGroup", key))

    class FakeM3UContextWithProperty(QObject):
        def __init__(self):
            super().__init__()
            self._model = FakeModel()
        def sources(self): return [{"id": "s1", "name": "Pack"}]
        def sourcesFull(self): return False
        def currentSourceName(self): return "Pack"
        def loading(self): return False
        def statusMessage(self): return "ok"
        def statusIsError(self): return False
        def currentChannelName(self): return "News1"
        @property
        def channels(self): return self._model

    ctx = FakeM3UContextWithProperty()
    bridge.register_context("m3u", ctx)
    bridge._controller.mode = "m3u"
    bridge.publish_now()
    snap = bridge.store.snapshot()
    m3u = snap["m3u"]
    assert m3u["channelCount"] == 2
    assert m3u["channels"][0]["name"] == "News1"

    bridge.request("m3u.playRow", {"row": 1})
    bridge.request("m3u.setFavourite", {"url": "http://x/1", "on": True})
    bridge.request("m3u.setFilter", {"text": "bbc"})
    bridge.request("m3u.setGrouping", {"mode": "country"})
    bridge.request("m3u.setFavouritesOnly", {"on": True})
    bridge.request("m3u.toggleGroup", {"key": "News"})
    pump()
    assert ("play_index", 1) in ctx._model.calls
    assert ("set_favourite_url", "http://x/1", True) in ctx._model.calls
    assert ("setFilter", "bbc") in ctx._model.calls
    assert ("setGrouping", "country") in ctx._model.calls
    assert ("setFavouritesOnly", True) in ctx._model.calls
    assert ("toggleGroup", "News") in ctx._model.calls
