#!/usr/bin/env python3
"""Live demo launcher for the mobile remote — NOT part of the app.

Starts the real remote server (``remote/server.py`` + ``remote/bridge.py``)
with fake controller/engine/contexts so the phone UI can be exercised in a
browser without Windows, WebView2 or libVLC. Every control works; the fakes
just respond instantly instead of driving real media.

    python tools/demo_remote.py [port]     # default 8765

The bridge's status poller needs a Qt event loop, so this pumps a
QCoreApplication on a background thread while the server runs on its own.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QObject

from remote.bridge import RemoteBridge
from remote.server import RemoteServer


# --------------------------------------------------------------------------- fakes
class DemoEngine(QObject):
    def __init__(self):
        super().__init__()
        self._playing = True
        self._muted = False
        self._volume = 62
        self._rate = 1.0
        self._time = 0
        self._duration = 264000

    def isPlaying(self): return self._playing
    def time(self):
        if self._playing:
            self._time = (self._time + 1000) % (self._duration + 1)
        return self._time
    def duration(self): return self._duration
    def position(self): return self._time / self._duration
    def volume(self): return self._volume
    def muted(self): return self._muted
    def rate(self): return self._rate
    def seek(self, ms): self._time = int(ms)
    def seek_relative(self, ms): self._time = max(0, self._time + int(ms))
    def set_position(self, f): self._time = int(f * self._duration)
    def set_rate(self, r): self._rate = float(r)
    def set_volume(self, v): self._volume = int(v)
    def toggle_mute(self): self._muted = not self._muted


class DemoController(QObject):
    def __init__(self):
        super().__init__()
        self.mode = "local"
        self.playlist = [
            {"path": "C:/Music/Aurora.mp3", "title": "Aurora", "duration": 264000},
            {"path": "C:/Music/Glass.mp3", "title": "Glass Ocean", "duration": 198000},
            {"path": "C:/Music/Neon.mp3", "title": "Neon Nights", "duration": 222000},
            {"path": "C:/Music/Drift.mp3", "title": "Drift Away", "duration": 176000},
            {"path": "C:/Music/Velvet.mp3", "title": "Velvet Sky", "duration": 241000},
            {"path": "C:/Music/Echo.mp3", "title": "Echoes", "duration": 205000},
            {"path": "C:/Music/Prism.mp3", "title": "Prism", "duration": 189000},
            {"path": "C:/Music/Solace.mp3", "title": "Solace", "duration": 233000},
            {"path": "C:/Music/Ember.mp3", "title": "Ember", "duration": 214000},
        ]
        self._current = 0
        self._repeat = 0
        self._shuffle = False

    def activeMode(self): return self.mode
    def setActiveMode(self, m): self.mode = m
    def playPause(self): pass
    def play(self): pass
    def pause(self): pass
    def stop(self): pass
    def next(self): self._current = (self._current + 1) % len(self.playlist)
    def previous(self): self._current = (self._current - 1) % len(self.playlist)
    def currentPlaybackLabel(self):
        if self.mode == "m3u":
            return "ESPN HD"
        return self.playlist[self._current]["title"]
    @property
    def currentFileStem(self): return self.playlist[self._current]["title"]
    def audioTracks(self): return [{"id": -1, "label": "Default"}]
    def subtitleTracks(self): return []
    def currentAudioId(self): return -1
    def currentSubtitleId(self): return -1
    def subtitleDelayMs(self): return 0
    def openPath(self, _p): pass
    def addPaths(self, paths):
        for p in paths:
            self.playlist.append({"path": p, "title": Path(p).stem, "duration": 0})
    def playIndex(self, i):
        if 0 <= i < len(self.playlist): self._current = i
    def moveItem(self, f, t):
        if 0 <= f < len(self.playlist) and 0 <= t < len(self.playlist):
            item = self.playlist.pop(f); self.playlist.insert(t, item)
    def clearSelected(self, rows):
        for r in sorted(rows, reverse=True):
            if 0 <= r < len(self.playlist): self.playlist.pop(r)
    def clearPlaylist(self): self.playlist = []
    def cycleRepeat(self): self._repeat = (self._repeat + 1) % 3
    def toggleShuffle(self): self._shuffle = not self._shuffle
    def setAudioTrack(self, _i): pass
    def setSubtitleTrack(self, _i): pass
    def adjustSubtitleDelay(self, _d): pass
    def loadSubtitle(self, _p): pass


class DemoM3U(QObject):
    def __init__(self):
        super().__init__()
        self._sources = [{"id": "s1", "name": "Sports Pack", "location": "http://demo/sports.m3u"},
                         {"id": "s2", "name": "News Mix", "location": "http://demo/news.m3u"}]
        self._loaded = False
        self._channels = self._make_channels()
        self._current = 0
        self._favs = {"http://demo/ch/1"}
        self._status = ""
        self._error = False
        self._loading = False

    @staticmethod
    def _make_channels():
        rows = []
        for i in range(18):
            rows.append({"name": f"Channel {i+1}", "url": f"http://demo/ch/{i+1}",
                         "group": ["Sports", "Movies", "News"][i % 3]})
        return rows

    def sources(self): return self._sources
    def sourcesFull(self): return len(self._sources) >= 7
    def currentSourceName(self): return "Sports Pack" if self._loaded else ""
    def loading(self): return self._loading
    def statusMessage(self): return self._status
    def statusIsError(self): return self._error
    def currentChannelName(self): return self._channels[self._current]["name"]
    def addSource(self, name, url, _kind): self._sources.append({"id": f"s{len(self._sources)+1}", "name": name, "location": url})
    def removeSource(self, sid): self._sources = [s for s in self._sources if s["id"] != sid]
    def loadSource(self, _sid): self._loaded = True; self._status = "Loaded 18 channels"; self._error = False

    class _Model:
        def __init__(self, ctx): self._ctx = ctx
        def grouping(self): return "category"
        def favouritesOnly(self): return False
        def expandedGroup(self): return ""
        def count(self): return len(self._ctx._channels)
        def currentIndex(self): return self._ctx._current
        def channel_at(self, i):
            c = self._ctx._channels[i]
            return type("Ch", (), {"name": c["name"], "url": c["url"], "group": c["group"],
                                   "country": "", "language": "", "logo": ""})()
        def is_favourite(self, url): return url in self._ctx._favs
        def play_index(self, row):
            if 0 <= row < len(self._ctx._channels): self._ctx._current = row
        def set_favourite_url(self, url, on):
            if on: self._ctx._favs.add(url)
            else: self._ctx._favs.discard(url)
        def setFilter(self, _t): pass
        def setGrouping(self, _m): pass
        def setFavouritesOnly(self, _b): pass
        def toggleGroup(self, _k): pass

    def channels(self): return self._Model(self)


class DemoWeb(QObject):
    def __init__(self):
        super().__init__()
        self._tabs = [{"id": "t1", "title": "How to build a PC", "url": "https://www.youtube.com/watch?v=demo1"}]
        self._bookmarks = [{"title": "YouTube", "url": "https://www.youtube.com"},
                           {"title": "GitHub", "url": "https://github.com"}]
        self._media = {"found": True, "paused": False, "currentTime": 42.0,
                       "duration": 180.0, "volume": 0.8, "muted": False, "hasVideo": True}

    def tabCount(self): return len(self._tabs)
    def tabs(self): return list(self._tabs)
    def activeTab(self): return dict(self._tabs[0])
    def runtimeAvailable(self): return True
    def bookmarkItems(self): return list(self._bookmarks)
    def activeTabBookmarked(self): return False
    def addBookmark(self, title, url): self._bookmarks.append({"title": title, "url": url})
    def removeBookmark(self, url): self._bookmarks = [b for b in self._bookmarks if b["url"] != url]
    def navigateActive(self, url): self._tabs[0] = {"id": "t1", "title": url, "url": url}
    def goBack(self): pass
    def goForward(self): pass
    def reloadOrStop(self): pass
    def media_status(self): return dict(self._media)
    def mediaControl(self, action, value=None):
        m = self._media
        if action == "toggle": m["paused"] = not m["paused"]
        elif action == "seek": m["currentTime"] = float(value or 0)
        elif action == "seekBy": m["currentTime"] = max(0, m["currentTime"] + float(value or 0))
        elif action == "volume": m["volume"] = float(value or 0)
        elif action == "mute": m["muted"] = bool(value)
        elif action == "fullscreen": pass


class DemoSubs(QObject):
    def __init__(self):
        super().__init__()
        self._searching = False
        self._status = ""
        self._best = []
        self._others = []
        self._languages = ["en", "fr", "es"]
        self._media_name = "Aurora"
        self._busy = -1

    def _get_media_name(self): return self._media_name
    def _get_searching(self): return self._searching
    def _get_busy_index(self): return self._busy
    def _get_status(self): return self._status
    def _get_status_is_error(self): return False
    def _get_best(self): return self._best
    def _get_others(self): return self._others
    def _get_languages(self): return self._languages

    # The bridge writes `subs.languages = [...]`; expose the same property
    # surface as the real SubtitleBackend so the demo behaves identically.
    languages = property(_get_languages, lambda self, v: self._languages.__setitem__(slice(None), list(v)))

    def search(self, query):
        self._status = f"Found results for “{query}”"
        self._best = [{"idx": 0, "file_name": f"{query}.2026.1080p.WEB-DL", "lang": "en"},
                      {"idx": 1, "file_name": f"{query}.2026.BluRay", "lang": "en"}]
        self._others = [{"idx": 2, "file_name": f"{query}.2026.FRENCH", "lang": "fr"}]
        self._languages = list(self._languages)

    def download(self, index):
        self._busy = index
        self._status = "Downloading…"
        self._best = list(self._best)
        self._others = list(self._others)

    def clearResults(self):
        self._best = []; self._others = []; self._status = ""


class DemoEQ(QObject):
    def __init__(self):
        super().__init__()
        self._presets = ["Flat", "Rock", "Pop", "Jazz", "Classical"]
        self._current = 0
        self._bands = ["60", "230", "910", "3.6k", "14k"]
        self._amps = [0.0] * 5
        self._preamp = 0.0

    def presetNames(self): return list(self._presets)
    def currentPreset(self): return self._current
    def bandLabels(self): return list(self._bands)
    def amp_at(self, b): return self._amps[b]
    def preamp(self): return self._preamp
    def apply_preset(self, i):
        self._current = int(i); self._amps = [0.0] * 5
    def set_amp(self, b, v): self._amps[int(b)] = float(v)
    def set_preamp(self, v): self._preamp = float(v)
    def reset(self): self._amps = [0.0] * 5; self._preamp = 0.0


# --------------------------------------------------------------------------- main
def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    app = QCoreApplication([])

    engine = DemoEngine()
    controller = DemoController()
    m3u, web, subs, eq = DemoM3U(), DemoWeb(), DemoSubs(), DemoEQ()

    class DemoLocal(QObject):
        """Mimics the Local PlaylistModel context the app registers."""

        def to_list(self): return list(controller.playlist)
        def count(self): return len(controller.playlist)
        def currentIndex(self): return controller._current
        def repeatMode(self): return controller._repeat
        def shuffle(self): return controller._shuffle

    local = DemoLocal()

    bridge = RemoteBridge(controller=controller, engine=engine, settings=None,
                          equalizer=eq, subs=subs)
    for mode, ctx in (("local", local), ("m3u", m3u), ("web", web)):
        bridge.register_context(mode, ctx)

    srv = RemoteServer(bridge=bridge, port=port)
    if not srv.start():
        print("server failed to start", file=sys.stderr)
        return 1

    print(f"Halcyon remote demo listening on {srv.base_url}")

    # The bridge's status poller and the queued-command dispatch both need the
    # REAL Qt event loop on the thread that owns the bridge (the main thread);
    # processEvents() from another thread would never see those events. The
    # server itself runs on its own daemon thread, so the main thread is free.
    import signal

    def _stop(_signum, _frame):
        srv.stop()
        app.quit()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
