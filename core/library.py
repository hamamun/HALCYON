"""Recent files and resume positions — Milestone 1.8.

``recent.json``, capped at 200 entries. Position is saved every 5 s and on close;
a resume is offered when you were more than 30 s in **and** more than 5% of the
file remains (§P1.5) — the thresholds stop it prompting for something you had
practically finished.
"""

from __future__ import annotations

import json
import logging
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
        entry = self._entries.setdefault(path, {})
        entry["path"] = path
        entry["title"] = Path(path).stem
        entry["opened"] = time.time()
        entry.setdefault("position", 0)
        entry.setdefault("duration", 0)
        self._trim()
        self.recentChanged.emit()

    @Slot(str, int, int)
    def record_position(self, path: str, position_ms: int, duration_ms: int) -> None:
        if not path:
            return
        entry = self._entries.setdefault(path, {"path": path, "title": Path(path).stem})
        entry["position"] = max(0, int(position_ms))
        entry["duration"] = max(0, int(duration_ms))
        entry["opened"] = time.time()

    @Slot(str, result=int)
    def resume_position(self, path: str) -> int:
        """The position to resume from, or 0 if a resume is not warranted."""
        entry = self._entries.get(path)
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
        if path in self._entries:
            self._entries[path]["position"] = 0

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
                if path:
                    self._entries[path] = entry

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
