"""Track metadata and album art — Milestone 1.8.

Everything comes from libVLC's own parser, so there is no ffprobe or mutagen
dependency to bundle (§P1.5: "via libVLC (no ffprobe)").
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

log = logging.getLogger(__name__)


def _fmt_duration(ms: int) -> str:
    if ms <= 0:
        return "\u2014"
    total = ms // 1000
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_bitrate(bps: int) -> str:
    return f"{bps // 1000} kbps" if bps > 0 else "\u2014"


class Metadata(QObject):
    """Metadata for whatever is currently loaded."""

    changed = Signal()

    def __init__(self, engine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._title = ""
        self._artist = ""
        self._album = ""
        self._artwork = ""
        self._details: list[dict] = []

    @Slot(str)
    def load(self, path: str) -> None:
        self._reset()
        if not path:
            self.changed.emit()
            return

        file_path = Path(path.replace("file://", ""))
        self._title = file_path.stem
        details = [
            {"label": "File", "value": file_path.name},
            {"label": "Container", "value": file_path.suffix.lstrip(".").upper() or "\u2014"},
        ]

        try:
            import vlc

            player = getattr(self._engine, "raw_player", None)
            media = player.get_media() if player is not None else None
            if media is not None:
                media.parse_with_options(vlc.MediaParseFlag.local, 3000)

                def meta(key):
                    try:
                        value = media.get_meta(key)
                        return value or ""
                    except Exception:
                        return ""

                self._title = meta(vlc.Meta.Title) or self._title
                self._artist = meta(vlc.Meta.Artist)
                self._album = meta(vlc.Meta.Album)
                self._artwork = meta(vlc.Meta.ArtworkURL)

                duration = int(media.get_duration())
                details.append({"label": "Duration", "value": _fmt_duration(duration)})

                for track in media.tracks_get() or []:
                    if track.type == vlc.TrackType.video:
                        video = track.video.contents
                        details.append(
                            {
                                "label": "Resolution",
                                "value": f"{video.width}\u00D7{video.height}",
                            }
                        )
                        fps = (
                            video.frame_rate_num / video.frame_rate_den
                            if video.frame_rate_den
                            else 0
                        )
                        if fps:
                            details.append({"label": "Frame rate", "value": f"{fps:.3g} fps"})
                        details.append(
                            {"label": "Video codec", "value": _fourcc(track.codec)}
                        )
                    elif track.type == vlc.TrackType.audio:
                        audio = track.audio.contents
                        details.append(
                            {"label": "Audio codec", "value": _fourcc(track.codec)}
                        )
                        details.append(
                            {
                                "label": "Channels",
                                "value": f"{audio.channels} ch @ {audio.rate} Hz",
                            }
                        )
                        if track.bitrate:
                            details.append(
                                {"label": "Bitrate", "value": _fmt_bitrate(track.bitrate)}
                            )
        except Exception:
            log.debug("metadata parse failed for %s", path, exc_info=True)

        self._details = details
        self.changed.emit()

    def _reset(self) -> None:
        self._title = ""
        self._artist = ""
        self._album = ""
        self._artwork = ""
        self._details = []

    @Property(str, notify=changed)
    def title(self) -> str:
        return self._title

    @Property(str, notify=changed)
    def artist(self) -> str:
        return self._artist

    @Property(str, notify=changed)
    def album(self) -> str:
        return self._album

    @Property(str, notify=changed)
    def artworkUrl(self) -> str:  # noqa: N802 - QML-facing
        return self._artwork

    @Property("QVariantList", notify=changed)
    def details(self) -> list:
        return self._details


def _fourcc(codec: int) -> str:
    try:
        raw = codec.to_bytes(4, "little")
        text = raw.decode("ascii", "ignore").strip("\x00 ")
        return text.upper() or str(codec)
    except Exception:
        return str(codec)
