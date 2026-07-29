"""Track metadata and album art — Milestone 1.8.

Everything comes from libVLC's own parser, so there is no ffprobe or mutagen
dependency to bundle (§P1.5: "via libVLC (no ffprobe)").
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core import paths
from engine.vlc_tracks import media_tracks

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

    #: How many times to re-read while waiting for libVLC's async parse.
    _MAX_RETRIES = 5

    def __init__(self, engine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._title = ""
        self._artist = ""
        self._album = ""
        self._artwork = ""
        self._details: list[dict] = []
        self._path = ""
        self._retries = 0

    @Slot(str)
    def load(self, path: str) -> None:
        """Read metadata for ``path``.

        libVLC parses asynchronously, so the first read right after a track
        opens usually returns empty strings for title/artist/album/art. A
        couple of short retries pick the values up as soon as the parse lands
        — cheap, and the alternative (subscribing to MediaParsedChanged) fires
        on a VLC thread and would need marshalling back anyway.
        """
        self._reset()
        self._retries = 0
        if not path:
            self.changed.emit()
            return
        self._path = path
        self._read(path)

    def _read(self, path: str) -> None:
        file_path = Path(paths.normalise_path(path))
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
                # `local` alone parses the *stream* but never goes looking for
                # cover art, so ArtworkURL came back empty for every file and
                # the album-art slot was permanently blank. `fetch_local` is
                # the flag that extracts embedded covers and picks up
                # folder.jpg / cover.jpg next to the file. The two are a
                # bitmask, so they combine.
                #
                # MediaParseFlag members are ctypes enums; OR-ing them needs
                # their .value, and the result is passed back as a plain int.
                flags = (
                    vlc.MediaParseFlag.local.value
                    | vlc.MediaParseFlag.fetch_local.value
                )
                media.parse_with_options(flags, 3000)

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

                with media_tracks(vlc, media) as tracks:
                    for track in tracks:
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
                                details.append(
                                    {"label": "Frame rate", "value": f"{fps:.3g} fps"}
                                )
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

        # If the parse has not produced tags yet, look again shortly. Bounded
        # so a file that genuinely has no tags does not retry forever.
        if self._retries < self._MAX_RETRIES and not (self._artist or self._artwork):
            self._retries += 1
            QTimer.singleShot(400, self._retry)

    def _retry(self) -> None:
        # The user may have skipped to another track while we waited; only
        # refresh if this is still the file on air.
        if self._path:
            self._read(self._path)

    def _reset(self) -> None:
        self._title = ""
        self._artist = ""
        self._album = ""
        self._artwork = ""
        self._details = []
        self._path = ""

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
