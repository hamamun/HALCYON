"""Lyrics — Milestone 1.8.

Sidecar ``.lrc`` files (timed, so they can auto-scroll and be clicked to seek)
plus plain embedded tags as a fallback.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

log = logging.getLogger(__name__)

#: [mm:ss.xx] or [mm:ss] — the standard LRC timestamp, possibly several per line.
_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str) -> list[dict]:
    """Parse LRC into ``[{timeMs, text}]``, sorted by time.

    Handles repeated timestamps on one line (``[00:12][01:30]same words``) and
    ignores ID tags such as ``[ar:]``.
    """
    lines: list[dict] = []
    for raw in text.splitlines():
        stamps = list(_TIMESTAMP.finditer(raw))
        if not stamps:
            continue
        content = _TIMESTAMP.sub("", raw).strip()
        if not content:
            continue
        for match in stamps:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction = match.group(3) or "0"
            millis = int(fraction.ljust(3, "0")[:3])
            lines.append(
                {"timeMs": minutes * 60_000 + seconds * 1000 + millis, "text": content}
            )
    lines.sort(key=lambda entry: entry["timeMs"])
    return lines


class Lyrics(QObject):
    """Lyrics for the current track, with a cursor that follows playback."""

    changed = Signal()
    currentLineChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lines: list[dict] = []
        self._timed = False
        self._current = -1

    @Slot(str)
    def load(self, media_path: str) -> None:
        self._lines = []
        self._timed = False
        self._current = -1

        if media_path:
            path = Path(media_path.replace("file://", ""))
            sidecar = path.with_suffix(".lrc")
            if sidecar.exists():
                try:
                    parsed = parse_lrc(sidecar.read_text(encoding="utf-8", errors="replace"))
                    if parsed:
                        self._lines = parsed
                        self._timed = True
                except OSError:
                    log.debug("could not read %s", sidecar)

        self.changed.emit()
        self.currentLineChanged.emit()

    @Slot(int)
    def update_position(self, position_ms: int) -> None:
        """Move the highlight. Called from the engine's time signal."""
        if not self._timed or not self._lines:
            return
        index = -1
        for i, line in enumerate(self._lines):
            if line["timeMs"] <= position_ms:
                index = i
            else:
                break
        if index != self._current:
            self._current = index
            self.currentLineChanged.emit()

    @Property("QVariantList", notify=changed)
    def lines(self) -> list:
        return self._lines

    @Property(bool, notify=changed)
    def timed(self) -> bool:
        return self._timed

    @Property(int, notify=currentLineChanged)
    def currentLine(self) -> int:  # noqa: N802 - QML-facing
        return self._current
