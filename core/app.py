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

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core import modes as mode_registry
from core import paths
from core.media_types import is_media_path, is_subtitle_path
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
    mediaNameChanged = Signal()

    def __init__(
        self,
        engine,
        settings,
        library,
        metadata,
        lyrics,
        equalizer,
        video_adjust=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._settings = settings
        self._library = library
        self._metadata = metadata
        self._lyrics = lyrics
        self._equalizer = equalizer
        self._video_adjust = video_adjust

        self._active_mode = settings.get("ui.mode", "local")
        if mode_registry.find(self._active_mode) is None:
            self._active_mode = mode_registry.default_mode().id

        #: Per-mode playlist/context objects, registered at startup. The
        #: controller never names a mode; it looks one up.
        self._contexts: dict[str, QObject] = {}

        self._subtitle_delay = 0
        self._audio_tracks: list[dict] = []
        self._video_tracks: list[dict] = []
        self._subtitle_tracks: list[dict] = []
        #: Drives the CC button's availability badge (§P1.6): true only when
        #: the current video has subtitles the user could switch on. Recomputed
        #: in _refresh_tracks so it tracks reality the instant tracks arrive.
        self._subtitles_available = False
        # Split views of the same spu list: tracks found inside the media vs
        # files this session attached (add_slave). One spu id appears in
        # exactly one of them.
        self._embedded_subtitle_tracks: list[dict] = []
        self._local_subtitle_tracks: list[dict] = []
        self._current_audio_id = -1
        self._current_subtitle_id = -1
        #: Basenames of every external subtitle attached for the current
        #: media — the only trace libVLC leaves of an add_slave spu is its
        #: file name, so classification matches on it (see _split_* below).
        self._external_sub_files: list[str] = []
        #: Ground-truth {spu_id -> full path} for every file attached via
        #: add_slave during this media. Populated from a before/after diff of
        #: the SPU list — the only race-proof way to bind an add_slave spu to
        #: the file that produced it (libVLC's SPU description on many builds
        #: is "Track N", not the file name).
        self._local_subtitle_map: dict[int, str] = {}

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
        #
        # Non-media files (Excel sheets, Markdown notes, Word documents) are
        # not queueable either. Folders stay allowed because the playlist model
        # scans them for media, but plain files must be recognised audio/video
        # before they are offered to the queue.
        subtitles: list[str] = []
        queueable: list[str] = []
        for path in cleaned:
            if is_subtitle_path(path):
                subtitles.append(path)
                continue
            candidate = Path(path).expanduser()
            if candidate.is_dir() or is_media_path(path):
                queueable.append(path)
                continue
            log.info("ignoring non-media file: %s", candidate.name or path)

        if subtitles and not queueable:
            self._attach_subtitles(subtitles)
            return
        if subtitles:
            # Mixed drop (a video and its sidecar): queue the media, and let
            # the sidecar be picked up by the normal auto-load on open.
            log.info("ignoring %d subtitle file(s) alongside media", len(subtitles))

        cleaned = queueable
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

    def current_media_path(self) -> str:
        """Public for the subtitle downloader, which saves beside this file.

        QML never sees it — the UI gets :attr:`currentFileStem` instead."""
        return self._current_path()

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
            # M3U fast O(1) resume for 15k lists - avoids scanning view.
            # Duck-typed: if the mode offers play_current, use it.
            fast = getattr(target, "play_current", None)
            if callable(fast):
                try:
                    if fast():
                        return
                except Exception:
                    log.debug("play_current fast path failed", exc_info=True)
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
            fast = getattr(target, "play_current", None)
            if callable(fast):
                try:
                    if fast():
                        return
                except Exception:
                    log.debug("play_current fast path failed in play()", exc_info=True)
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
            log.info("resuming %s at %d ms", path, resume_ms)
            self.resumePrompted.emit(path, resume_ms)

    @Slot(str)
    def startOver(self, path: str) -> None:  # noqa: N802 - QML-facing
        """Abandon a resume: forget the saved position and play from the top.

        Three steps, and the order is load-bearing. Cancelling the engine's
        pending resume seek has to come first: that seek is applied when the
        media reaches Playing, which may be *after* this call, so seeking to 0
        while one is still queued is undone a moment later and playback jumps
        back to exactly where the user asked to leave.

        The two bookkeeping steps are individually guarded so a failure in
        either still leaves the picture rewound — that is the part the user can
        see, and a stale entry in recent.json is not worth losing it over.
        """
        cancel = getattr(self._engine, "cancel_pending_resume", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                log.debug("could not cancel the pending resume seek", exc_info=True)
        try:
            self._library.clear_position(path)
        except Exception:
            log.debug("could not clear the saved position", exc_info=True)
        self._engine.seek(0)
        log.info("start over: %s", path)

    def _on_media_changed(self, mrl: str) -> None:
        path = _from_uri(mrl)
        self._library.note_opened(path)
        self._metadata.load(path)
        self._lyrics.load(path)
        self._equalizer.reapply()
        if self._video_adjust is not None:
            try:
                self._video_adjust.reapply()
            except Exception:
                log.debug("video adjust reapply failed", exc_info=True)
        self._subtitle_delay = 0
        self.subtitleDelayChanged.emit()
        # External files belong to the media they were attached to; a new
        # media starts with a clean list before its sidecar is auto-loaded.
        self._external_sub_files = []
        self._local_subtitle_map = {}
        self.mediaNameChanged.emit()
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
            if self._load_external_subtitle(path):
                log.info("loaded subtitle %s", Path(path).name)
            else:
                log.warning("could not load subtitle %s", Path(path).name)
        self._refresh_tracks()

    def _auto_load_subtitle(self, path: str) -> None:
        media = Path(path)
        for suffix in (".srt", ".ass", ".ssa", ".sub", ".vtt"):
            sidecar = media.with_suffix(suffix)
            if sidecar.exists():
                self._load_external_subtitle(str(sidecar))
                log.info("auto-loaded subtitle %s", sidecar.name)
                return

    def _load_external_subtitle(self, path: str) -> bool:
        """The one attach path for subtitle *files* — auto sidecar, user-picked,
        drag-and-drop and downloaded all arrive here (§4.1).

        After the slave is attached the SPU list is diffed before/after so the
        new spu id can be bound to *this* file — that mapping is what lets the
        Local subtitles section show the real file name (VLC's spu description
        for a slave is often just "Track N"). The diff is scheduled on a short
        timer because libVLC parses the file asynchronously; the new id shows
        up milliseconds after add_slave returns.
        """
        # Snapshot the SPU ids that already exist — anything new that appears
        # after add_slave is a strong candidate for being this file.
        # Always treat -1 (Disable) as already known, so a race where VLC
        # hasn't reported any spu yet never maps -1 to a file.
        try:
            before_ids = {tid for tid, _label in self._engine.subtitle_tracks()}
        except Exception:
            before_ids = set()
        before_ids.add(-1)

        ok = self._engine.add_subtitle_file(path)
        if not ok:
            return False

        name = Path(path).name
        if name not in self._external_sub_files:
            self._external_sub_files.append(name)

        # Poll a few times — libVLC may take a beat to register the slave, and
        # a single-shot at 150 ms is not always long enough on a busy machine.
        # Attempts are cheap (a getter call each) and stop the moment the id
        # is found. `path` is captured by value; the map is safe to mutate
        # from the GUI thread these callbacks land on.
        attempts = {"n": 0}

        def poll_for_slave_id() -> None:
            attempts["n"] += 1
            try:
                current = self._engine.subtitle_tracks()
            except Exception:
                current = []
            # Never consider -1 as a new local track — libVLC's Disable
            # pseudo-track. Without this, an empty before_ids (VLC not yet
            # parsed) would map -1 to the file.
            new_ids = [
                tid for tid, _label in current if tid != -1 and tid not in before_ids
            ]
            if new_ids:
                # If multiple ids appeared (rare — a second slave started at
                # the same time), take the lowest not already mapped.
                sub_map = getattr(self, "_local_subtitle_map", None)
                if sub_map is None:
                    sub_map = {}
                    self._local_subtitle_map = sub_map
                # Defensive: purge any stale -1 entry that may have been
                # created by the old race.
                sub_map.pop(-1, None)
                for tid in sorted(new_ids):
                    if tid != -1 and tid not in sub_map:
                        sub_map[tid] = path
                        break
                self._refresh_tracks()
                return
            if attempts["n"] < 8:  # up to ~1.2 s total
                QTimer.singleShot(150, poll_for_slave_id)
            else:
                # Give up: the name-based fallback in _refresh_tracks will
                # still place it under Local subtitles when the label carries
                # the file name; otherwise it stays under Subtitles rather
                # than misclassify the wrong track.
                self._refresh_tracks()

        QTimer.singleShot(150, poll_for_slave_id)
        return True

    # ---------------------------------------------------------------- tracks ---
    def _refresh_tracks(self) -> None:
        try:
            raw_audio = [
                {"id": tid, "label": label} for tid, label in self._engine.audio_tracks()
            ]
            raw_video = [
                {"id": tid, "label": label} for tid, label in self._engine.video_tracks()
            ]
            subs = [
                {"id": tid, "label": label} for tid, label in self._engine.subtitle_tracks()
            ]
            self._current_audio_id = self._engine.current_audio_track()
            self._current_subtitle_id = self._engine.current_subtitle_track()
        except Exception:
            raw_audio = []
            raw_video = []
            subs = []
            self._current_audio_id = -1
            self._current_subtitle_id = -1

        # Video tracks: filter out -1 Disable if present (though VLC typically
        # doesn't surface one for video)
        self._video_tracks = [t for t in raw_video if t["id"] != -1]

        # Audio: libVLC surfaces a synthetic (-1, "Disable") row at the top of
        # every audio_get_track_description(). Mute already covers turning
        # audio off (§P1.4), so exposing a second control for the same thing
        # is redundant — and, worse, its id (-1) is what the engine also
        # returns for "no selection yet", which is the reason the popover
        # highlighted Disable while a real track was playing.
        self._audio_tracks = [t for t in raw_audio if t["id"] != -1]

        # If the engine has not settled on a real selection yet, treat the
        # first real track as current so the popover paints its highlight on
        # what is actually coming out of the speakers.
        if self._current_audio_id == -1 and self._audio_tracks:
            self._current_audio_id = self._audio_tracks[0]["id"]

        self._subtitle_tracks = subs

        # Local vs embedded classification. The authoritative source is the
        # {spu_id -> file_path} map populated at add_slave time — id-matching
        # is race-proof against VLC labels being "Track N" instead of the
        # file name. Anything not in the map falls back to the file-name
        # matcher for tests and for old sessions without a map entry.
        local_map = getattr(self, "_local_subtitle_map", {}) or {}
        # Defensive: if an old race left -1 in the map, drop it now.
        if -1 in local_map:
            local_map = {k: v for k, v in local_map.items() if k != -1}
            self._local_subtitle_map = local_map
        embedded: list[dict] = []
        local: list[dict] = []
        for track in subs:
            if track["id"] in local_map:
                # Replace VLC's generic label with the real file name — that
                # is the whole point of the Local subtitles section.
                local.append({
                    "id": track["id"],
                    "label": Path(local_map[track["id"]]).name,
                })
            else:
                embedded.append(track)
        # Fallback: names in _external_sub_files that never got mapped to an
        # id (e.g. a sidecar added before the map existed) still route via the
        # cosmetic-key matcher.
        if getattr(self, "_external_sub_files", None):
            extra_embedded, extra_local = _split_subtitle_tracks(
                embedded, self._external_sub_files
            )
            embedded = extra_embedded
            local = local + extra_local
        self._embedded_subtitle_tracks = embedded
        self._local_subtitle_tracks = local

        # Availability hint for the CC button badge. The badge promises
        # "something here you could switch on", so it is true only when the
        # media is video, at least one real subtitle exists (embedded or
        # loaded from disk — VLC's -1 "Disable" pseudo-track never counts),
        # AND none is currently active. The moment the user turns subtitles
        # on, currentSubtitleId leaves -1 and the badge disappears.
        real_subs = [
            t for t in (embedded + local) if t["id"] != -1
        ]
        self._subtitles_available = (
            len(self._video_tracks) > 0
            and bool(real_subs)
            and self._current_subtitle_id == -1
        )

        self.tracksChanged.emit()

    @Property("QVariantList", notify=tracksChanged)
    def audioTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._audio_tracks

    @Property("QVariantList", notify=tracksChanged)
    def videoTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._video_tracks

    @Property("QVariantList", notify=tracksChanged)
    def subtitleTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._subtitle_tracks

    @Property("QVariantList", notify=tracksChanged)
    def embeddedSubtitleTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._embedded_subtitle_tracks

    @Property("QVariantList", notify=tracksChanged)
    def localSubtitleTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._local_subtitle_tracks

    @Property(int, notify=tracksChanged)
    def currentAudioId(self) -> int:  # noqa: N802 - QML-facing
        return self._current_audio_id

    @Property(int, notify=tracksChanged)
    def currentSubtitleId(self) -> int:  # noqa: N802 - QML-facing
        return self._current_subtitle_id

    @Property(bool, notify=tracksChanged)
    def hasVideo(self) -> bool:  # noqa: N802 - QML-facing
        """True if the current media has at least one video track."""
        return len(self._video_tracks) > 0

    @Property(bool, notify=tracksChanged)
    def subtitlesAvailable(self) -> bool:  # noqa: N802 - QML-facing
        """True when the current video has subtitles the user could switch on.

        Drives the CC button's availability badge. It re-evaluates on every
        ``tracksChanged`` — the same signal the popover reads — so the badge
        follows reality the instant tracks arrive asynchronously or the user
        toggles a subtitle on or off.
        """
        return self._subtitles_available

    @Property(str, notify=mediaNameChanged)
    def currentFileStem(self) -> str:  # noqa: N802 - QML-facing
        """File name of the playing media without extension — the subtitle
        download flyout's default search text and save-name base."""
        path = self._current_path()
        return Path(path).stem if path else ""

    @Slot(int)
    def setAudioTrack(self, track_id: int) -> None:  # noqa: N802 - QML-facing
        self._engine.set_audio_track(track_id)
        # Refresh so the popover's "current" marker follows the click now,
        # not whenever the next external event happens to rebuild the lists.
        self._refresh_tracks()

    @Slot(int)
    def setSubtitleTrack(self, track_id: int) -> None:  # noqa: N802 - QML-facing
        self._engine.set_subtitle_track(track_id)
        self._refresh_tracks()

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
        self._load_external_subtitle(_normalise(url))
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


def _name_key(text: str) -> str:
    """Punctuation-insensitive comparison key for a track label or file name.

    ``"Movie.2024.1080p-[GRP].srt"`` and ``"movie 2024 1080p grp"`` must land
    on the same key whichever cosmetic form VLC picked for the spu description.
    """
    lowered = text.lower()
    for ch in "._-[](){},":
        lowered = lowered.replace(ch, " ")
    return " ".join(lowered.split())


def _split_subtitle_tracks(
    tracks: list[dict], external_files: list[str]
) -> tuple[list[dict], list[dict]]:
    """Partition *(embedded, local)* subtitle tracks by file name.

    libVLC exposes no "this spu came from ``add_slave``" flag; the only trace an
    external file leaves in the spu list is its file name in the description.
    Matching by name (instead of by add order) is immune to VLC reporting the
    tracks in several bursts while a media parses — a race an id-diff would
    lose. An empty external list means everything is embedded, which is the
    whole answer for media with no sidecar at all.
    """
    keys = set()
    for file_name in external_files:
        keys.add(_name_key(file_name))
        keys.add(_name_key(Path(file_name).stem))
    keys.discard("")

    embedded: list[dict] = []
    local: list[dict] = []
    for track in tracks:
        label_key = _name_key(track["label"])
        # id -1 is libVLC's "Disable" pseudo-track, not a spu — never let a
        # file literally named "disable.srt" drag it into the local list.
        is_local = (
            track["id"] != -1
            and bool(label_key)
            and any(key in label_key or label_key in key for key in keys)
        )
        (local if is_local else embedded).append(track)
    return embedded, local


def _normalise(raw) -> str:
    """One URL->path implementation, shared with the playlist model (§4.1)."""
    return paths.normalise_path(raw)


def _from_uri(mrl: str) -> str:
    return _normalise(mrl)
