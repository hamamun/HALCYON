"""Command-line and installer integration for Windows shell launches.

The installer can register verbs such as ``Play with Halcyon`` and
``Add to Halcyon Queue``, but those verbs are only useful if the application
understands the arguments that Windows passes to the executable.  This module is
kept Qt-free so it can be unit-tested and used before the GUI starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from core import paths as path_utils

ACTION_ACTIVATE = "activate"
ACTION_PLAY = "play"
ACTION_QUEUE = "queue"

_CONTROL_FLAGS = {
    "--debug",
    "-d",
    "--trace-shutdown",
    "--no-pythonnet",
}
_ACTION_FLAGS = {
    "--play": ACTION_PLAY,
    "/play": ACTION_PLAY,
    "--queue": ACTION_QUEUE,
    "/queue": ACTION_QUEUE,
    "--add-to-queue": ACTION_QUEUE,
    "/add-to-queue": ACTION_QUEUE,
}
_PLAYLIST_EXTENSIONS = {".m3u", ".m3u8", ".pls"}


@dataclass(slots=True)
class LaunchRequest:
    """A normalized request from the command line or a second app instance."""

    action: str = ACTION_ACTIVATE
    paths: list[str] = field(default_factory=list)

    @property
    def has_paths(self) -> bool:
        return bool(self.paths)

    def to_payload(self) -> dict[str, Any]:
        return {"action": self.action, "paths": list(self.paths)}

    @classmethod
    def from_payload(cls, payload: Any) -> "LaunchRequest":
        if not isinstance(payload, dict):
            return cls()
        action = str(payload.get("action") or ACTION_ACTIVATE).lower()
        if action not in {ACTION_ACTIVATE, ACTION_PLAY, ACTION_QUEUE}:
            action = ACTION_ACTIVATE
        raw_paths = payload.get("paths") or []
        if isinstance(raw_paths, (str, bytes)):
            raw_paths = [raw_paths]
        cleaned = [normalise_launch_path(p) for p in raw_paths]
        cleaned = [p for p in cleaned if p]
        if cleaned and action == ACTION_ACTIVATE:
            action = ACTION_PLAY
        return cls(action=action, paths=cleaned)


def normalise_launch_path(value: Any) -> str:
    """Normalize a file/folder argument from Windows, QML or IPC."""
    text = path_utils.normalise_path(value).strip()
    if not text:
        return ""
    return text.strip('"')


def parse_launch_request(argv: Iterable[str]) -> LaunchRequest:
    """Parse Halcyon's own launch arguments while ignoring diagnostic switches.

    Supported forms:

    ``Halcyon.exe movie.mp4``
        Open/play the file.  This is what normal file association double-clicks
        can use.

    ``Halcyon.exe --play movie.mp4``
        Explicit play verb for context menus and AutoPlay.

    ``Halcyon.exe --queue movie.mp4``
        Add to the existing queue when an instance is already running.
    """
    items = list(argv)
    action = ACTION_ACTIVATE
    collected: list[str] = []
    passthrough = False

    for raw in items[1:]:
        arg = str(raw)
        lowered = arg.lower()

        if passthrough:
            collected.append(arg)
            continue
        if arg == "--":
            passthrough = True
            continue
        if lowered in _CONTROL_FLAGS:
            continue

        matched_action = None
        matched_value = None
        for prefix, candidate_action in (
            ("--play=", ACTION_PLAY),
            ("/play=", ACTION_PLAY),
            ("--queue=", ACTION_QUEUE),
            ("/queue=", ACTION_QUEUE),
            ("--add-to-queue=", ACTION_QUEUE),
            ("/add-to-queue=", ACTION_QUEUE),
        ):
            if lowered.startswith(prefix):
                matched_action = candidate_action
                matched_value = arg[len(prefix):]
                break
        if matched_action is not None:
            action = matched_action
            if matched_value:
                collected.append(matched_value)
            continue

        if lowered in _ACTION_FLAGS:
            action = _ACTION_FLAGS[lowered]
            continue

        # Unknown switches belong to Qt, Nuitka, a diagnostic launch or a future
        # feature.  They should not become fake media paths.
        if arg.startswith("-"):
            continue

        collected.append(arg)

    paths = [normalise_launch_path(p) for p in collected]
    paths = [p for p in paths if p]
    if paths and action == ACTION_ACTIVATE:
        action = ACTION_PLAY
    return LaunchRequest(action=action, paths=paths)


def is_playlist_path(path: str) -> bool:
    """Return true for playlist files that should open the M3U mode."""
    clean = str(path).split("?", 1)[0].split("#", 1)[0]
    return Path(clean).suffix.lower() in _PLAYLIST_EXTENSIONS


def split_media_and_playlists(paths: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split launch paths into normal media/folders and playlist documents."""
    media: list[str] = []
    playlists: list[str] = []
    for item in paths:
        if is_playlist_path(item):
            playlists.append(item)
        else:
            media.append(item)
    return media, playlists
