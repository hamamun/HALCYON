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
        found = mode_registry.find(mode_id)
        return self._as_dict(found) if found else None

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
    def addPaths(self, paths: list) -> None:  # noqa: N802 - QML-facing
        """The one append path — Add Files, Add Folder, Ctrl+O and drag-and-drop
        all arrive here (§4.1)."""
        target = self.playlist
        if target is None or not hasattr(target, "add_paths"):
            return
        cleaned = [_normalise(p) for p in paths]
        added = target.add_paths(cleaned)
        if added and target.current_index() < 0:
            target.play_index(0)

    @Slot(list)
    def clearSelected(self, rows: list) -> None:  # noqa: N802 - QML-facing
        target = self.playlist
        if target is not None and hasattr(target, "remove_rows"):
            target.remove_rows([int(r) for r in rows])

    @Slot()
    def clearPlaylist(self) -> None:  # noqa: N802 - QML-facing
        target = self.playlist
        if target is not None and hasattr(target, "clear"):
            target.clear()

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
            target.play_next()

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
        self._library.shutdown()
        self._equalizer.release()
        self._settings.flush()


def _normalise(raw) -> str:
    text = str(raw)
    if text.startswith("file://"):
        from urllib.parse import unquote, urlparse

        parsed = urlparse(text)
        path = unquote(parsed.path)
        # Windows: file:///C:/x -> /C:/x, strip the leading slash
        if len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path
    return text


def _from_uri(mrl: str) -> str:
    return _normalise(mrl)
