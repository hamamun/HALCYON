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

from core import media_types
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
        self._current_audio = -1
        self._current_subtitle = -1
        self._resume_path = ""
        self._audio_restored = False
        self._subtitle_restored = False

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
        """Open a file, resuming where it was left off if that applies.

        The file is opened **at** the resume point rather than from zero, so
        there is no jarring restart-then-jump. The prompt that follows is
        therefore an *undo* — "Start over" — not a question the user has to
        answer before playback can begin. Ignoring it does the right thing,
        which is the point: a modal you must dismiss before your film starts is
        worse than no resume at all.

        Resume is video-only and honours the Settings toggle; both of those
        decisions live in ``Library.resume_position``, once.
        """
        resume_ms = 0
        if self._settings.get("playback.resumeEnabled", True):
            resume_ms = self._library.resume_position(path)
        self._resume_path = path
        self._audio_restored = False
        self._subtitle_restored = False
        self._engine.open(path, resume_ms)
        if resume_ms:
            self.resumePrompted.emit(path, int(resume_ms))

    @Slot()
    def startOver(self) -> None:  # noqa: N802 - QML-facing
        """Discard the saved position and play from the beginning.

        Clears the stored position too — otherwise the next open would offer to
        resume to the point the user just explicitly rejected.
        """
        if self._resume_path:
            self._library.clear_position(self._resume_path)
        self._engine.seek(0)

    def _on_media_changed(self, mrl: str) -> None:
        path = _from_uri(mrl)
        # The engine is the authority on what is playing. `openPath` sets these
        # too, but media can also change without it (the queue advancing at
        # end-of-file), and a stale `_resume_path` would file the next film's
        # track choice against the previous one.
        self._resume_path = path
        self._audio_restored = False
        self._subtitle_restored = False
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
        """Republish the track lists *and* which entry of each is live.

        The lists carry an ``off`` flag rather than the UI matching on the
        label. libVLC calls the no-track row "Disable", localises it, and gives
        it id ``-1``; a QML string comparison against "Disable" is therefore
        both fragile and untranslatable, and it was why the off row could not be
        told apart from a real track.
        """
        try:
            self._audio_tracks = _track_dicts(self._engine.audio_tracks())
            self._subtitle_tracks = _track_dicts(
                self._engine.subtitle_tracks(), off_label="Off"
            )
        except Exception:
            self._audio_tracks = []
            self._subtitle_tracks = []
        self._restore_remembered_tracks()
        self._auto_select_default_audio()
        self._refresh_current_tracks(emit=False)
        self.tracksChanged.emit()

    def _auto_select_default_audio(self) -> None:
        """Auto-select the first audio track if none is currently selected.

        When a video with multiple audio tracks loads, libVLC sometimes defaults
        to track -1 (disabled), leaving the user with no audio. This ensures
        that if no audio track is selected and real tracks exist, the first one
        is automatically selected.
        """
        if not self._audio_tracks:
            return
        
        # Check if a real audio track is currently selected
        try:
            current = int(self._engine.current_audio_track())
        except Exception:
            current = -1
        
        # If disabled (-1) and we have real tracks, select the first one
        if current == -1:
            real_tracks = [t for t in self._audio_tracks if not t.get("off")]
            if real_tracks:
                first_track_id = int(real_tracks[0]["id"])
                try:
                    self._engine.set_audio_track(first_track_id)
                    log.info("auto-selected first audio track: %s", real_tracks[0].get("label"))
                except Exception:
                    log.debug("could not auto-select audio track", exc_info=True)

    def _restore_remembered_tracks(self) -> None:
        """Re-select the track this file was last watched with.

        Runs off the track refresh rather than off media-open because the track
        list does not exist yet when the file opens — libVLC discovers the
        elementary streams asynchronously, which is exactly why ESAdded exists.

        **The latch is per kind, and that is load-bearing.** libVLC discovers
        elementary streams incrementally, so a typical file raises ESAdded for
        its audio track first and its subtitle tracks a moment later. A single
        shared latch closed on the audio pass and the remembered *subtitle* was
        then never restored — silently, and only for real files, which is why
        a test that populated both lists at once did not catch it.

        Each kind latches when its own list first appears, so each gets exactly
        one attempt: late-arriving subtitles are still restored, and a later
        ESAdded (an external .srt being attached, say) cannot yank an
        in-session choice back to the remembered one.
        """
        if not self._resume_path:
            return

        if self._audio_tracks and not self._audio_restored:
            self._audio_restored = True
            wanted = self._library.remembered_audio_track(self._resume_path)
            if wanted:
                self._select_by_label(
                    self._audio_tracks, wanted, self._engine.set_audio_track, "audio"
                )

        if self._subtitle_tracks and not self._subtitle_restored:
            self._subtitle_restored = True
            wanted = self._library.remembered_subtitle_track(self._resume_path)
            if wanted:
                self._select_by_label(
                    self._subtitle_tracks,
                    wanted,
                    self._engine.set_subtitle_track,
                    "subtitle",
                )

    @staticmethod
    def _select_by_label(tracks: list[dict], label: str, setter, kind: str) -> None:
        """Match on the label, because libVLC's ids are not stable.

        A numeric id is assigned per demuxer run: id 2 might be Japanese today
        and the director's commentary tomorrow, so restoring by id would
        silently play the wrong thing. A label either matches or it does not,
        and a miss just leaves libVLC's own default in place.
        """
        for track in tracks:
            if str(track.get("label", "")) == label:
                try:
                    setter(int(track["id"]))
                except Exception:
                    log.debug("could not restore %s track %r", kind, label, exc_info=True)
                else:
                    log.info("restored %s track %r", kind, label)
                return
        log.info("remembered %s track %r is not in this file", kind, label)

    def _refresh_current_tracks(self, emit: bool = True) -> None:
        try:
            audio = int(self._engine.current_audio_track())
        except Exception:
            audio = -1
        try:
            subtitle = int(self._engine.current_subtitle_track())
        except Exception:
            subtitle = -1
        changed = (audio, subtitle) != (self._current_audio, self._current_subtitle)
        self._current_audio, self._current_subtitle = audio, subtitle
        if changed and emit:
            self.tracksChanged.emit()

    @Property("QVariantList", notify=tracksChanged)
    def audioTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._audio_tracks

    @Property("QVariantList", notify=tracksChanged)
    def subtitleTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._subtitle_tracks

    @Property(int, notify=tracksChanged)
    def currentAudioId(self) -> int:  # noqa: N802 - QML-facing
        return self._current_audio

    @Property(int, notify=tracksChanged)
    def currentSubtitleId(self) -> int:  # noqa: N802 - QML-facing
        return self._current_subtitle

    @Slot(int)
    def setAudioTrack(self, track_id: int) -> None:  # noqa: N802 - QML-facing
        self._engine.set_audio_track(track_id)
        self._refresh_current_tracks()
        self._remember_choice(self._audio_tracks, track_id, "audio")

    @Slot(int)
    def setSubtitleTrack(self, track_id: int) -> None:  # noqa: N802 - QML-facing
        self._engine.set_subtitle_track(track_id)
        self._refresh_current_tracks()
        self._remember_choice(self._subtitle_tracks, track_id, "subtitle")

    def _remember_choice(self, tracks: list[dict], track_id: int, kind: str) -> None:
        """File the user's pick against this media, by label.

        Only an *explicit* selection is remembered — this is called from the
        setters and the cycle hotkeys, never from ``_restore_remembered_tracks``,
        so restoring a choice cannot be mistaken for making one.
        """
        if not self._resume_path:
            return
        label = next(
            (str(t.get("label", "")) for t in tracks if int(t["id"]) == int(track_id)), ""
        )
        if kind == "audio":
            self._library.remember_audio_track(self._resume_path, label)
        else:
            self._library.remember_subtitle_track(self._resume_path, label)

    @Slot()
    def cycleAudioTrack(self) -> None:  # noqa: N802 - QML-facing
        self._cycle(self._audio_tracks, self._current_audio, self._engine.set_audio_track)
        self._refresh_current_tracks()
        # `A` is as explicit a choice as clicking the row, so it is remembered
        # the same way — one behaviour, two triggers (§4.1).
        self._remember_choice(self._audio_tracks, self._current_audio, "audio")

    @Slot()
    def cycleSubtitleTrack(self) -> None:  # noqa: N802 - QML-facing
        self._cycle(
            self._subtitle_tracks, self._current_subtitle, self._engine.set_subtitle_track
        )
        self._refresh_current_tracks()
        self._remember_choice(self._subtitle_tracks, self._current_subtitle, "subtitle")

    @staticmethod
    def _cycle(tracks: list[dict], current_id: int, setter) -> None:
        """Advance to the next track, wrapping.

        It used to always select ``tracks[0]`` — so `A` and `S` selected the
        same track forever and "cycle" was a misnomer. Cycling from wherever the
        player actually is makes the hotkey and the popover agree, which is the
        point of them sharing one implementation.
        """
        if not tracks:
            return
        ids = [int(t["id"]) for t in tracks]
        try:
            index = ids.index(int(current_id))
        except ValueError:
            index = -1
        setter(ids[(index + 1) % len(ids)])

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


#: libVLC's id for "no track". Both audio and SPU use it.
TRACK_OFF_ID = -1


def _track_dicts(pairs, off_label: str = "Off") -> list[dict]:
    """``[(id, label)]`` -> ``[{id, label, off}]``.

    The off row is identified by its **id**, never its text, and is always
    hoisted to the front so the UI can pin it above a scrolling list without
    searching for it.
    """
    tracks = [
        {
            "id": int(tid),
            "label": (off_label if int(tid) == TRACK_OFF_ID else str(label)),
            "off": int(tid) == TRACK_OFF_ID,
        }
        for tid, label in pairs
    ]
    tracks.sort(key=lambda t: 0 if t["off"] else 1)
    return tracks


#: One shared answer, in ``core.media_types``. This used to reach into
#: ``modes.local.playlist`` — lazily, to soften it, but the chassis still
#: depended on a mode and the isolation guard reported it (§A.3, rule 2). The
#: dependency was backwards: ".srt is a subtitle" is a fact about media, not
#: about Local's queue, and M3U and Web need the same answer.
_is_subtitle = media_types.is_subtitle


def _normalise(raw) -> str:
    """One URL->path implementation, shared with the playlist model (§4.1)."""
    return paths.normalise_path(raw)


def _from_uri(mrl: str) -> str:
    return _normalise(mrl)
