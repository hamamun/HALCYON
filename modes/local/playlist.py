"""Local mode's queue — Milestone 1.5.

A ``QAbstractListModel`` so QML gets change notifications for free, with
reorder, multi-select and repeat/shuffle-aware next/prev.

**Isolation (§A.1):** this is Local's queue and nothing else's. M3U keeps its own
channel list in ``modes/m3u/``; the two never mix, and deleting either directory
leaves the other perfect.

Duration probing runs on a worker thread — a folder of 500 files must never
block the UI while it works out how long each one is (§P1.5).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)

from core import paths as path_utils

log = logging.getLogger(__name__)

#: Extensions Add Folder will pick up (§P1.5). Deliberately generous — libVLC
#: plays far more than this, but a recursive scan should not hoover up .txt.
VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts", ".m2ts", ".mts", ".flv",
    ".webm", ".mpg", ".mpeg", ".m4v", ".3gp", ".ogv", ".vob", ".divx", ".rmvb",
}
AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".aac", ".opus", ".ogg", ".wav", ".m4a", ".wma", ".alac",
    ".ape", ".aiff", ".dsf", ".mka", ".mpc",
}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

#: Sidecar subtitle formats. These are **not** media and must never enter the
#: queue: libVLC will happily "open" a .srt as a media item, produce a track
#: with no video and no audio, tear the video pipeline down and leave the UI
#: showing a track that can never play. Dropping one is a request to subtitle
#: the *current* video — core.app routes them there instead (§P1.5).
SUBTITLE_EXTENSIONS = {
    ".srt", ".ass", ".ssa", ".sub", ".vtt", ".idx", ".sup", ".smi", ".txt",
}


class RepeatMode(IntEnum):
    Off = 0
    One = 1
    All = 2


@dataclass
class Track:
    path: str
    title: str
    duration_ms: int = 0
    probed: bool = False

    @property
    def is_audio(self) -> bool:
        return Path(self.path).suffix.lower() in AUDIO_EXTENSIONS


class _ProbeSignals(QObject):
    """Carries probe results back to the GUI thread.

    Parented to the model so its lifetime is Qt's business, and carrying a
    ``cancelled`` flag so in-flight probes stop talking to it once the model is
    going away.
    """

    done = Signal(str, int)  # path, duration_ms

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cancelled = False


class _ProbeTask(QRunnable):
    """Ask libVLC how long a file is, off the UI thread."""

    def __init__(self, path: str, signals: _ProbeSignals) -> None:
        super().__init__()
        self._path = path
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        """Probe one file. **Must never raise.**

        This is a ``QRunnable`` override, so an escaping exception surfaces as
        Qt's "Error calling Python override of QRunnable::run()" on a pool
        thread with no useful traceback. The whole body is therefore wrapped:
        during interpreter shutdown even ``import vlc`` or ``log.debug`` can
        fail, and a probe result is never worth taking the process down for.
        """
        try:
            self._probe()
        except BaseException:  # noqa: BLE001 - a pool thread must not propagate
            pass

    def _probe(self) -> None:
        # Bail before doing any work if the queue was cleared or the app is
        # quitting — a folder of 500 files leaves a lot of these queued.
        if self._signals.cancelled:
            return
        duration = 0
        instance = media = None
        try:
            import vlc

            instance = vlc.Instance(["--quiet", "--no-video", "--intf=dummy"])
            if instance is not None:
                media = instance.media_new_path(self._path)
                if media is not None:
                    media.parse_with_options(vlc.MediaParseFlag.local, 2000)
                    duration = max(0, int(media.get_duration()))
        except Exception:
            log.debug("probe failed for %s", self._path, exc_info=True)
        finally:
            # Release in reverse order of creation, and never let a failed
            # release strand the other handle.
            for obj in (media, instance):
                if obj is not None:
                    try:
                        obj.release()
                    except Exception:
                        pass

        # Re-check: the model may have been torn down during the parse above,
        # and emitting into a deleted QObject raises out of a pool thread.
        if self._signals.cancelled:
            return
        try:
            self._signals.done.emit(self._path, duration)
        except RuntimeError:
            pass  # receiver already gone; nothing to report to


class PlaylistModel(QAbstractListModel):
    """Local's queue."""

    PathRole = Qt.ItemDataRole.UserRole + 1
    TitleRole = Qt.ItemDataRole.UserRole + 2
    DurationRole = Qt.ItemDataRole.UserRole + 3
    IsCurrentRole = Qt.ItemDataRole.UserRole + 4
    IsAudioRole = Qt.ItemDataRole.UserRole + 5

    currentIndexChanged = Signal(int)
    countChanged = Signal()
    repeatModeChanged = Signal()
    shuffleChanged = Signal()
    playRequested = Signal(str, int)  # path, index

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tracks: list[Track] = []
        self._current = -1
        self._repeat = RepeatMode.Off
        self._shuffle = False
        self._shuffle_order: list[int] = []
        self._pool = QThreadPool.globalInstance()
        self._probe_signals = _ProbeSignals(self)
        self._probe_signals.done.connect(self._on_probed)

    # ------------------------------------------------------ model plumbing ---
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._tracks)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._tracks)):
            return None
        track = self._tracks[index.row()]
        if role in (self.TitleRole, Qt.ItemDataRole.DisplayRole):
            return track.title
        if role == self.PathRole:
            return track.path
        if role == self.DurationRole:
            return track.duration_ms
        if role == self.IsCurrentRole:
            return index.row() == self._current
        if role == self.IsAudioRole:
            return track.is_audio
        return None

    def roleNames(self) -> dict:  # noqa: N802 - Qt override
        return {
            self.PathRole: QByteArray(b"path"),
            self.TitleRole: QByteArray(b"title"),
            self.DurationRole: QByteArray(b"duration"),
            self.IsCurrentRole: QByteArray(b"isCurrent"),
            self.IsAudioRole: QByteArray(b"isAudio"),
        }

    # -------------------------------------------------------------- adding ---
    @Slot(list)
    def add_paths(self, paths: list[str]) -> int:
        """The single append implementation (§4.1).

        Add Files, Add Folder, ``Ctrl+O`` and Explorer drag-and-drop all end up
        here. There is no second path that adds to the queue.
        """
        incoming: list[Track] = []
        for raw in paths or []:
            # Shared normaliser: percent-decoding and the Windows drive-letter
            # fix live in exactly one place (core.paths). The old
            # `.replace("file://", "")` left "/E:/drvie%20personal/..." behind,
            # which is not a file anywhere, so the item was dropped in silence.
            text = path_utils.normalise_path(raw)
            if not text:
                continue
            p = Path(text).expanduser()
            if p.is_dir():
                incoming.extend(self._scan_folder(p))
            elif p.is_file():
                suffix = p.suffix.lower()
                if suffix in SUBTITLE_EXTENSIONS:
                    # Not media. The caller (core.app.addPaths) has already had
                    # the chance to attach it to the playing video; reaching
                    # here means it could not, so drop it rather than queue an
                    # unplayable row.
                    log.info("ignoring subtitle file in queue: %s", p.name)
                elif suffix in MEDIA_EXTENSIONS:
                    incoming.append(Track(str(p), p.stem))
                else:
                    # The queue is the last line of defence: drag-and-drop and
                    # Add Files may hand us a real file that is not playable
                    # media (Excel, Markdown, Word). Ignore it rather than
                    # queueing a dead row.
                    log.info("ignoring non-media file in queue: %s", p.name)
            else:
                log.warning("skipped, not found on disk: %s", text)

        if not incoming:
            log.info("add_paths: nothing to add from %d input(s)", len(paths or []))
            return 0

        start = len(self._tracks)
        self.beginInsertRows(QModelIndex(), start, start + len(incoming) - 1)
        self._tracks.extend(incoming)
        self.endInsertRows()
        self.countChanged.emit()
        self._rebuild_shuffle()
        for track in incoming:
            self._pool.start(_ProbeTask(track.path, self._probe_signals))
        return len(incoming)

    def _scan_folder(self, folder: Path) -> list[Track]:
        """Recursive, media extensions only (§P1.5)."""
        found: list[Track] = []
        try:
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                    found.append(Track(str(path), path.stem))
        except OSError:
            log.warning("could not scan %s", folder)
        return found

    def _on_probed(self, path: str, duration_ms: int) -> None:
        for row, track in enumerate(self._tracks):
            if track.path == path and not track.probed:
                track.duration_ms = duration_ms
                track.probed = True
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [self.DurationRole])
                break

    # ------------------------------------------------------------ removing ---
    @Slot(list, result=bool)
    def remove_rows(self, rows: list[int]) -> bool:
        """Clear Selected. The Delete key routes to the same Actions entry that
        the toolbar button does, so this has exactly one caller path.

        Returns True if the currently playing track was among the removed rows.
        """
        playing_removed = False
        playing_row = self._current
        wanted = sorted({int(r) for r in rows}, reverse=True)
        for row in wanted:
            if 0 <= row < len(self._tracks):
                if row == playing_row:
                    playing_removed = True
                self.beginRemoveRows(QModelIndex(), row, row)
                self._tracks.pop(row)
                self.endRemoveRows()
                if row < self._current:
                    self._set_current(self._current - 1)

        if playing_removed:
            self._set_current(-1)

        self.countChanged.emit()
        self._rebuild_shuffle()
        return playing_removed

    @Slot()
    def clear(self) -> None:
        self.beginResetModel()
        self._tracks.clear()
        self._current = -1
        self.endResetModel()
        self.countChanged.emit()
        self.currentIndexChanged.emit(-1)
        self._rebuild_shuffle()

    @Slot(int, int)
    def move_row(self, source: int, target: int) -> None:
        """Drag-to-reorder."""
        n = len(self._tracks)
        if not (0 <= source < n) or not (0 <= target < n) or source == target:
            return
        self.beginMoveRows(
            QModelIndex(), source, source, QModelIndex(),
            target + 1 if target > source else target,
        )
        track = self._tracks.pop(source)
        self._tracks.insert(target, track)
        self.endMoveRows()
        if self._current == source:
            self._set_current(target)
        elif source < self._current <= target:
            self._set_current(self._current - 1)
        elif target <= self._current < source:
            self._set_current(self._current + 1)

    # ----------------------------------------------------------- playback ---
    @Slot(int)
    def play_index(self, row: int) -> None:
        if 0 <= row < len(self._tracks):
            self._set_current(row)
            self.playRequested.emit(self._tracks[row].path, row)

    @Slot(result=bool)
    def play_next(self) -> bool:
        nxt = self.next_index()
        if nxt < 0:
            return False
        self.play_index(nxt)
        return True

    @Slot(result=bool)
    def play_previous(self) -> bool:
        prev = self.previous_index()
        if prev < 0:
            return False
        self.play_index(prev)
        return True

    def next_index(self) -> int:
        """Repeat and shuffle are honoured here, in one place, so every caller
        (Next button, track-ended, hotkey) behaves identically."""
        n = len(self._tracks)
        if n == 0:
            return -1
        if self._repeat == RepeatMode.One and self._current >= 0:
            return self._current
        if self._shuffle:
            return self._shuffle_next()
        if self._current + 1 < n:
            return self._current + 1
        return 0 if self._repeat == RepeatMode.All else -1

    def previous_index(self) -> int:
        n = len(self._tracks)
        if n == 0:
            return -1
        if self._repeat == RepeatMode.One and self._current >= 0:
            return self._current
        if self._shuffle:
            return self._shuffle_previous()
        if self._current > 0:
            return self._current - 1
        return n - 1 if self._repeat == RepeatMode.All else -1

    def _shuffle_next(self) -> int:
        if not self._shuffle_order or len(self._shuffle_order) != len(self._tracks):
            self._rebuild_shuffle()
        if not self._shuffle_order:
            return -1
        try:
            pos = self._shuffle_order.index(self._current)
        except ValueError:
            pos = -1
        if pos + 1 < len(self._shuffle_order):
            return self._shuffle_order[pos + 1]
        if self._repeat == RepeatMode.All:
            self._rebuild_shuffle(avoid_first=self._current)
            return self._shuffle_order[0] if self._shuffle_order else -1
        return -1

    def _shuffle_previous(self) -> int:
        if not self._shuffle_order or len(self._shuffle_order) != len(self._tracks):
            self._rebuild_shuffle()
        if not self._shuffle_order:
            return -1
        try:
            pos = self._shuffle_order.index(self._current)
        except ValueError:
            pos = -1
        if pos > 0:
            return self._shuffle_order[pos - 1]
        if self._repeat == RepeatMode.All:
            return self._shuffle_order[-1]
        return -1

    def _rebuild_shuffle(self, avoid_first: int = -1) -> None:
        n = len(self._tracks)
        if n == 0:
            self._shuffle_order = []
            return

        order = list(range(n))
        random.shuffle(order)

        if avoid_first >= 0 and avoid_first in order and n > 1:
            if order[0] == avoid_first:
                swap_idx = random.randint(1, n - 1)
                order[0], order[swap_idx] = order[swap_idx], order[0]
        elif 0 <= self._current < n and self._current in order:
            order.remove(self._current)
            order.insert(0, self._current)

        self._shuffle_order = order

    def _set_current(self, row: int) -> None:
        if row == self._current:
            return
        previous = self._current
        self._current = row
        for changed in (previous, row):
            if 0 <= changed < len(self._tracks):
                idx = self.index(changed, 0)
                self.dataChanged.emit(idx, idx, [self.IsCurrentRole])
        self.currentIndexChanged.emit(row)

    @Slot(str)
    def set_current_by_path(self, path: str) -> None:
        for row, track in enumerate(self._tracks):
            if track.path == path:
                self._set_current(row)
                return

    # --------------------------------------------------------- properties ---
    # These are Properties, not Slots, and that distinction is the whole reason
    # the panel updates. A `@Slot(result=int) def count()` is callable from QML
    # as `model.count()` — but a *call* is not a binding: QML has no idea the
    # answer ever changes, so `visible: model.count() > 0` is evaluated once, at
    # load, when the queue is empty, and never again. Files were being added to
    # the model correctly and the list stayed hidden behind the empty state.
    #
    # A Property with a notify signal makes the same expression a live binding.

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._tracks)

    @Property(int, notify=currentIndexChanged)
    def currentIndex(self) -> int:  # noqa: N802 - QML-facing
        return self._current

    @Property(int, notify=repeatModeChanged)
    def repeatMode(self) -> int:  # noqa: N802 - QML-facing
        return int(self._repeat)

    @Property(bool, notify=shuffleChanged)
    def shuffle(self) -> bool:
        return self._shuffle

    # Python-side accessors. The controller uses these; QML uses the properties
    # above. Same state, one storage location.
    def current_index(self) -> int:
        return self._current

    def repeat_mode(self) -> int:
        return int(self._repeat)

    def is_shuffled(self) -> bool:
        return self._shuffle

    @Slot(int, result=str)
    def path_at(self, row: int) -> str:
        return self._tracks[row].path if 0 <= row < len(self._tracks) else ""

    @Slot()
    def cycle_repeat(self) -> None:
        self._repeat = RepeatMode((int(self._repeat) + 1) % 3)
        self.repeatModeChanged.emit()

    @Slot(int)
    def set_repeat_mode(self, mode: int) -> None:
        self._repeat = RepeatMode(int(mode) % 3)
        self.repeatModeChanged.emit()

    @Slot()
    def toggle_shuffle(self) -> None:
        self._shuffle = not self._shuffle
        if self._shuffle:
            self._rebuild_shuffle()
        self.shuffleChanged.emit()

    # ---------------------------------------------------------- shutdown ---
    def shutdown(self) -> None:
        """Stop accepting probe results. Called before the app tears down."""
        self._probe_signals.cancelled = True

    def to_list(self) -> list[dict]:
        return [
            {"path": t.path, "title": t.title, "duration": t.duration_ms}
            for t in self._tracks
        ]

    def restore(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._tracks = [
            Track(i["path"], i.get("title", Path(i["path"]).stem), i.get("duration", 0), True)
            for i in items
            if i.get("path")
        ]
        self._current = -1
        self.endResetModel()
        self.countChanged.emit()
        self._rebuild_shuffle()
