"""Drive browser for the mobile remote — Local chip → Files (§R.2).

Serves the "all drives" file picker the phone uses to play files and load
subtitles. Pure filesystem code with no Qt involvement, so it runs happily on
the aiohttp thread. Only metadata crosses the wire — paths are validated to
exist and be directories, and forward slashes are used everywhere (the
Windows backslash gotcha, §R.4).
"""

from __future__ import annotations

import os
import string

#: Extensions shown in the browser. Anything else is invisible so the list
#: stays scannable on a phone.
VIDEO_EXT = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".3gp", ".ogv", ".vob",
    ".rm", ".rmvb", ".divx",
}
AUDIO_EXT = {
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus",
    ".wma", ".ape", ".aiff", ".alac", ".ac3", ".dts",
}
SUBTITLE_EXT = {".srt", ".sub", ".ass", ".ssa", ".vtt", ".idx"}

KIND_VIDEO = "video"
KIND_AUDIO = "audio"
KIND_SUBTITLE = "subtitle"


def kind_for(path: str) -> str | None:
    """Media kind for a path, or None when it is not a media file."""
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXT:
        return KIND_VIDEO
    if ext in AUDIO_EXT:
        return KIND_AUDIO
    if ext in SUBTITLE_EXT:
        return KIND_SUBTITLE
    return None


def is_media(path: str) -> bool:
    return kind_for(path) is not None


def _norm(path: str) -> str:
    """Normalise to forward slashes with a trailing root intact."""
    path = (path or "").strip().strip('"')
    if not path:
        return ""
    return path.replace("\\", "/")


def list_drives() -> list[dict]:
    """All drives on this machine (owner: all drives, §R.1#12)."""
    drives: list[dict] = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append({"name": f"{letter}:", "path": _norm(root)})
    else:
        drives.append({"name": "/", "path": "/"})
    return drives


def list_dir(path: str) -> dict:
    """Contents of a directory: folders + media files only.

    Returns a dict with ``path`` (normalised), ``parent`` (or None at a
    drive root), ``folders`` and ``files`` (name/path/kind). Raises
    ``ValueError`` for a missing/empty path; ``OSError`` perms bubble up to
    the API layer, which turns them into a readable 4xx.
    """
    raw = _norm(path)
    if not raw:
        raise ValueError("no path given")
    full = os.path.realpath(raw)
    if not os.path.isdir(full):
        raise ValueError("not a directory")

    folders: list[dict] = []
    files: list[dict] = []
    try:
        entries = sorted(os.scandir(full), key=lambda e: (e.name.lower()))
    except OSError:
        raise ValueError("cannot read directory")

    for entry in entries:
        name = entry.name
        if name.startswith("."):
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        child = _norm(entry.path)
        if is_dir:
            # Skip reparse points so the browser cannot loop on junctions.
            if entry.is_symlink():
                continue
            folders.append({"name": name, "path": child})
        else:
            kind = kind_for(name)
            if kind is not None:
                files.append({"name": name, "path": child, "kind": kind})

    parent = _norm(os.path.dirname(full))
    parent = None if parent == raw or parent in ("/", "") or (len(parent) == 3 and parent[1:] == ":/") else parent
    return {
        "path": _norm(full),
        "parent": parent,
        "folders": folders,
        "files": files,
    }
