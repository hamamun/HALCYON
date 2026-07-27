"""Where Halcyon keeps things.

Runtime state lives **only** in the per-user app-data directory (§P1.3):

    Windows  %APPDATA%\\Halcyon
    Linux    ~/.local/share/Halcyon        (development)
    macOS    ~/Library/Application Support/Halcyon

The repository ``config/`` directory holds first-run defaults which are copied
once, never read afterwards. Set ``HALCYON_DATA_DIR`` to override (used by the
test suite so it never touches a real profile).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Halcyon"

#: Repository root — the directory containing main.py.
ROOT = Path(__file__).resolve().parent.parent

#: First-run defaults shipped with the app.
DEFAULTS_DIR = ROOT / "config"

#: Bundled libVLC (§P1.3). Gitignored; see README for how to populate it.
VENDOR_VLC = ROOT / "vendor" / "vlc"

ASSETS = ROOT / "assets"
UI_DIR = ROOT / "ui"
SHADERS = UI_DIR / "shaders"


def qml_url(url: str) -> str:
    """Resolve a ``qrc:/`` QML URL for the way Halcyon is actually running.

    ``ModeSpec`` declares its QML as ``qrc:/modes/local/LocalPanel.qml`` — the
    right form for a frozen build, where everything is compiled into a Qt
    resource. Running from a source checkout there is no resource bundle, so
    that URL resolves to nothing and the Loader silently renders an empty panel.

    This maps the URL onto the equivalent file on disk when that file exists,
    and otherwise hands the ``qrc:`` URL back untouched so a packaged build
    keeps using its resources. Non-``qrc:`` URLs pass straight through.
    """
    if not url.startswith("qrc:"):
        return url
    relative = url[len("qrc:") :].lstrip("/")
    on_disk = ROOT / relative
    if on_disk.exists():
        return on_disk.as_uri()
    return url


def normalise_path(raw) -> str:
    """Turn anything the UI can hand us into a plain filesystem path.

    QML's ``FileDialog`` yields percent-encoded URLs — the very first log in this
    repo came from ``E:\\drvie personal\\...``, which arrives as
    ``file:///E:/drvie%20personal/...``. Three things have to happen, and a
    ``.replace("file://", "")`` does none of them:

    * percent-decoding, or the path contains a literal ``%20`` and never exists;
    * dropping the leading slash on ``/E:/...``, or Windows rejects it;
    * leaving UNC paths (``file://server/share``) with their host intact.

    Non-URL input passes through untouched, so this is safe to call twice.
    """
    text = str(raw).strip()
    if not text:
        return ""
    if not text.lower().startswith("file:"):
        return text

    from urllib.parse import unquote, urlparse

    parsed = urlparse(text)
    path = unquote(parsed.path)
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        # file://server/share/file -> \\server\share\file
        return f"//{parsed.netloc}{path}".replace("/", os.sep) if os.sep == "\\" \
            else f"//{parsed.netloc}{path}"
    # file:///E:/x -> /E:/x -> E:/x
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


def _platform_data_dir() -> Path:
    override = os.environ.get("HALCYON_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


def data_dir() -> Path:
    """The writable profile directory, created on first access."""
    d = _platform_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_file(name: str) -> Path:
    return data_dir() / name


def cache_dir() -> Path:
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def seed_defaults() -> list[str]:
    """Copy any missing first-run defaults from ``config/`` into the profile.

    Only copies files that do not already exist — a user's edits are never
    clobbered by an upgrade. Returns the names copied.
    """
    if not DEFAULTS_DIR.is_dir():
        return []
    copied: list[str] = []
    target = data_dir()
    for src in sorted(DEFAULTS_DIR.iterdir()):
        if not src.is_file():
            continue
        dst = target / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
            copied.append(src.name)
    return copied
