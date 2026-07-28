"""One settings store — §P1.2.

A single flat JSON document in ``%APPDATA%\\Halcyon\\settings.json``, exposed to
QML as the ``Settings`` context object. Dotted keys namespace things without
nesting the API:

    settings.get("window.width", 1280)
    settings.set("audio.volume", 80)
    settings.set_mode("local", "repeat", "all")     # per-mode sub-tree

Writes are debounced (400 ms) and always atomic, so a crash mid-write cannot
leave a truncated file. ``flush()`` on shutdown.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from core import paths

log = logging.getLogger(__name__)

FILENAME = "settings.json"
WRITE_DEBOUNCE_MS = 400

DEFAULTS: dict[str, Any] = {
    # window / shell
    "window.x": -1,
    "window.y": -1,
    "window.width": 1280,
    "window.height": 760,
    "window.maximized": False,
    "window.leftPanelVisible": True,
    "window.rightPanelVisible": False,
    # playback
    "audio.volume": 80,
    "audio.muted": False,
    "playback.rate": 1.0,
    "playback.turboMode": False,
    "playback.resumeEnabled": True,
    # ui
    "ui.mode": "local",
    "ui.timeDisplayRemaining": False,
    "ui.osdEnabled": True,
    "ui.autoHideDelayMs": 2500,
    # video / engine
    "video.backend": "auto",  # auto | i420 | rv32
    "video.adjustEnabled": False,
    "video.contrast": 1.0,
    "video.brightness": 1.0,
    "video.hue": 0.0,
    "video.saturation": 1.0,
    "video.gamma": 1.0,
    # subtitles
    "subs.autoLoadSidecar": True,
    "subs.delayMs": 0,
    "subs.scale": 1.0,
    "subs.encoding": "",
    # subtitles — online (opensubtitles.com REST API v1)
    #: The user's own consumer key. Empty is a valid, expected state: the
    #: download UI renders a "not configured yet" panel rather than failing at
    #: request time. A key shipped in the binary would be shared by every
    #: install and throttled to nothing, so there is no default to fall back to.
    "subs.online.apiKey": "",
    #: Optional account. Anonymous downloads work with a smaller daily quota;
    #: signing in raises it. Stored in the same plain settings.json as
    #: everything else, which is why the UI says so next to the field.
    "subs.online.username": "",
    "subs.online.password": "",
    #: Preferred subtitle language, as an opensubtitles.com language code.
    "subs.online.language": "en",
    #: "best" — only what the file hash (or a strict title/episode match)
    #: vouches for. "all" — everything the query found, partial matches
    #: included, best-first. Default "best": for a file already on disk the
    #: hash match is almost always the right subtitle.
    "subs.online.matchMode": "best",
    #: Save next to the media (so it auto-loads next time) when the folder is
    #: writable; otherwise the profile cache is used automatically.
    "subs.online.saveAlongsideMedia": True,
}


class Settings(QObject):
    """Persistent key/value store. Also usable head-less (tests, tools)."""

    changed = Signal(str, "QVariant")  # key, new value

    def __init__(self, path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        paths.seed_defaults()
        self._path = path or paths.data_file(FILENAME)
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._dirty = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(WRITE_DEBOUNCE_MS)
        self._timer.timeout.connect(self.flush)
        self.load()

    # ---------------------------------------------------------------- io ---
    def load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("settings unreadable (%s) — falling back to defaults", exc)
            self._backup_corrupt()
            return
        if isinstance(raw, dict):
            self._data.update(raw)

    def _backup_corrupt(self) -> None:
        try:
            self._path.replace(self._path.with_suffix(".corrupt.json"))
        except OSError:
            pass

    @Slot()
    def flush(self) -> None:
        """Write immediately if dirty. Atomic: temp file + replace."""
        if not self._dirty:
            return
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(self._data, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self._path)
            self._dirty = False
        except OSError as exc:
            log.error("could not write settings: %s", exc)

    def _schedule(self) -> None:
        self._dirty = True
        self._timer.start()

    # ------------------------------------------------------------- access ---
    @Slot(str, result="QVariant")
    @Slot(str, "QVariant", result="QVariant")
    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return self._data[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return default

    @Slot(str, "QVariant")
    def set(self, key: str, value: Any) -> None:
        if self._data.get(key, object()) == value:
            return
        self._data[key] = value
        self._schedule()
        self.changed.emit(key, value)

    @Slot(str, result=bool)
    def get_bool(self, key: str) -> bool:
        return bool(self.get(key, False))

    @Slot(str, result=int)
    def get_int(self, key: str) -> int:
        try:
            return int(self.get(key, 0))
        except (TypeError, ValueError):
            return 0

    @Slot(str, result=float)
    def get_real(self, key: str) -> float:
        try:
            return float(self.get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0

    @Slot(str, result=str)
    def get_string(self, key: str) -> str:
        v = self.get(key, "")
        return "" if v is None else str(v)

    # --------------------------------------------------------- per mode ---
    @Slot(str, str, result="QVariant")
    @Slot(str, str, "QVariant", result="QVariant")
    def get_mode(self, mode_id: str, key: str, default: Any = None) -> Any:
        return self.get(f"mode.{mode_id}.{key}", default)

    @Slot(str, str, "QVariant")
    def set_mode(self, mode_id: str, key: str, value: Any) -> None:
        self.set(f"mode.{mode_id}.{key}", value)

    # ------------------------------------------------------------- misc ---
    @Slot()
    def reset_to_defaults(self) -> None:
        self._data = dict(DEFAULTS)
        self._dirty = True
        self.flush()

    @property
    def path(self) -> Path:
        return self._path

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)
