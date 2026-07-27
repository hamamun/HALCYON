"""The application controller — the Python half of the Actions host.

QML's ``actionHost`` (ui/Main.qml) routes UI intent here; this object owns the
behaviour and talks to the engine, the library and the active mode's data. One
implementation per action, on both sides of the QML boundary (§4.1).

**Mode neutrality.** This class knows about ``ModeSpec`` and about the *active*
mode's context object, never about a specific mode by name. Local's playlist is
reached through a registered context object, so Phase 2 can add M3U without a
single edit here (§A.3).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from core import modes as mode_registry
from core import paths
from core.mode_api import ModeSpec

log = logging.getLogger(__name__)


class ModeList(QObject):
    """Exposes the registry to QML so the title bar can render its chips
    without knowing which modes exist (§P1.4)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._specs = mode_registry.all_modes()

    @Property("QVariantList", constant=True)
    def list(self) -> list:
        return [self._as_dict(spec) for spec in self._specs]

    @Slot(str, result="QVariant")
    def spec(self, mode_id: str):
        """Look up a mode, falling back to the default rather than to null.

        QML calls this during binding evaluation, sometimes before
        ``App.activeMode`` has propagated. Returning ``None`` there turns every
        downstream ``modeSpec.usesPlayer`` into a TypeError, so an unknown id
        resolves to the default mode — Local — which is always registered.
        """
        found = mode_registry.find(mode_id)
        if found is None:
            log.warning("unknown mode %r — falling back to the default", mode_id)
            found = mode_registry.default_mode()
        return self._as_dict(found)

    @staticmethod
    def _as_dict(spec: ModeSpec) -> dict:
        # Modes declare their QML as qrc: URLs (the packaged form). Resolve them
        # to real files when running from a checkout — see core.paths.qml_url.
        return {
            "id": spec.id,
            "title": spec.title,
            "panelQml": paths.qml_url(spec.panel_qml),
            "stageQml": paths.qml_url(spec.stage_qml),
            "transportQml": paths.qml_url(spec.transport_qml),
            "osdEnabled": spec.osd_enabled,
            "mediaKeysEnabled": spec.media_keys_enabled,
            "usesPlayer": spec.uses_player,
        }


class AppController(QObject):
    """Behaviour behind the Actions."""

    activeModeChanged = Signal()
    subtitleDelayChanged = Signal()
    tracksChanged = Signal()
    resumePrompted = Signal(str, int)

    def __init__(
        self,
        engine,
        settings,
        library,
        metadata,
        lyrics,
        equalizer,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._settings = settings
        self._library = library
        self._metadata = metadata
        self._lyrics = lyrics
        self._equalizer = equalizer

        self._active_mode = settings.get("ui.mode", "local")
        if mode_registry.find(self._active_mode) is None:
            self._active_mode = mode_registry.default_mode().id

        #: Per-mode playlist/context objects, registered at startup. The
        #: controller never names a mode; it looks one up.
        self._contexts: dict[str, QObject] = {}

        self._subtitle_delay = 0
        self._audio_tracks: list[dict] = []
        self._subtitle_tracks: list[dict] = []

        engine.mediaChanged.connect(self._on_media_changed)
        engine.endReached.connect(self._on_end_reached)
        engine.timeChanged.connect(self._lyrics.update_position)
        engine.tracksChanged.connect(self._refresh_tracks)

    # ---------------------------------------------------------- registration ---
    def register_context(self, mode_id: str, context: QObject) -> None:
        self._contexts[mode_id] = context

    def context(self, mode_id: str | None = None) -> QObject | None:
        return self._contexts.get(mode_id or self._active_mode)

    @property
    def playlist(self):
        """The active mode's list-like context, if it has one."""
        return self._contexts.get(self._active_mode)

    # ------------------------------------------------------------------ mode ---
    @Property(str, notify=activeModeChanged)
    def activeMode(self) -> str:  # noqa: N802 - QML-facing
        return self._active_mode

    @Slot(str)
    def setActiveMode(self, mode_id: str) -> None:  # noqa: N802 - QML-facing
        """Change the band, not the radio (§A.1).

        Each mode keeps its own data, so switching away and back leaves a
        playlist exactly as it was. Nothing is cleared and nothing crosses over.
        """
        if mode_id == self._active_mode or mode_registry.find(mode_id) is None:
            return
        self._active_mode = mode_id
        self._settings.set("ui.mode", mode_id)
        self.activeModeChanged.emit()
        log.info("mode -> %s", mode_id)

    # -------------------------------------------------------------- playlist ---
    @Slot(list)
    @Slot("QVariant")
    def addPaths(self, incoming) -> None:  # noqa: N802 - QML-facing
        """The one append path — Add Files, Add Folder, Ctrl+O and drag-and-drop
        all arrive here (§4.1).

        The parameter is deliberately **not** called ``paths``: this module
        imports a module of that name, and shadowing it inside the one method
        that does path handling is how you get an ``AttributeError`` at the
        worst possible moment.

        Overloaded on ``QVariant`` as well as ``list`` so a JS array from QML
        binds whichever way PySide marshals it.
        """
        target = self.playlist
        if target is None or not hasattr(target, "add_paths"):
            log.warning("addPaths: active mode %r has no queue", self._active_mode)
            return

        if isinstance(incoming, (str, bytes)):
            incoming = [incoming]
        cleaned = [_normalise(p) for p in incoming or []]
        cleaned = [p for p in cleaned if p]
        if not cleaned:
            return

        # Dropping a .srt on the window means "subtitle what is playing", not
        # "queue this file". Split them out before the queue ever sees them: a
        # subtitle added as a track opens as media with no audio and no video,
        # which tears down the video pipeline mid-playback.
        subtitles = [p for p in cleaned if _is_subtitle(p)]
        media = [p for p in cleaned if not _is_subtitle(p)]

        if subtitles and not media:
            self._attach_subtitles(subtitles)
            return
        if subtitles:
            # Mixed drop (a video and its sidecar): queue the media, and let
            # the sidecar be picked up by the normal auto-load on open.
            log.info("ignoring %d subtitle file(s) alongside media", len(subtitles))

        cleaned = media
        if not cleaned:
            return

        was_empty = target.current_index() < 0
        added = target.add_paths(cleaned)
        log.info("addPaths: %d path(s) in, %d track(s) queued", len(cleaned), added)
        if added and was_empty:
            target.play_index(0)

    @Slot(list)
    def clearSelected(self, rows: list) -> None:  # noqa: N802 - QML-facing
        """Remove the selected rows. If the currently playing track was removed,
        auto-start the next available track or stop if queue is empty.
        """
        target = self.playlist
        if target is None or not hasattr(target, "remove_rows"):
            return
        wanted = [int(r) for r in rows if isinstance(r, (int, float, str))]
        if not wanted:
            return

        cur = getattr(target, "current_index", lambda: -1)()
        playing_removed = (cur in wanted)
        removed_before = len([r for r in wanted if r < cur]) if playing_removed else 0

        target.remove_rows(wanted)

        new_count = getattr(target, "count", 0)

        if playing_removed:
            if new_count == 0:
                self._engine.stop()
                self._metadata.load("")
                self._lyrics.load("")
            else:
                target_idx = cur - removed_before
                if target_idx < new_count:
                    next_idx = target_idx
                else:
                    rep = getattr(target, "repeat_mode", lambda: 0)()
                    next_idx = 0 if rep == 2 else new_count - 1

                target.play_index(next_idx)

    @Slot()
    def clearPlaylist(self) -> None:  # noqa: N802 - QML-facing
        """Empty the queue *and* stop the player.

        An empty playlist with audio still coming out of the speakers is the
        clearest possible contradiction between what the UI says and what the
        app is doing.
        """
        target = self.playlist
        if target is not None and hasattr(target, "clear"):
            target.clear()
        self._engine.stop()
        self._metadata.load("")
        self._lyrics.load("")

    def _current_path(self) -> str:
        """Filesystem path of whatever the engine currently has open."""
        return _from_uri(self._engine.currentMedia or "")

    def _stop_if_orphaned(self, playing_path: str) -> None:
        """Stop playback if ``playing_path`` is no longer in the queue."""
        if not playing_path:
            return
        target = self.playlist
        if target is None:
            return
        still_queued = False
        path_at = getattr(target, "path_at", None)
        count = getattr(target, "count", 0)
        if callable(path_at):
            for row in range(int(count)):
                if path_at(row) == playing_path:
                    still_queued = True
                    break
        if not still_queued:
            self._engine.stop()
            self._metadata.load("")
            self._lyrics.load("")

    @Slot(int)
    def playIndex(self, row: int) -> None:  # noqa: N802 - QML-facing
        target = self.playlist
        if target is not None and hasattr(target, "play_index"):
            target.play_index(row)

    @Slot(int, int)
    def moveItem(self, source: int, target_row: int) -> None:  # noqa: N802
        target = self.playlist
        if target is not None and hasattr(target, "move_row"):
            target.move_row(source, target_row)

    @Slot()
    def next(self) -> None:
        target = self.playlist
        if target is not None and hasattr(target, "play_next"):
            target.play_next()

    @Slot()
    def previous(self) -> None:
        target = self.playlist
        if target is not None and hasattr(target, "play_previous"):
            target.play_previous()

    @Slot()
    def cycleRepeat(self) -> None:  # noqa: N802 - QML-facing
        target = self.playlist
        if target is not None and hasattr(target, "cycle_repeat"):
            target.cycle_repeat()

    @Slot()
    def toggleShuffle(self) -> None:  # noqa: N802 - QML-facing
        target = self.playlist
        if target is not None and hasattr(target, "toggle_shuffle"):
            target.toggle_shuffle()

    # -------------------------------------------------------------- playback ---
    @Slot()
    def playPause(self) -> None:  # noqa: N802 - QML-facing
        """Toggle play/pause, or start playing from playlist if stopped."""
        from engine.vlc_engine import State

        state = self._engine.state
        if state in (State.Playing, State.Paused):
            self._engine.toggle()
            return

        target = self.playlist
        if target is not None:
            count = getattr(target, "count", 0)
            if count > 0:
                cur = getattr(target, "current_index", lambda: -1)()
                if 0 <= cur < count:
                    target.play_index(cur)
                else:
                    target.play_index(0)
            return

        if self._engine.currentMedia:
            self._engine.play()

    @Slot()
    def play(self) -> None:  # noqa: N802 - QML-facing
        from engine.vlc_engine import State

        state = self._engine.state
        if state == State.Paused:
            self._engine.play()
            return

        target = self.playlist
        if target is not None:
            count = getattr(target, "count", 0)
            if count > 0:
                cur = getattr(target, "current_index", lambda: -1)()
                if 0 <= cur < count:
                    target.play_index(cur)
                else:
                    target.play_index(0)
            return

        if self._engine.currentMedia:
            self._engine.play()

    @Slot()
    def pause(self) -> None:  # noqa: N802 - QML-facing
        self._engine.pause()

    @Slot()
    def stop(self) -> None:  # noqa: N802 - QML-facing
        self._engine.stop()
        self._metadata.load("")
        self._lyrics.load("")

    @Slot(str)
    def openPath(self, path: str) -> None:  # noqa: N802 - QML-facing
        resume_ms = 0
        if self._settings.get("playback.resumeEnabled", True):
            resume_ms = self._library.resume_position(path)
        self._engine.open(path, resume_ms)
        if resume_ms:
            self.resumePrompted.emit(path, resume_ms)

    def _on_media_changed(self, mrl: str) -> None:
        path = _from_uri(mrl)
        self._library.note_opened(path)
        self._metadata.load(path)
        self._lyrics.load(path)
        self._equalizer.reapply()
        self._subtitle_delay = 0
        self.subtitleDelayChanged.emit()
        if self._settings.get("subs.autoLoadSidecar", True):
            self._auto_load_subtitle(path)
        self._refresh_tracks()

    def _on_end_reached(self) -> None:
        """Advance the queue. Repeat/shuffle logic lives in the playlist model,
        in one place, so this is just a nudge."""
        target = self.playlist
        if target is not None and hasattr(target, "play_next"):
            played = target.play_next()
            if not played:
                self._engine.stop()
                self._metadata.load("")
                self._lyrics.load("")

    def _attach_subtitles(self, paths: list[str]) -> None:
        """Load dropped subtitle files onto whatever is currently playing."""
        if not self._engine.currentMedia:
            log.info("subtitle dropped with nothing playing — ignored")
            return
        for path in paths:
            if self._engine.add_subtitle_file(path):
                log.info("loaded subtitle %s", Path(path).name)
            else:
                log.warning("could not load subtitle %s", Path(path).name)
        self._refresh_tracks()

    def _auto_load_subtitle(self, path: str) -> None:
        media = Path(path)
        for suffix in (".srt", ".ass", ".ssa", ".sub", ".vtt"):
            sidecar = media.with_suffix(suffix)
            if sidecar.exists():
                self._engine.add_subtitle_file(str(sidecar))
                log.info("auto-loaded subtitle %s", sidecar.name)
                return

    # ---------------------------------------------------------------- tracks ---
    def _refresh_tracks(self) -> None:
        try:
            self._audio_tracks = [
                {"id": tid, "label": label} for tid, label in self._engine.audio_tracks()
            ]
            self._subtitle_tracks = [
                {"id": tid, "label": label} for tid, label in self._engine.subtitle_tracks()
            ]
        except Exception:
            self._audio_tracks = []
            self._subtitle_tracks = []
        self.tracksChanged.emit()

    @Property("QVariantList", notify=tracksChanged)
    def audioTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._audio_tracks

    @Property("QVariantList", notify=tracksChanged)
    def subtitleTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._subtitle_tracks

    @Slot(int)
    def setAudioTrack(self, track_id: int) -> None:  # noqa: N802 - QML-facing
        self._engine.set_audio_track(track_id)

    @Slot(int)
    def setSubtitleTrack(self, track_id: int) -> None:  # noqa: N802 - QML-facing
        self._engine.set_subtitle_track(track_id)

    @Slot()
    def cycleAudioTrack(self) -> None:  # noqa: N802 - QML-facing
        self._cycle(self._audio_tracks, self._engine.set_audio_track)

    @Slot()
    def cycleSubtitleTrack(self) -> None:  # noqa: N802 - QML-facing
        self._cycle(self._subtitle_tracks, self._engine.set_subtitle_track)

    @staticmethod
    def _cycle(tracks: list[dict], setter) -> None:
        if not tracks:
            return
        setter(tracks[0]["id"])

    @Slot(str)
    def loadSubtitle(self, url: str) -> None:  # noqa: N802 - QML-facing
        self._engine.add_subtitle_file(_normalise(url))
        self._refresh_tracks()

    @Slot(int)
    def adjustSubtitleDelay(self, delta_ms: int) -> None:  # noqa: N802 - QML-facing
        self._subtitle_delay += int(delta_ms)
        self._engine.set_subtitle_delay(self._subtitle_delay)
        self.subtitleDelayChanged.emit()

    @Property(int, notify=subtitleDelayChanged)
    def subtitleDelayMs(self) -> int:  # noqa: N802 - QML-facing
        return self._subtitle_delay

    # -------------------------------------------------------------- shutdown ---
    def shutdown(self) -> None:
        # Modes first: stop background work (duration probes) before the objects
        # it reports into start disappearing. Each step is independent, so one
        # failure must not skip the settings flush that follows it.
        for mode_id, context in self._contexts.items():
            shutdown = getattr(context, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    log.exception("mode %r failed to shut down", mode_id)
        for step in (self._library.shutdown, self._equalizer.release, self._settings.flush):
            try:
                step()
            except Exception:
                log.exception("shutdown step %s failed", getattr(step, "__name__", step))


#: Kept in step with modes.local.playlist.SUBTITLE_EXTENSIONS, imported lazily
#: so core/ never depends on a mode package at import time (§A.1).
def _is_subtitle(path: str) -> bool:
    from modes.local.playlist import SUBTITLE_EXTENSIONS

    return Path(path).suffix.lower() in SUBTITLE_EXTENSIONS


def _normalise(raw) -> str:
    """One URL->path implementation, shared with the playlist model (§4.1)."""
    return paths.normalise_path(raw)


def _from_uri(mrl: str) -> str:
    return _normalise(mrl)
