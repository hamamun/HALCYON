"""Shared media/subtitle extension classification.

These sets describe file types the shared controller and mode implementations
need to route correctly. They live in ``core`` so core code never has to import
from a concrete mode package (Local, M3U, etc.) just to answer "is this media?".
"""

from __future__ import annotations

#: Extensions file/folder import will pick up (§P1.5). Deliberately generous —
#: libVLC plays far more than this, but recursive scans should not hoover up
#: arbitrary documents.
VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts", ".m2ts", ".mts", ".flv",
    ".webm", ".mpg", ".mpeg", ".m4v", ".3gp", ".ogv", ".vob", ".divx", ".rmvb",
}
AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".aac", ".opus", ".ogg", ".wav", ".m4a", ".wma", ".alac",
    ".ape", ".aiff", ".dsf", ".mka", ".mpc",
}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

#: Sidecar subtitle formats. These are **not** media and must never enter a
#: playable queue: libVLC will happily "open" a subtitle as a media item with
#: no audio/video. Dropping one means "subtitle the current video".
SUBTITLE_EXTENSIONS = {
    ".srt", ".ass", ".ssa", ".sub", ".vtt", ".idx", ".sup", ".smi", ".txt",
}


def is_media_path(path: str) -> bool:
    """Return true when *path* has a known audio/video extension."""
    from pathlib import Path

    return Path(path).suffix.lower() in MEDIA_EXTENSIONS


def is_subtitle_path(path: str) -> bool:
    """Return true when *path* has a known sidecar subtitle extension."""
    from pathlib import Path

    return Path(path).suffix.lower() in SUBTITLE_EXTENSIONS
