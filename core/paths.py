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


def _runtime_root() -> Path:
    """Locate the application root in every supported runtime.

    Order matters:

    1. **Nuitka standalone.**  This is the build the Inno installer ships.
       Nuitka neither sets ``sys.frozen`` nor makes ``__file__`` point at the
       install dir, and ``__compiled__.containing_dir`` reports the directory
       of *whichever module reads it* — so reading it from this ``core.paths``
       submodule would yield ``<app>\\core``, one level too deep, and the
       bundled ``vendor\\vlc`` tree would never be found. For a standalone
       build the bundled data files always live beside the executable, so the
       directory of ``sys.executable`` is the correct, module-independent
       root.
    2. **Nuitka onefile / macOS app bundle.**  Here the data files live in a
       temp unpack directory (or inside the ``.app``), not beside the
       executable. ``__compiled__.containing_dir`` from the *main* module
       abstracts that. We cannot read the main module's value directly from
       here, but Nuitka exposes the same value through ``__compiled__``; if a
       containing_dir is present and is NOT the directory of the executable,
       use it (the onefile/unpack case).
    3. **PyInstaller.**  ``sys.frozen`` is set and bundled resources live
       under ``sys._MEIPASS``.
    4. **Source checkout.**  Two parents up from this file — the directory
       holding ``main.py``.

    Using anything based on ``os.getcwd()`` would break when Explorer launches
    the app with a different working directory (file associations, the
    AutoPlay handler), so it is deliberately never consulted.
    """
    exe_dir = Path(sys.executable).resolve().parent

    # In a Nuitka build every compiled module has a ``__compiled__`` attribute
    # in its own globals (Nuitka does *not* set ``sys.frozen`` — that is a
    # PyInstaller convention). It may also be visible as a builtin in some
    # Nuitka configurations, so check both.
    compiled = globals().get("__compiled__")
    if compiled is None:
        compiled = getattr(__import__("builtins"), "__compiled__", None)
    containing_dir = getattr(compiled, "containing_dir", None)

    if containing_dir is not None:
        containing_path = Path(containing_dir).resolve()
        # Standalone: containing_dir of a submodule is a child of the .dist
        # folder (e.g. .dist\\core). The exe directory IS the .dist root and
        # is where vendor/ and ui/ live.
        if containing_path == exe_dir or containing_path.is_relative_to(exe_dir):
            return exe_dir
        # Onefile / app bundle: data files are in the unpack/containing
        # location, which differs from the exe directory.
        return containing_path

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return exe_dir

    return Path(__file__).resolve().parent.parent


#: Application root — the directory containing main.py (source) or the
#: compiled executable / unpacked bundle (packaged build).
ROOT = _runtime_root()

#: First-run defaults shipped with the app.
DEFAULTS_DIR = ROOT / "config"

#: Bundled libVLC (§P1.3). Gitignored; see README for how to populate it.
VENDOR_VLC = ROOT / "vendor" / "vlc"

VENDOR_WEBVIEW2 = ROOT / "vendor" / "webview2"

ASSETS = ROOT / "assets"
UI_DIR = ROOT / "ui"
SHADERS = UI_DIR / "shaders"


def is_packaged_build() -> bool:
    """True when running inside a Nuitka/PyInstaller bundle (not a source run)."""
    if globals().get("__compiled__") is not None:
        return True
    if getattr(__import__("builtins"), "__compiled__", None) is not None:
        return True
    return bool(getattr(sys, "frozen", False))


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
