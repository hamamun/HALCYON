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
POLL_MS = 300  # reduced from 500 for web media responsiveness (seekbar 400ms probe)

#: Player-bearing modes — where transport commands are legal (§P3.6: Web is
#: inert; the page owns its own playback).
PLAYER_MODES = ("local", "m3u")


def read(obj, attr, default=None):
    """Read ``attr`` off ``obj``, calling it when it is a zero-arg callable.

    The same state is exposed two ways across the codebase: ``AppController``
    publishes ``activeMode`` as a Qt ``Property`` (a plain value), while other
    contexts and the test fakes expose it as a method. Reading it blind leaks a
    *bound method* into the snapshot, which is not JSON-serialisable — the
    phone then gets an HTTP 500 from ``/api/status``. Normalise both shapes in
    exactly one place (§4.1) instead of repeating the ternary at every site.
    """
    try:
        val = getattr(obj, attr, default)
    except Exception:
        return default
    if callable(val):
        try:
            return val()
        except Exception:
            return default
    return val


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
        # Resume is announced by AppController only when a newly opened file
        # has a meaningful saved position. Keep it in the remote snapshot so
        # the phone can offer the same choice as the desktop toast.
        self._resume: dict = {"available": False, "path": "", "time": 0}
        resume_signal = getattr(controller, "resumePrompted", None)
        if resume_signal is not None:
            resume_signal.connect(self._on_resume_prompted)

        self.store = StatusStore()
        self._server_url = ""
        # Cache for heavy M3U channel snapshot — rebuilt only when the model
        # actually changes, not on every 500 ms tick (§R.4 perf for thousands).
        self._m3u_cache_sig = None
        self._m3u_cache_rows: list[dict] = []

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
        if context is None:
            return
        self._contexts[mode_id] = context
        # For web, connect relevant signals so publish_now fires immediately,
        # not only on the 300 ms timer. Gives <200 ms perceived response
        # for bookmark taps and media seek.
        if mode_id == "web":
            try:
                for sig_name in ("tabsChanged", "activeTabChanged", "bookmarksChanged",
                                 "mediaStatusChanged", "activeTabIndexChanged",
                                 "windowTitleChanged"):
                    sig = getattr(context, sig_name, None)
                    if sig is not None and hasattr(sig, "connect"):
                        # Use a queued singleShot to coalesce rapid media probes
                        sig.connect(lambda: QTimer.singleShot(25, self.publish_now))
            except Exception:
                pass

    def context(self, mode_id: str) -> QObject | None:
        return self._contexts.get(mode_id)

    # ---------------------------------------------------------- server side ---
    def request(self, action: str, payload: dict | None = None) -> None:
        """Thread-safe command entry point — safe from the aiohttp thread."""
        self.commandRequested.emit(action, payload or {})

    # ------------------------------------------------------------- status ----
    @Slot(str, int)
    def _on_resume_prompted(self, path: str, position_ms: int) -> None:
        self._resume = {
            "available": bool(path and position_ms > 0),
            "path": str(path or ""),
            "time": max(0, int(position_ms)),
        }
        self.publish_now()

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

        mode = read(controller, "activeMode", "local") if controller else "local"
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
                player[key] = read(engine, attr, player.get(key))
            # hasVideo and subsAvailable come from the controller/tracks
            if controller:
                try:
                    player["hasVideo"] = bool(controller.hasVideo)
                    player["subsAvailable"] = bool(controller.subtitlesAvailable)
                except Exception:
                    pass
        player["resume"] = dict(self._resume)
        snap["player"] = player

        # ---- now playing ------------------------------------------------
        label = ""
        if controller:
            lp = getattr(controller, "currentPlaybackLabel", None)
            label = lp() if callable(lp) else lp
        stem = getattr(controller, "currentFileStem", "") if controller else ""
        snap["nowPlaying"] = {"label": label or "", "stem": stem or ""}

        # ---- tracks ------------------------------------------------------
        tracks: dict = {"audio": [], "currentAudio": -1, "subtitle": [],
                        "currentSubtitle": -1, "delayMs": 0}
        if controller is not None:
            for key, attr in (
                ("audio", "audioTracks"), ("subtitle", "subtitleTracks"),
                ("currentAudio", "currentAudioId"), ("currentSubtitle", "currentSubtitleId"),
                ("delayMs", "subtitleDelayMs")
            ):
                tracks[key] = read(controller, attr, tracks.get(key))
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
        for key, attr in (("currentIndex", "currentIndex"), ("repeatMode", "repeatMode"), ("shuffle", "shuffle")):
            out[key] = read(ctx, attr, out.get(key))
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
        
        for key, attr in (
            ("sources", "sources"), ("sourcesFull", "sourcesFull"),
            ("currentSource", "currentSourceName"), ("loading", "loading"),
            ("status", "statusMessage"), ("statusIsError", "statusIsError"),
            ("currentChannel", "currentChannelName")
        ):
            out[key] = read(ctx, attr, out.get(key))

        model = self._m3u_channels()
        if model is not None:
            for key, attr in (
                ("grouping", "grouping"), ("favouritesOnly", "favouritesOnly"),
                ("expandedGroup", "expandedGroup")
            ):
                out[key] = read(model, attr, out.get(key))
            # The channel list is only useful while M3U is the active mode and
            # only as big as the current view (filtered/grouped) — bound it.
            if mode == "m3u":
                try:
                    count = int(read(model, "count", 0) or 0)
                    out["channelCount"] = count
                    # Build a signature that changes only when the visible list
                    # really changes — avoids rebuilding 15k dicts every 500 ms.
                    try:
                        total = int(read(model, "totalCount", 0) or 0)
                    except Exception:
                        total = 0
                    grouping_val = read(model, "grouping", "")
                    fav_only = bool(read(model, "favouritesOnly", False))
                    try:
                        filt = getattr(model, "_filter", "")
                    except Exception:
                        filt = ""
                    try:
                        cur_idx = int(read(model, "currentIndex", -1))
                    except Exception:
                        cur_idx = -1
                    try:
                        fav_set = frozenset(getattr(model, "_favourite_urls", set()) or set())
                    except Exception:
                        fav_set = frozenset()
                    try:
                        ch_id = id(getattr(model, "_channels", None))
                    except Exception:
                        ch_id = 0
                    sig = (ch_id, count, total, grouping_val, fav_only, filt, cur_idx, fav_set)

                    if sig == self._m3u_cache_sig and self._m3u_cache_rows:
                        out["channels"] = self._m3u_cache_rows
                    else:
                        rows = []
                        # cur_idx already computed above
                        for i in range(count):
                            ch = model.channel_at(i)
                            if ch is None:
                                continue
                            rows.append({
                                "name": ch.name, "url": ch.url, "group": ch.group,
                                "country": ch.country, "language": ch.language,
                                # Same filtered logo the desktop list uses, so
                                # the phone does not spend its data re-fetching
                                # URLs already known to be dead (§M2.3). Falls
                                # back to the raw value for models that predate
                                # the filter (the bridge's own fakes).
                                "logo": (model.display_logo(ch)
                                         if hasattr(model, "display_logo") else ch.logo),
                                "fav": model.is_favourite(ch.url),
                                "current": i == cur_idx,
                            })
                        self._m3u_cache_sig = sig
                        self._m3u_cache_rows = rows
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
        for key, attr in (
            ("tabCount", "tabCount"), ("tabs", "tabs"), ("activeTab", "activeTab"),
            ("runtimeAvailable", "runtimeAvailable"), ("bookmarks", "bookmarkItems"),
            ("activeTabBookmarked", "activeTabBookmarked")
        ):
            out[key] = read(ctx, attr, out.get(key))
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
        for key, attr in (
            ("presets", "presetNames"), ("currentPreset", "currentPreset"),
            ("bands", "bandLabels"), ("preamp", "preamp")
        ):
            out[key] = read(eq, attr, out.get(key))
        try:
            if hasattr(eq, "amp_at"):
                out["amps"] = [float(eq.amp_at(b)) for b in range(len(out["bands"]))]
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
        mode = read(self._controller, "activeMode", "") if self._controller else ""
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
        self._resume = {"available": False, "path": "", "time": 0}

    def _cmd_startOver(self, p: dict) -> None:
        if self._uses_player() and self._controller is not None:
            path = str(p.get("path", ""))
            if path:
                self._controller.startOver(path)
                self._resume = {"available": False, "path": "", "time": 0}

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
            self._resume = {"available": False, "path": "", "time": 0}
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
        self._m3u_cache_sig = None
        self._m3u_cache_rows = []

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

    def _m3u_channels(self):
        ctx = self._m3u()
        if ctx is None:
            return None
        try:
            return read(ctx, "channels", None)
        except Exception:
            return None

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
        self._m3u_cache_sig = None
        self._m3u_cache_rows = []

    def _cmd_m3u_playRow(self, p: dict) -> None:
        model = self._m3u_channels()
        if model is not None:
            model.play_index(int(p.get("row", -1)))

    def _cmd_m3u_setFavourite(self, p: dict) -> None:
        model = self._m3u_channels()
        ctx = self._m3u()
        if model is None:
            return
        url = str(p.get("url", "")).strip()
        on = bool(p.get("on", False))
        if not url:
            return
        # Persist to the per-source store when we have a saved source — mirrors
        # QML's toggleFavourite path which updates both model and store.
        if ctx is not None:
            try:
                source_id = getattr(ctx, "_current_source_id", "") or ""
                fav_store = getattr(ctx, "_favourites", None)
                if source_id and fav_store is not None:
                    fav_store.set(source_id, url, on)
            except Exception:
                pass
        model.set_favourite_url(url, on)
        # Invalidate channel cache so the new fav flag is sent immediately.
        self._m3u_cache_sig = None

    def _cmd_m3u_setFilter(self, p: dict) -> None:
        model = self._m3u_channels()
        if model is not None:
            model.setFilter(str(p.get("text", "")))
        self._m3u_cache_sig = None

    def _cmd_m3u_setGrouping(self, p: dict) -> None:
        model = self._m3u_channels()
        if model is not None:
            model.setGrouping(str(p.get("mode", "category")))
        self._m3u_cache_sig = None

    def _cmd_m3u_setFavouritesOnly(self, p: dict) -> None:
        model = self._m3u_channels()
        if model is not None:
            model.setFavouritesOnly(bool(p.get("on", False)))
        self._m3u_cache_sig = None

    def _cmd_m3u_toggleGroup(self, p: dict) -> None:
        model = self._m3u_channels()
        if model is not None:
            model.toggleGroup(str(p.get("key", "")))
        self._m3u_cache_sig = None

    def _cmd_m3u_retry(self, _p: dict) -> None:
        ctx = self._m3u()
        if ctx is not None:
            ctx.retry()
        self._m3u_cache_sig = None
        self._m3u_cache_rows = []

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

    def _cmd_web_openInNewTab(self, p: dict) -> None:
        """Open URL in a NEW tab – primary path for remote bookmarks (§R.2).

        Also ensures Web mode is active on the PC so the new page becomes
        visible immediately (stage active -> hosts visible).
        """
        ctx = self._web()
        url = str(p.get("url", ""))
        if ctx is None or not url:
            return
        try:
            # Switch PC to Web if not already – avoids hidden background nav
            if self._controller is not None:
                cur = read(self._controller, "activeMode", "")
                if cur != "web":
                    self._controller.setActiveMode("web")
        except Exception:
            pass
        # Add as new tab (respects MAX_TABS)
        try:
            # Prefer explicit openInNewTab slot if available (newer BrowserContext)
            opener = getattr(ctx, "openInNewTab", None) or getattr(ctx, "addTab", None)
            if callable(opener):
                opener(url)
            else:
                ctx.navigateActive(url)
        except Exception:
            try:
                ctx.navigateActive(url)
            except Exception:
                pass

    def _cmd_web_openBookmark(self, p: dict) -> None:
        """Alias – bookmark tap always opens new tab per UX spec."""
        self._cmd_web_openInNewTab(p)

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
            query = str(p.get("query", "")).strip()
            # The desktop dialog pre-fills its query. The remote has no
            # desktop text field, so use the current media stem as the same
            # fallback when the phone submits an empty field.
            if not query and self._controller is not None:
                query = str(getattr(self._controller, "currentFileStem", "") or "")
            self._subs.search(query)

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
