"""Recent files and resume positions — Milestone 1.8.

``recent.json``, capped at 200 entries. Position is saved every 5 s and on close;
a resume is offered when you were more than 30 s in **and** more than 5% of the
file remains (§P1.5) — the thresholds stop it prompting for something you had
practically finished.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core import media_types, paths

log = logging.getLogger(__name__)

FILENAME = "recent.json"
MAX_ENTRIES = 200
SAVE_INTERVAL_MS = 5000
RESUME_MIN_POSITION_MS = 30_000
RESUME_MIN_REMAINING_FRACTION = 0.05


def entry_key(path: str) -> str:
    """The one key a file is filed under.

    **This is what made resume silently never work.** Positions were *saved*
    under the path derived from libVLC's MRL and *looked up* under the path the
    playlist holds, and on Windows those are different strings for the same
    file::

        playlist   E:\\drvie personal\\Andor.mkv     <- the lookup key
        from MRL   E:/drvie personal/Andor.mkv     <- the key it was saved under

    Different separators, so the dict lookup missed, so ``resume_position``
    returned 0 for every file forever. Nothing errored; the feature just never
    fired. Both sides now go through here, so a file has exactly one key
    regardless of which direction it arrived from.

    Case is folded on Windows only — NTFS is case-insensitive, so ``Andor.mkv``
    and ``andor.mkv`` are one file and must not be two entries. POSIX is
    case-sensitive and they are genuinely different files.
    """
    if not path:
        return ""
    text = paths.normalise_path(path).replace("\\", "/")
    while "//" in text[2:]:
        head, tail = text[:2], text[2:].replace("//", "/")
        text = head + tail
    text = text.rstrip("/")
    if sys.platform == "win32":
        text = text.lower()
    return text


class Library(QObject):
    """Recent list plus resume bookkeeping."""

    recentChanged = Signal()
    resumeAvailable = Signal(str, int)  # path, position_ms

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: dict[str, dict] = {}
        self._path = paths.data_file(FILENAME)
        self._current: str = ""
        self._engine = None
        self.load()

        self._save_timer = QTimer(self)
        self._save_timer.setInterval(SAVE_INTERVAL_MS)
        self._save_timer.timeout.connect(self._tick)
        self._save_timer.start()

    def bind(self, engine) -> None:
        self._engine = engine

    # ---------------------------------------------------------------- state ---
    def _tick(self) -> None:
        """Checkpoint the current position every 5 s."""
        if not self._current or self._engine is None:
            return
        try:
            if not self._engine.isPlaying:
                return
            self.record_position(self._current, self._engine.time, self._engine.duration)
        except Exception:
            log.debug("position checkpoint failed", exc_info=True)

    @Slot(str)
    def note_opened(self, path: str) -> None:
        self._current = path
        key = entry_key(path)
        if not key:
            return
        entry = self._entries.setdefault(key, {})
        # `path` is the display/playback path; `key` is what it is filed under.
        # Keeping both means recent.json stays readable and the lookup stays
        # exact.
        entry["path"] = path
        entry["key"] = key
        entry["title"] = Path(path).stem
        entry["opened"] = time.time()
        entry.setdefault("position", 0)
        entry.setdefault("duration", 0)
        self._trim()
        self.recentChanged.emit()

    @Slot(str, int, int)
    def record_position(self, path: str, position_ms: int, duration_ms: int) -> None:
        key = entry_key(path)
        if not key:
            return
        entry = self._entries.setdefault(
            key, {"path": path, "key": key, "title": Path(path).stem}
        )
        entry["position"] = max(0, int(position_ms))
        entry["duration"] = max(0, int(duration_ms))
        entry["opened"] = time.time()

    @Slot(str, result=int)
    def resume_position(self, path: str) -> int:
        """The position to resume from, or 0 if a resume is not warranted.

        **Video only** (§P1.5). An album track you were 40 seconds into does
        not want a modal dialog every time you play it; a film you are 24
        minutes into does.
        """
        if not media_types.is_video(path):
            return 0
        entry = self._entries.get(entry_key(path))
        if not entry:
            return 0
        position = int(entry.get("position", 0))
        duration = int(entry.get("duration", 0))
        if position < RESUME_MIN_POSITION_MS:
            return 0
        if duration > 0:
            remaining = (duration - position) / duration
            if remaining < RESUME_MIN_REMAINING_FRACTION:
                return 0
        return position

    @Slot(str)
    def clear_position(self, path: str) -> None:
        """Forget where we were — what *Start over* calls."""
        entry = self._entries.get(entry_key(path))
        if entry is not None:
            entry["position"] = 0

    # -------------------------------------------------------- track memory ---
    # Remembering the chosen audio/subtitle track per file (CHECKLIST §1.6).
    # Filed in the same recent.json entry as the resume position, under the
    # same key, because it is the same question: "what did I last do with this
    # file?" A second store would be a second thing to keep in sync.
    #
    # Tracks are remembered by **label**, not by id. libVLC's numeric ids are
    # assigned per demuxer run and are not stable across sessions — id 2 might
    # be Japanese today and the commentary tomorrow, which would silently play
    # the wrong audio. The label ("Japanese", "English AC3 5.1") is what the
    # user actually chose, and matching on it is either right or a clean miss.

    @Slot(str, str)
    def remember_audio_track(self, path: str, label: str) -> None:
        self._remember_track(path, "audioTrack", label)

    @Slot(str, str)
    def remember_subtitle_track(self, path: str, label: str) -> None:
        self._remember_track(path, "subtitleTrack", label)

    def _remember_track(self, path: str, field: str, label: str) -> None:
        key = entry_key(path)
        if not key:
            return
        entry = self._entries.setdefault(
            key, {"path": path, "key": key, "title": Path(path).stem}
        )
        entry[field] = str(label or "")

    @Slot(str, result=str)
    def remembered_audio_track(self, path: str) -> str:
        return self._remembered_track(path, "audioTrack")

    @Slot(str, result=str)
    def remembered_subtitle_track(self, path: str) -> str:
        return self._remembered_track(path, "subtitleTrack")

    def _remembered_track(self, path: str, field: str) -> str:
        entry = self._entries.get(entry_key(path))
        if not entry:
            return ""
        return str(entry.get(field) or "")

    @Property("QVariantList", notify=recentChanged)
    def recent(self) -> list:
        items = sorted(
            self._entries.values(), key=lambda e: e.get("opened", 0), reverse=True
        )
        return items[:MAX_ENTRIES]

    def _trim(self) -> None:
        if len(self._entries) <= MAX_ENTRIES:
            return
        ordered = sorted(
            self._entries.items(), key=lambda kv: kv[1].get("opened", 0), reverse=True
        )
        self._entries = dict(ordered[:MAX_ENTRIES])

    # ---------------------------------------------------------- persistence ---
    def load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            for entry in data["entries"]:
                path = entry.get("path")
                if not path:
                    continue
                # Re-key on load. A file written by an older build was filed
                # under its raw path; re-deriving the key here means an existing
                # recent.json keeps working instead of being silently ignored.
                key = entry.get("key") or entry_key(path)
                entry["key"] = key
                self._entries[key] = entry

    @Slot()
    def save(self) -> None:
        self._trim()
        payload = {"entries": list(self._entries.values())}
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.warning("could not save recent.json")

    def shutdown(self) -> None:
        self._save_timer.stop()
        self._tick()
        self.save()
