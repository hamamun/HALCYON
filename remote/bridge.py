"""Qt-thread bridge for the mobile remote — the safety keystone (§R.4).

Two rules keep the player intact:

1. **Commands are queued.** ``RemoteBridge.request()`` may be called from any
   thread (the aiohttp thread). It only *emits* a signal that is connected
   with ``Qt.QueuedConnection``, so ``_dispatch`` always runs on the Qt main
   thread — the same thread every button, hotkey and drag-drop handler runs
   on. The server thread never calls a QObject method directly.
2. **Status is read on the Qt thread too.** A ``QTimer`` on this object
   rebuilds the snapshot from live player/context state and publishes it into
   a thread-safe :class:`remote.status.StatusStore`; the server thread only
   ever reads plain dicts.

Every action here maps to the *existing* single implementation (§4.1): the
same ``AppController`` slots and engine primitives the QML action host uses.
The remote adds no new ways to do anything — it is a second doorway.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Property, QObject, QTimer, Qt, Signal, Slot

from remote import power as power_actions
from remote.status import StatusStore

log = logging.getLogger(__name__)

#: Poll cadence for the status snapshot. 500 ms keeps the phone live without
#: hammering libVLC property reads.
POLL_MS = 500

#: Player-bearing modes — where transport commands are legal (§P3.6: Web is
#: inert; the page owns its own playback).
PLAYER_MODES = ("local", "m3u")


class RemoteBridge(QObject):
    """The single door between the remote server and the player."""

    #: Emitted by the server thread; _dispatch runs queued on the Qt thread.
    commandRequested = Signal(str, dict)
    #: Tell the QML shell to toggle window fullscreen (M3U ⛶, §R.2).
    toggleFullscreenRequested = Signal()
    #: Tell the M3U transport to toggle its PiP window (§R.2).
    togglePipRequested = Signal()

    def __init__(
        self,
        controller=None,
        engine=None,
        settings=None,
        equalizer=None,
        subs=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._engine = engine
        self._settings = settings
        self._equalizer = equalizer
        self._subs = subs
        self._contexts: dict[str, QObject] = {}

        self.store = StatusStore()
        self._server_url = ""

        # The explicit QueuedConnection is load-bearing: with AutoConnection
        # Qt compares the *emitting object's* thread (this bridge, which lives
        # in the main thread) and would call _dispatch directly on the server
        # thread. QueuedConnection pins it to the main thread, always.
        self.commandRequested.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.publish_now)
        self._timer.start()

    # -------------------------------------------------------------- wiring ---
    #: The URL the phone dials (set once the server is listening) — read by
    #: the QML Settings dialog (§R.1#3).
    serverUrlChanged = Signal()

    @Property(str, notify=serverUrlChanged)
    def serverUrl(self) -> str:  # noqa: N802 - QML-facing
        return self._server_url

    def set_server_url(self, url: str) -> None:
        if url != self._server_url:
            self._server_url = url
            self.serverUrlChanged.emit()

    def register_context(self, mode_id: str, context: QObject | None) -> None:
        if context is not None:
            self._contexts[mode_id] = context

    def context(self, mode_id: str) -> QObject | None:
        return self._contexts.get(mode_id)

    # ---------------------------------------------------------- server side ---
    def request(self, action: str, payload: dict | None = None) -> None:
        """Thread-safe command entry point — safe from the aiohttp thread."""
        self.commandRequested.emit(action, payload or {})

    # ------------------------------------------------------------- status ----
    def stop(self) -> None:
        """Stop the status poller. Idempotent; called on app shutdown so the
        bridge never reads engine state after the engine is torn down."""
        try:
            if self._timer.isActive():
                self._timer.stop()
        except RuntimeError:  # pragma: no cover — already destroyed
            pass

    def publish_now(self) -> None:
        """Rebuild the snapshot from live state (Qt thread) and publish it."""
        snap: dict = {"app": "halcyon", "serverUrl": self._server_url}
        controller, engine = self._controller, self._engine

        mode = getattr(controller, "activeMode", "local") if controller else "local"
        snap["mode"] = mode

        # ---- player -----------------------------------------------------
        player: dict = {"playing": False, "muted": False, "time": 0,
                        "duration": 0, "position": 0.0, "volume": 0,
                        "rate": 1.0, "hasVideo": False, "subsAvailable": False}
        if engine is not None:
            for key, attr in (
                ("playing", "isPlaying"), ("muted", "muted"), ("time", "time"),
                ("duration", "duration"), ("position", "position"),
                ("volume", "volume"), ("rate", "rate"),
            ):
                try:
                    player[key] = getattr(engine, attr)()
                except Exception:
                    pass
        snap["player"] = player

        # ---- now playing ------------------------------------------------
        label = getattr(controller, "currentPlaybackLabel", lambda: "")() if controller else ""
        stem = getattr(controller, "currentFileStem", "") if controller else ""
        snap["nowPlaying"] = {"label": label or "", "stem": stem or ""}

        # ---- tracks ------------------------------------------------------
        tracks: dict = {"audio": [], "currentAudio": -1, "subtitle": [],
                        "currentSubtitle": -1, "delayMs": 0}
        if controller is not None:
            try:
                tracks["audio"] = list(controller.audioTracks())
            except Exception:
                pass
            try:
                tracks["subtitle"] = list(controller.subtitleTracks())
            except Exception:
                pass
            try:
                tracks["currentAudio"] = int(controller.currentAudioId())
            except Exception:
                pass
            try:
                tracks["currentSubtitle"] = int(controller.currentSubtitleId())
            except Exception:
                pass
            try:
                tracks["delayMs"] = int(controller.subtitleDelayMs())
            except Exception:
                pass
        snap["tracks"] = tracks

        # ---- local playlist ----------------------------------------------
        snap["playlist"] = self._playlist_snapshot(mode)

        # ---- m3u ----------------------------------------------------------
        snap["m3u"] = self._m3u_snapshot(mode)

        # ---- web ----------------------------------------------------------
        snap["web"] = self._web_snapshot()

        # ---- equalizer -----------------------------------------------------
        snap["eq"] = self._eq_snapshot()

        # ---- subtitles ------------------------------------------------------
        snap["subs"] = self._subs_snapshot()

        snap["connected"] = True
        self.store.update(snap)

    def _playlist_snapshot(self, mode: str) -> dict:
        out = {"rows": [], "count": 0, "currentIndex": -1, "repeatMode": 0, "shuffle": False}
        ctx = self._contexts.get("local") if mode == "local" else None
        if ctx is None:
            return out
        try:
            rows = ctx.to_list() if hasattr(ctx, "to_list") else []
            out["rows"] = rows
            out["count"] = len(rows)
        except Exception:
            pass
        try:
            out["currentIndex"] = int(ctx.currentIndex())
        except Exception:
            pass
        try:
            out["repeatMode"] = int(ctx.repeatMode())
        except Exception:
            pass
        try:
            out["shuffle"] = bool(ctx.shuffle())
        except Exception:
            pass
        return out

    def _m3u_snapshot(self, mode: str) -> dict:
        out = {"sources": [], "sourcesFull": False, "currentSource": "",
               "loading": False, "status": "", "statusIsError": False,
               "currentChannel": "", "grouping": "category",
               "favouritesOnly": False, "expandedGroup": "",
               "channels": [], "channelCount": 0}
        ctx = self._contexts.get("m3u")
        if ctx is None:
            return out
        try:
            out["sources"] = list(ctx.sources())
        except Exception:
            pass
        try:
            out["sourcesFull"] = bool(ctx.sourcesFull())
        except Exception:
            pass
        try:
            out["currentSource"] = str(ctx.currentSourceName())
        except Exception:
            pass
        try:
            out["loading"] = bool(ctx.loading())
        except Exception:
            pass
        try:
            out["status"] = str(ctx.statusMessage())
        except Exception:
            pass
        try:
            out["statusIsError"] = bool(ctx.statusIsError())
        except Exception:
            pass
        try:
            out["currentChannel"] = str(ctx.currentChannelName())
        except Exception:
            pass

        model = None
        try:
            model = ctx.channels()
        except Exception:
            model = None
        if model is not None:
            try:
                out["grouping"] = str(model.grouping())
            except Exception:
                pass
            try:
                out["favouritesOnly"] = bool(model.favouritesOnly())
            except Exception:
                pass
            try:
                out["expandedGroup"] = str(model.expandedGroup())
            except Exception:
                pass
            # The channel list is only useful while M3U is the active mode and
            # only as big as the current view (filtered/grouped) — bound it.
            if mode == "m3u":
                try:
                    count = int(model.count())
                    out["channelCount"] = count
                    rows = []
                    for i in range(count):
                        ch = model.channel_at(i)
                        if ch is None:
                            continue
                        rows.append({
                            "name": ch.name, "url": ch.url, "group": ch.group,
                            "country": ch.country, "language": ch.language,
                            "logo": ch.logo, "fav": model.is_favourite(ch.url),
                            "current": i == int(model.currentIndex()),
                        })
                    out["channels"] = rows
                except Exception:
                    pass
        return out

    def _web_snapshot(self) -> dict:
        out = {"tabCount": 0, "tabs": [], "activeTab": None,
               "runtimeAvailable": False, "bookmarks": [],
               "activeTabBookmarked": False, "media": None}
        ctx = self._contexts.get("web")
        if ctx is None:
            return out
        try:
            out["tabCount"] = int(ctx.tabCount())
        except Exception:
            pass
        try:
            out["tabs"] = list(ctx.tabs())
        except Exception:
            pass
        try:
            out["activeTab"] = dict(ctx.activeTab())
        except Exception:
            pass
        try:
            out["runtimeAvailable"] = bool(ctx.runtimeAvailable())
        except Exception:
            pass
        try:
            out["bookmarks"] = list(ctx.bookmarkItems())
        except Exception:
            pass
        try:
            out["activeTabBookmarked"] = bool(ctx.activeTabBookmarked())
        except Exception:
            pass
        try:
            probe = getattr(ctx, "media_status", None)
            if probe is not None:
                out["media"] = probe()
        except Exception:
            pass
        return out

    def _eq_snapshot(self) -> dict:
        out = {"presets": [], "currentPreset": -1, "bands": [], "amps": [], "preamp": 0.0}
        eq = self._equalizer
        if eq is None:
            return out
        try:
            out["presets"] = list(eq.presetNames())
        except Exception:
            pass
        try:
            out["currentPreset"] = int(eq.currentPreset())
        except Exception:
            pass
        try:
            out["bands"] = list(eq.bandLabels())
        except Exception:
            pass
        try:
            out["amps"] = [float(eq.amp_at(b)) for b in range(len(out["bands"]))]
        except Exception:
            pass
        try:
            out["preamp"] = float(eq.preamp())
        except Exception:
            pass
        return out

    def _subs_snapshot(self) -> dict:
        out = {"mediaName": "", "searching": False, "busyIndex": -1,
               "status": "", "statusIsError": False, "best": [], "others": [],
               "languages": []}
        subs = self._subs
        if subs is None:
            return out
        for key, attr in (
            ("mediaName", "_get_media_name"), ("searching", "_get_searching"),
            ("busyIndex", "_get_busy_index"), ("status", "_get_status"),
            ("statusIsError", "_get_status_is_error"), ("best", "_get_best"),
            ("others", "_get_others"), ("languages", "_get_languages"),
        ):
            try:
                value = getattr(subs, attr)()
                if key in ("best", "others", "languages"):
                    value = list(value)
                out[key] = value
            except Exception:
                pass
        return out

    # ------------------------------------------------------------- dispatch ---
    @Slot(str, dict)
    def _dispatch(self, action: str, payload: dict) -> None:
        """Run a remote command on the Qt thread. Never raises to the caller:
        each handler is individually guarded so one bad payload cannot take
        down the queue."""
        log.debug("remote command: %s %s", action, payload)
        handler = getattr(self, f"_cmd_{action.replace('.', '_')}", None)
        if handler is None:
            log.warning("remote command ignored: %s", action)
            return
        try:
            handler(payload or {})
        except Exception:
            log.exception("remote command failed: %s", action)
        finally:
            # Push the resulting state to the phone quickly.
            QTimer.singleShot(40, self.publish_now)

    # ------------------------------------------------------- player cmds ----
    def _uses_player(self) -> bool:
        try:
            mode = self._controller.activeMode if self._controller else ""
        except Exception:
            mode = ""
        return mode in PLAYER_MODES

    def _cmd_playPause(self, _p: dict) -> None:
        if self._uses_player() and self._controller is not None:
            self._controller.playPause()

    def _cmd_play(self, _p: dict) -> None:
        if self._uses_player() and self._controller is not None:
            self._controller.play()

    def _cmd_pause(self, _p: dict) -> None:
        if self._uses_player() and self._controller is not None:
            self._controller.pause()

    def _cmd_stop(self, _p: dict) -> None:
        if self._uses_player() and self._controller is not None:
            self._controller.stop()

    def _cmd_next(self, _p: dict) -> None:
        if self._uses_player() and self._controller is not None:
            self._controller.next()

    def _cmd_previous(self, _p: dict) -> None:
        if self._uses_player() and self._controller is not None:
            self._controller.previous()

    def _cmd_seekTo(self, p: dict) -> None:
        if self._uses_player() and self._engine is not None:
            self._engine.seek(int(p.get("ms", 0)))

    def _cmd_seekRelative(self, p: dict) -> None:
        if self._uses_player() and self._engine is not None:
            self._engine.seek_relative(int(p.get("ms", 0)))

    def _cmd_seekFraction(self, p: dict) -> None:
        if self._uses_player() and self._engine is not None:
            self._engine.set_position(float(p.get("f", 0.0)))

    def _cmd_setRate(self, p: dict) -> None:
        if self._uses_player() and self._engine is not None:
            self._engine.set_rate(float(p.get("rate", 1.0)))

    def _cmd_setVolume(self, p: dict) -> None:
        if self._engine is None:
            return
        vol = max(0, min(100, int(p.get("volume", 0))))
        self._engine.set_volume(vol)
        if self._settings is not None:
            self._settings.set("audio.volume", vol)

    def _cmd_toggleMute(self, _p: dict) -> None:
        if self._engine is None:
            return
        self._engine.toggle_mute()
        if self._settings is not None:
            self._settings.set("audio.muted", bool(self._engine.muted()))

    def _cmd_setAudioTrack(self, p: dict) -> None:
        if self._controller is not None:
            self._controller.setAudioTrack(int(p.get("id", -1)))

    def _cmd_setSubtitleTrack(self, p: dict) -> None:
        if self._controller is not None:
            self._controller.setSubtitleTrack(int(p.get("id", -1)))

    def _cmd_adjustSubtitleDelay(self, p: dict) -> None:
        if self._controller is not None:
            self._controller.adjustSubtitleDelay(int(p.get("delta", 0)))

    def _cmd_loadSubtitleFile(self, p: dict) -> None:
        path = str(p.get("path", ""))
        if path and self._controller is not None:
            self._controller.loadSubtitle(path)

    # ------------------------------------------------------ playlist cmds ----
    def _cmd_openPath(self, p: dict) -> None:
        path = str(p.get("path", ""))
        if path and self._controller is not None:
            self._controller.openPath(path)

    def _cmd_addPaths(self, p: dict) -> None:
        paths = list(p.get("paths", []))
        if paths and self._controller is not None:
            self._controller.addPaths(paths)

    def _cmd_playIndex(self, p: dict) -> None:
        if self._controller is not None:
            self._controller.playIndex(int(p.get("index", -1)))

    def _cmd_moveItem(self, p: dict) -> None:
        if self._controller is not None:
            self._controller.moveItem(int(p.get("from", -1)), int(p.get("to", -1)))

    def _cmd_clearSelected(self, p: dict) -> None:
        if self._controller is not None:
            self._controller.clearSelected(list(p.get("rows", [])))

    def _cmd_clearPlaylist(self, _p: dict) -> None:
        if self._controller is not None:
            self._controller.clearPlaylist()

    def _cmd_cycleRepeat(self, _p: dict) -> None:
        if self._controller is not None:
            self._controller.cycleRepeat()

    def _cmd_toggleShuffle(self, _p: dict) -> None:
        if self._controller is not None:
            self._controller.toggleShuffle()

    # ----------------------------------------------------------- mode/window ---
    def _cmd_switchMode(self, p: dict) -> None:
        if self._controller is not None:
            self._controller.setActiveMode(str(p.get("id", "local")))

    def _cmd_fullscreen(self, _p: dict) -> None:
        self.toggleFullscreenRequested.emit()

    def _cmd_pip(self, _p: dict) -> None:
        self.togglePipRequested.emit()

    # -------------------------------------------------------------- m3u cmds ---
    def _m3u(self):
        return self._contexts.get("m3u")

    def _cmd_m3u_addSource(self, p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.addSource(str(p.get("name", "")), str(p.get("url", "")), "url")

    def _cmd_m3u_removeSource(self, p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.removeSource(str(p.get("id", "")))

    def _cmd_m3u_loadSource(self, p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.loadSource(str(p.get("id", "")))

    def _cmd_m3u_playRow(self, p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.channels().play_index(int(p.get("row", -1)))

    def _cmd_m3u_setFavourite(self, p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.channels().set_favourite_url(str(p.get("url", "")), bool(p.get("on", False)))

    def _cmd_m3u_setFilter(self, p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.channels().setFilter(str(p.get("text", "")))

    def _cmd_m3u_setGrouping(self, p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.channels().setGrouping(str(p.get("mode", "category")))

    def _cmd_m3u_setFavouritesOnly(self, p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.channels().setFavouritesOnly(bool(p.get("on", False)))

    def _cmd_m3u_toggleGroup(self, p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.channels().toggleGroup(str(p.get("key", "")))

    def _cmd_m3u_retry(self, _p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.retry()

    def _cmd_m3u_clearStatus(self, _p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.clearStatus()

    # -------------------------------------------------------------- web cmds ---
    def _web(self):
        return self._contexts.get("web")

    def _cmd_web_navigate(self, p: dict) -> None:
        ctx = self._web()
        url = str(p.get("url", ""))
        if ctx is not None and url:
            ctx.navigateActive(url)

    def _cmd_web_back(self, _p: dict) -> None:
        ctx = self._web()
        if ctx is not None:
            ctx.goBack()

    def _cmd_web_forward(self, _p: dict) -> None:
        ctx = self._web()
        if ctx is not None:
            ctx.goForward()

    def _cmd_web_reload(self, _p: dict) -> None:
        ctx = self._web()
        if ctx is not None:
            ctx.reloadOrStop()

    def _cmd_web_bookmarkAdd(self, p: dict) -> None:
        ctx = self._web()
        if ctx is not None:
            ctx.addBookmark(str(p.get("title", "")), str(p.get("url", "")))

    def _cmd_web_bookmarkRemove(self, p: dict) -> None:
        ctx = self._web()
        if ctx is not None:
            ctx.removeBookmark(str(p.get("url", "")))

    def _cmd_web_media(self, p: dict) -> None:
        ctx = self._web()
        if ctx is not None:
            getattr(ctx, "mediaControl")(str(p.get("action", "")), p.get("value"))

    # ---------------------------------------------------------------- eq cmds --
    def _cmd_eq_preset(self, p: dict) -> None:
        if self._equalizer is not None:
            self._equalizer.apply_preset(int(p.get("index", 0)))

    def _cmd_eq_band(self, p: dict) -> None:
        if self._equalizer is not None:
            self._equalizer.set_amp(int(p.get("band", 0)), float(p.get("value", 0.0)))

    def _cmd_eq_preamp(self, p: dict) -> None:
        if self._equalizer is not None:
            self._equalizer.set_preamp(float(p.get("value", 0.0)))

    def _cmd_eq_reset(self, _p: dict) -> None:
        if self._equalizer is not None:
            self._equalizer.reset()

    # -------------------------------------------------------------- subs cmds --
    def _cmd_subs_search(self, p: dict) -> None:
        if self._subs is not None:
            self._subs.search(str(p.get("query", "")))

    def _cmd_subs_download(self, p: dict) -> None:
        if self._subs is not None:
            self._subs.download(int(p.get("index", -1)))

    def _cmd_subs_languages(self, p: dict) -> None:
        if self._subs is not None:
            self._subs.languages = list(p.get("languages", []))

    def _cmd_subs_clear(self, _p: dict) -> None:
        if self._subs is not None:
            self._subs.clearResults()

    # ------------------------------------------------------------- power cmds --
    def _cmd_power_sleep(self, _p: dict) -> None:
        power_actions.sleep_pc()

    def _cmd_power_shutdown(self, _p: dict) -> None:
        power_actions.shutdown_pc()
