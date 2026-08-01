"""Recent files and resume positions — Milestone 1.8.

``recent.json``, capped at 200 entries. Position is saved every 5 s and on close;
a resume is offered when you were more than 30 s in **and** more than 5% of the
file remains (§P1.5) — the thresholds stop it prompting for something you had
practically finished.

**One canonical key per file (§4.1).** Every entry is filed under
:func:`media_key`, and every lookup goes through it too. This is load-bearing,
not tidiness: the two callers reach this class by different routes and used to
spell the same file two different ways.

    playlist -> openPath()      ->  resume_position("E:\\Movies\\film.mkv")
    engine   -> mediaChanged    ->  note_opened("E:/Movies/film.mkv")

Storing under one spelling and looking up under the other meant
``resume_position`` returned 0 for *every* file on Windows, so playback never
resumed and ``clear_position`` silently zeroed nothing. Normalising in one place
here fixes resume, the recent list and Start Over together, and leaves
``core/app.py``, the engine and the playlist untouched.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core import paths

log = logging.getLogger(__name__)

FILENAME = "recent.json"
MAX_ENTRIES = 200
SAVE_INTERVAL_MS = 5000
RESUME_MIN_POSITION_MS = 30_000
RESUME_MIN_REMAINING_FRACTION = 0.05


def media_key(raw) -> str:
    """The one spelling of a media path used as a dictionary key.

    Handles the three ways the same file arrives here:

    * a ``file://`` URL from the engine's MRL — percent-decoded by
      :func:`core.paths.normalise_path`;
    * a relative path from the command line — made absolute, so ``film.mkv``
      and ``/home/me/film.mkv`` are one entry rather than two;
    * a Windows path in either slash direction and any case — folded to a
      single form via ``os.path.normcase``.

    Network URLs (Phase 2's HLS streams) are left exactly as they are: they are
    not filesystem paths and ``resolve()`` would mangle them.
    """
    text = paths.normalise_path(raw)
    if not text:
        return ""
    lowered = text.lower()
    if "://" in text and not lowered.startswith("file:"):
        return text  # a stream URL is already canonical
    try:
        # strict=False: a file that has since been deleted or unplugged must
        # still resolve to the key it was recorded under, or its history is
        # orphaned the moment the drive is disconnected.
        resolved = str(Path(text).expanduser().resolve(strict=False))
    except (OSError, ValueError, RuntimeError):
        resolved = text
    return os.path.normcase(resolved)


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
        key = media_key(path)
        if not key:
            return
        self._current = key
        entry = self._entries.setdefault(key, {})
        # `path` keeps the human-readable spelling for the recent list; `key` is
        # what the dictionary is filed under. Displaying normcase'd text would
        # show Windows users their filenames in lower case.
        entry.setdefault("path", paths.normalise_path(path) or path)
        entry["title"] = Path(entry["path"]).stem
        entry["opened"] = time.time()
        entry.setdefault("position", 0)
        entry.setdefault("duration", 0)
        self._trim()
        self.recentChanged.emit()

    @Slot(str, int, int)
    def record_position(self, path: str, position_ms: int, duration_ms: int) -> None:
        key = media_key(path)
        if not key:
            return
        display = paths.normalise_path(path) or path
        entry = self._entries.setdefault(
            key, {"path": display, "title": Path(display).stem}
        )
        entry["position"] = max(0, int(position_ms))
        entry["duration"] = max(0, int(duration_ms))
        entry["opened"] = time.time()

    @Slot(str, result=int)
    def resume_position(self, path: str) -> int:
        """The position to resume from, or 0 if a resume is not warranted."""
        entry = self._entries.get(media_key(path))
        if not entry:
            return 0
        position = int(entry.get("position", 0))
        duration = int(entry.get("duration", 0))
        if position < RESUME_MIN_POSITION_MS:
            log.debug(
                "no resume for %s: %d ms is under the %d ms threshold",
                path, position, RESUME_MIN_POSITION_MS,
            )
            return 0
        if duration > 0:
            remaining = (duration - position) / duration
            if remaining < RESUME_MIN_REMAINING_FRACTION:
                log.debug(
                    "no resume for %s: only %.1f%% of the file remains",
                    path, remaining * 100,
                )
                return 0
        log.debug("resume %s at %d ms", path, position)
        return position

    @Slot(str)
    def clear_position(self, path: str) -> None:
        key = media_key(path)
        if key in self._entries:
            self._entries[key]["position"] = 0
            log.debug("cleared saved position for %s", path)

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
        """Read ``recent.json``, re-keying anything written by an older build.

        Entries used to be filed under whatever spelling the caller happened to
        use, so an existing profile holds a mix of ``E:/x/y.mkv`` and
        ``E:\\x\\y.mkv``. Both fold to the same :func:`media_key` here, and when
        two rows collide the more recently opened one wins — so a user upgrading
        keeps their resume positions instead of starting from scratch.
        """
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if not (isinstance(data, dict) and isinstance(data.get("entries"), list)):
            return
        merged = 0
        for entry in data["entries"]:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if not path:
                continue
            key = media_key(path)
            if not key:
                continue
            existing = self._entries.get(key)
            if existing is None:
                self._entries[key] = entry
                continue
            merged += 1
            if entry.get("opened", 0) >= existing.get("opened", 0):
                self._entries[key] = entry
        if merged:
            log.info("recent.json: merged %d duplicate entr(ies) on load", merged)

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
