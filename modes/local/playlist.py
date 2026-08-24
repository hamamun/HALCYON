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

import json
import logging
import os
import random
import tempfile
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QSortFilterProxyModel,
    QByteArray,
    QModelIndex,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)

from core import paths as path_utils
from core.media_types import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS, SUBTITLE_EXTENSIONS

log = logging.getLogger(__name__)

LOCAL_PLAYLIST_FILENAME = "local-playlist.json"
PLAYLIST_FORMAT_VERSION = 1
SAVE_DEBOUNCE_MS = 400


class RepeatMode(IntEnum):
    Off = 0
    One = 1
    All = 2


class LocalPlaylistFilterModel(QSortFilterProxyModel):
    """The Local queue's filtered view.

    The source model remains the authoritative playlist: playback, selection,
    persistence, and Actions all continue to use source rows. This proxy only
    changes what the panel displays, which means filtering can never make a
    double-click target the wrong media item.
    """

    SourceIndexRole = Qt.ItemDataRole.UserRole + 6
    countChanged = Signal()
    currentIndexChanged = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._filter_text = ""
        self._current_index = -1
        self.setDynamicSortFilter(True)

    def roleNames(self) -> dict:  # noqa: N802 - Qt override
        roles = dict(super().roleNames())
        roles[self.SourceIndexRole] = QByteArray(b"sourceIndex")
        return roles

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if role == self.SourceIndexRole:
            if not index.isValid():
                return -1
            source_index = self.mapToSource(index)
            return source_index.row() if source_index.isValid() else -1
        return super().data(index, role)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        if not self._filter_text:
            return True
        source = self.sourceModel()
        if source is None:
            return False
        index = source.index(source_row, 0, source_parent)
        title = str(source.data(index, Qt.ItemDataRole.DisplayRole) or "")
        path = str(source.data(index, Qt.ItemDataRole.UserRole + 1) or "")
        return self._filter_text in f"{title}\n{path}".casefold()

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return self.rowCount()

    @Property(int, notify=currentIndexChanged)
    def currentIndex(self) -> int:  # noqa: N802 - QML-facing
        return self._current_index

    @Slot(str)
    def setFilter(self, text: str) -> None:  # noqa: N802 - QML-facing
        value = str(text or "").casefold()
        if value == self._filter_text:
            return
        self._filter_text = value
        self.invalidateFilter()
        self._publish_current_index()

    @Slot(int, result=int)
    def sourceRowAt(self, view_row: int) -> int:  # noqa: N802 - QML-facing
        if not (0 <= int(view_row) < self.rowCount()):
            return -1
        index = self.mapToSource(self.index(int(view_row), 0))
        return index.row() if index.isValid() else -1

    @Slot(int)
    def sourceCurrentIndexChanged(self, source_row: int) -> None:  # noqa: N802
        self._publish_current_index(int(source_row))

    @Slot()
    def _on_rows_changed(self) -> None:
        self.countChanged.emit()
        self._publish_current_index()

    def _publish_current_index(self, source_row: int | None = None) -> None:
        if source_row is None:
            source = self.sourceModel()
            source_row = int(source.currentIndex) if source is not None else -1
        mapped = QModelIndex()
        source = self.sourceModel()
        if source is not None and source_row >= 0:
            mapped = self.mapFromSource(source.index(source_row, 0))
        current = mapped.row() if mapped.isValid() else -1
        if current != self._current_index:
            self._current_index = current
            self.currentIndexChanged.emit(current)


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
        try:
            if not self._signals.cancelled:
                self._signals.done.emit(self._path, duration)
        except (RuntimeError, Exception):
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

    def __init__(
        self,
        parent: QObject | None = None,
        storage_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._tracks: list[Track] = []
        self._current = -1
        self._repeat = RepeatMode.Off
        self._shuffle = False
        self._shuffle_order: list[int] = []
        self._storage_path = Path(storage_path) if storage_path is not None else None
        self._save_dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.save)
        # A pool of our own, not QThreadPool.globalInstance(). The global pool
        # is shared with the rest of Qt and cannot be drained without stalling
        # unrelated work, so shutdown() had no way to guarantee that every
        # in-flight probe had finished. A probe still running inside
        # `self._probe_signals.done.emit(...)` while Python collected the
        # signals QObject tore the process down with a segfault (§9) — the
        # `cancelled` flag alone loses the race, because it can flip *after*
        # the emit has already started. Owning the pool lets shutdown() wait.
        self._pool = QThreadPool(self)
        self._probe_signals = _ProbeSignals()
        self._probe_signals.done.connect(self._on_probed)
        self._shut_down = False

        # The Local queue is session-persistent, just like M3U remembers its
        # last saved source. Loading only rebuilds the list and current marker;
        # it deliberately never emits playRequested, so startup stays silent.
        self._load_saved_playlist()

        # The panel binds to this proxy, while all Actions continue to address
        # the complete source playlist. Source rows are therefore stable even
        # while the user types into the filter.
        self._filtered_model = LocalPlaylistFilterModel(self)
        self._filtered_model.setSourceModel(self)
        self.currentIndexChanged.connect(
            self._filtered_model.sourceCurrentIndexChanged
        )
        self.countChanged.connect(self._filtered_model._on_rows_changed)
        self._filtered_model.sourceCurrentIndexChanged(self._current)

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

    # --------------------------------------------------------- persistence ---
    def _load_saved_playlist(self) -> None:
        """Restore valid local files in their saved order without playing.

        A missing or unreadable store is just an empty first run. Files can
        disappear between sessions (renamed, deleted, or on an unplugged
        drive), so each unavailable row is skipped rather than making startup
        fail. The stored file is not rewritten merely because a drive is
        temporarily absent; reconnecting it before a later launch can bring
        those rows back.
        """
        path = self._storage_path
        if path is None or not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError):
            log.warning("local playlist store is corrupt (%s) — starting empty", path)
            self._backup_corrupt_store()
            return
        except OSError as exc:
            log.warning("could not read local playlist store %s: %s", path, exc)
            return

        if not isinstance(raw, dict) or not isinstance(raw.get("tracks"), list):
            log.warning(
                "local playlist store has an invalid format (%s) — starting empty", path
            )
            self._backup_corrupt_store()
            return

        try:
            saved_current = int(raw.get("currentIndex", -1))
        except (TypeError, ValueError, OverflowError):
            saved_current = -1
        saved_current_path = path_utils.normalise_path(raw.get("currentPath", ""))

        restored: list[Track] = []
        restored_current = -1
        skipped = 0
        for original_index, item in enumerate(raw["tracks"]):
            if not isinstance(item, dict):
                skipped += 1
                continue
            text = path_utils.normalise_path(item.get("path", ""))
            if not text:
                skipped += 1
                continue
            candidate = Path(text).expanduser()
            try:
                usable = (
                    candidate.is_file() and candidate.suffix.lower() in MEDIA_EXTENSIONS
                )
            except OSError:
                usable = False
            if not usable:
                skipped += 1
                continue
            try:
                duration = max(0, int(item.get("duration", 0) or 0))
            except (TypeError, ValueError, OverflowError):
                duration = 0
            title = str(item.get("title", "") or candidate.stem)
            restored.append(Track(str(candidate), title, duration, True))
            if original_index == saved_current:
                restored_current = len(restored) - 1

        # currentPath makes the selection resilient to an older store without
        # currentIndex and to harmless row-format changes. currentIndex remains
        # authoritative for duplicate file entries.
        if restored_current < 0 and saved_current_path:
            for row, track in enumerate(restored):
                if path_utils.normalise_path(track.path) == saved_current_path:
                    restored_current = row
                    break

        self._tracks = restored
        self._current = restored_current
        self._rebuild_shuffle()
        if restored:
            log.info("restored %d Local playlist item(s)", len(restored))
        if skipped:
            log.info("skipped %d unavailable Local playlist item(s)", skipped)

    def _backup_corrupt_store(self) -> None:
        """Keep a broken store for diagnosis instead of overwriting it."""
        path = self._storage_path
        if path is None or not path.exists():
            return
        base = path.with_suffix(".corrupt.json")
        backup = base
        number = 2
        while backup.exists():
            backup = base.with_name(f"{base.stem}-{number}{base.suffix}")
            number += 1
        try:
            path.replace(backup)
        except OSError:
            log.debug("could not back up corrupt local playlist store", exc_info=True)

    @staticmethod
    def _saved_path(raw: str) -> str:
        """Persist an absolute spelling so launch working-directory changes do
        not break files that originally arrived as relative command-line paths."""
        try:
            return str(Path(raw).expanduser().resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            return str(raw)

    def _schedule_save(self) -> None:
        if self._storage_path is None or self._shut_down:
            return
        self._save_dirty = True
        self._save_timer.start()

    @Slot()
    def save(self) -> None:
        """Atomically write the queue if it changed since the last save."""
        self._save_timer.stop()
        path = self._storage_path
        if path is None or not self._save_dirty:
            return

        current_path = ""
        if 0 <= self._current < len(self._tracks):
            current_path = self._saved_path(self._tracks[self._current].path)
        payload = {
            "version": PLAYLIST_FORMAT_VERSION,
            "currentIndex": self._current,
            "currentPath": current_path,
            "tracks": [
                {
                    "path": self._saved_path(track.path),
                    "title": track.title,
                    "duration": track.duration_ms,
                }
                for track in self._tracks
            ],
        }

        temp_name = ""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
            self._save_dirty = False
        except (OSError, TypeError, ValueError):
            # TypeError/ValueError are defensive: normal app rows contain only
            # JSON-safe values, but restore() is also a public Python API. One
            # bad caller must not let a timer callback bring down the app.
            log.warning("could not save Local playlist %s", path, exc_info=True)
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass

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
        self._schedule_save()
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
                self._schedule_save()
                break

    # ------------------------------------------------------------ removing ---
    @Slot(list, result=bool)
    def remove_rows(self, rows: list[int]) -> bool:
        """Clear Selected. The Delete key routes to the same Actions entry that
        the toolbar button does, so this has exactly one caller path.

        Returns True if the currently playing track was among the removed rows.
        """
        playing_removed = False
        changed = False
        playing_row = self._current
        wanted = sorted({int(r) for r in rows}, reverse=True)
        for row in wanted:
            if 0 <= row < len(self._tracks):
                changed = True
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
        if changed:
            self._schedule_save()
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
        self._schedule_save()

    @Slot(int, int)
    def move_row(self, source: int, target: int) -> None:
        """Drag-to-reorder."""
        n = len(self._tracks)
        if not (0 <= source < n) or not (0 <= target < n) or source == target:
            return
        self.beginMoveRows(
            QModelIndex(),
            source,
            source,
            QModelIndex(),
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
        self._schedule_save()

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
        self._schedule_save()

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

    @Property(QObject, constant=True)
    def filteredModel(self) -> QObject:  # noqa: N802 - QML-facing
        return self._filtered_model

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
        """Stop accepting probe results and wait for in-flight probes to exit.

        Setting the flag is not enough on its own: a probe that has already
        passed the `cancelled` check may be inside `done.emit()` when this
        object is collected, which crashes the interpreter rather than raising
        (§9). Clearing the queue and then *waiting* for the running probes is
        what makes teardown deterministic. Idempotent — teardown paths may call
        it more than once.
        """
        if self._shut_down:
            return
        self._shut_down = True
        self._save_timer.stop()
        self._probe_signals.cancelled = True
        try:
            # Drop probes that have not started; they cannot be waited on.
            self._pool.clear()
            # Bounded wait: a probe is a 2 s libVLC parse at worst, so this
            # returns promptly. The timeout means a wedged probe can never
            # hang application exit.
            self._pool.waitForDone(5000)
        except RuntimeError:
            # Pool already destroyed by a previous shutdown() — nothing to do.
            pass
        try:
            self._probe_signals.done.disconnect(self._on_probed)
        except (RuntimeError, TypeError):
            pass  # already disconnected, or the receiver is gone
        # Normal app exit always flushes the latest queue, even if the 400 ms
        # debounce has not elapsed yet.
        self.save()

    def to_list(self) -> list[dict]:
        return [
            {"path": t.path, "title": t.title, "duration": t.duration_ms}
            for t in self._tracks
        ]

    def restore(self, items: list[dict]) -> None:
        previous = self._current
        self.beginResetModel()
        self._tracks = [
            Track(
                i["path"],
                i.get("title", Path(i["path"]).stem),
                i.get("duration", 0),
                True,
            )
            for i in items
            if i.get("path")
        ]
        self._current = -1
        self.endResetModel()
        self.countChanged.emit()
        if previous != -1:
            self.currentIndexChanged.emit(-1)
        self._rebuild_shuffle()
        self._schedule_save()
