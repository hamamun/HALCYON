#!/usr/bin/env python3
"""Nuitka standalone build for Halcyon — the only supported release pipeline.

This script is the single entry point CI uses to produce ``dist/main.dist``
(the tree Inno Setup packages into ``Halcyon-Setup.exe``). It has two stages,
and BOTH must succeed for the build to be considered good:

1. **Build** — invoke Nuitka with the argument list from
   :func:`get_nuitka_args`.
2. **Verify** — walk ``dist/main.dist`` and hard-fail unless every file the
   app needs at runtime is actually present (see :func:`verify_dist`).

Why the verify stage is not optional
------------------------------------
Nuitka changed the semantics of ``--include-data-dir`` (2.x): it now treats
the directory as *data files only* and **silently skips** anything with a
"code" suffix — ``.dll``, ``.exe``, ``.so``, ``.pyd``, … (see
``default_ignored_suffixes`` in ``nuitka/freezer/IncludedDataFiles.py`` and
Nuitka issue #3116). That is precisely how release 1.2.1 shipped a
``vendor/vlc`` directory containing ``plugins.dat`` and ``hrtfs/`` but **no
libvlc.dll, no libvlccore.dll and no plugin DLLs** — the installer looked
correct, installed correctly, and the app then died on first launch with
``FileNotFoundError: libvlc.dll``.

Two rules follow, and this file encodes both:

* Directories that contain DLLs (``vendor/vlc``, ``vendor/webview2``) are
  included with ``--include-raw-dir``, which copies the tree verbatim and
  ignores nothing. ``--include-data-dir`` is reserved for genuinely
  code-free trees (QML, shaders, assets, config).
* The build is only green when :func:`verify_dist` has proven, file by file,
  that the DLLs are in the output. A silent regression in a future Nuitka
  version turns into a loud CI failure instead of a broken installer.

Bundled trees and why each is needed:
  vendor/vlc/       libVLC runtime: libvlc.dll, libvlccore.dll, plugins/
                    (with plugins.dat), hrtfs/ — raw dir, contains DLLs.
  vendor/webview2/  WebView2 SDK bridge DLLs (§P3.2) — raw dir, contains DLLs.
  ui/, modes/,      QML + compiled shaders loaded from disk by dynamic
  Halcyon/          Loaders and the Halcyon.Ui import bridge.
  assets/, config/, icons/first-run defaults/mobile remote static files.
  remote/static/
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Fallback only — the real version is read from core/version.py, the single
#: source of truth shared with packaging/installer/Halcyon.iss.
_FALLBACK_VERSION = "1.2.2"


def read_app_version() -> str:
    """Read ``__version__`` from ``core/version.py`` without importing it.

    Executed as text so this works before dependencies are installed and can
    never pull in Qt. Falls back to :data:`_FALLBACK_VERSION` only if the
    file is unreadable, so an amputated checkout still produces a build.
    """
    version_ns: dict[str, object] = {}
    version_file = ROOT / "core" / "version.py"
    try:
        exec(version_file.read_text(encoding="utf-8"), version_ns)  # noqa: S102
        return str(version_ns.get("__version__", _FALLBACK_VERSION))
    except OSError:
        return _FALLBACK_VERSION


# --------------------------------------------------------------------------
# Stage 1 — the Nuitka command line
# --------------------------------------------------------------------------

#: Directories copied VERBATIM into the distribution. These contain native
#: DLLs, which --include-data-dir silently drops (the 1.2.1 bug) — they must
#: use --include-raw-dir and nothing else.
RAW_DIRS: tuple[tuple[str, str], ...] = (
    ("vendor/vlc", "vendor/vlc"),
    ("vendor/webview2", "vendor/webview2"),
)

#: Code-free data trees. Safe for --include-data-dir (nothing in them has a
#: suffix Nuitka strips; QML/QSB/PNG/ICO/JSON all pass through).
DATA_DIRS: tuple[tuple[str, str], ...] = (
    ("modes", "modes"),
    ("ui", "ui"),
    ("Halcyon", "Halcyon"),
    ("assets", "assets"),
    ("remote/static", "remote/static"),
    ("config", "config"),
)

# libVLC's binauralizer resolves its HRTF relative to the directory holding
# libvlccore.dll, so the frozen build must keep hrtfs/ next to it or 5.1
# content silently loses spatial audio. The vendor/vlc raw dir above already
# carries vendor/vlc/hrtfs verbatim; the explicit path below is what
# tests/test_hrtf_bundling.py pins so packaging edits cannot forget it.
VLC_HRTF_DIR = ROOT / "vendor" / "vlc" / "hrtfs"


def get_nuitka_args(
    output_dir: Path,
    onefile: bool = False,
    console: bool = False,
) -> list[str]:
    """Generate the full Nuitka command line for building Halcyon."""
    app_version = read_app_version()

    args = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--enable-plugin=pyside6",
        # CI has no interactive terminal; never stall on a download prompt.
        "--assume-yes-for-downloads",
        # QML app: bundle the Qt qml plugin family, otherwise the frozen
        # build ships QML files that cannot be loaded.
        "--include-qt-plugins=qml",
        "--include-package=modes",
        "--include-package=ui",
        "--include-package=core",
        "--include-package=engine",
        "--include-package=remote",
        # python-vlc is imported lazily (inside VlcEngine.__init__, after the
        # DLL path has been fixed up), so Nuitka's static analysis misses it
        # and the frozen build fails with ModuleNotFoundError: vlc. Force it.
        "--include-module=vlc",
        # WebView2 is reached through pythonnet at runtime; same story.
        "--include-module=clr",
        "--include-package=pythonnet",
        "--output-filename=Halcyon.exe",
        "--product-name=Halcyon",
        "--file-description=Halcyon media player",
        "--company-name=Halcyon",
        # Windows requires file/product version numbers whenever any other
        # version info field is given; without them Nuitka exits immediately.
        f"--file-version={app_version}",
        f"--product-version={app_version}",
        f"--output-dir={output_dir}",
    ]

    if onefile:
        args.append("--onefile")

    if sys.platform == "win32":
        # Release builds are GUI subsystem (no console window). --console
        # keeps the console attached so startup crashes are visible in a
        # terminal. The installer always ships the GUI build.
        if console:
            args.append("--windows-console-mode=force")
        else:
            args.append("--windows-console-mode=disable")

    icon_path = ROOT / "assets" / "halcyon.ico"
    if icon_path.exists():
        args.append(f"--windows-icon-from-ico={icon_path}")

    # DLL-bearing vendor trees — RAW copies, never data dirs. See module
    # docstring: --include-data-dir silently drops .dll/.exe files, which is
    # exactly how 1.2.1 shipped a vendor/vlc with no libvlc.dll in it.
    # The vendor/vlc raw dir includes vendor/vlc/hrtfs (spatial audio HRTF).
    for src_rel, dest_rel in RAW_DIRS:
        src = ROOT / Path(src_rel)
        if src.is_dir():
            args.append(f"--include-raw-dir={src}={dest_rel}")

    # Code-free data trees.
    for src_rel, dest_rel in DATA_DIRS:
        src = ROOT / Path(src_rel)
        if src.is_dir():
            args.append(f"--include-data-dir={src}={dest_rel}")

    args.append(str(ROOT / "main.py"))
    return args


# --------------------------------------------------------------------------
# Stage 2 — distribution verification
# --------------------------------------------------------------------------


def _dist_dir(output_dir: Path) -> Path:
    """The standalone output tree for a build rooted at ``output_dir``."""
    return output_dir / "main.dist"


def verify_dist(output_dir: Path) -> list[str]:
    """Prove the distribution is complete; return a list of problems.

    Every check here corresponds to a real, observed failure mode:

    * ``vendor/vlc/libvlc.dll`` + ``libvlccore.dll`` missing → the 1.2.1
      release: FileNotFoundError at first launch on a clean machine.
    * ``vendor/vlc/plugins`` empty of DLLs → libVLC initialises but cannot
      decode anything (no demux/codec/aout/vout modules).
    * ``vendor/webview2`` DLLs missing → Web mode dead with a vague panel.
    * ``hrtfs`` missing → binaural spatial audio silently degrades (warning
      only: playback still works).
    * ``ui/`` / ``modes/`` / ``Halcyon/`` missing → blank panels, because
      dynamic QML Loaders resolve those files from disk.

    Checks are conditional on the corresponding *source* tree existing, so a
    developer building without vendor files (system VLC fallback) is not
    blocked — CI always fetches vendor files first, so on CI every check is
    live.
    """
    dist = _dist_dir(output_dir)
    problems: list[str] = []

    def require(relative: str, why: str) -> None:
        p = dist / relative
        if not p.exists():
            problems.append(f"MISSING {relative}  ({why})")
        elif p.is_file() and p.stat().st_size == 0:
            problems.append(f"EMPTY   {relative}  ({why})")

    if not dist.is_dir():
        return [f"MISSING {dist} — Nuitka produced no standalone output tree"]

    require("Halcyon.exe", "the application binary")

    if (ROOT / "vendor" / "vlc").is_dir():
        require("vendor/vlc/libvlc.dll", "libVLC entry DLL — app dies without it")
        require("vendor/vlc/libvlccore.dll", "libVLC core DLL — app dies without it")
        require("vendor/vlc/plugins", "libVLC plugin tree")
        require("vendor/vlc/plugins/plugins.dat", "plugin cache from vlc-cache-gen")

        plugin_dlls = list((dist / "vendor" / "vlc" / "plugins").rglob("*.dll")) if (
            dist / "vendor" / "vlc" / "plugins"
        ).is_dir() else []
        if not plugin_dlls:
            problems.append(
                "MISSING vendor/vlc/plugins/**/*.dll  "
                "(no plugin DLLs shipped — libVLC would load but decode nothing)"
            )
        else:
            print(f"  verified {len(plugin_dlls)} VLC plugin DLLs")

        # HRTF is a warning-level check: playback works without it, only
        # binaural spatialisation is lost. Report loudly, do not fail.
        hrtf_dir = dist / "vendor" / "vlc" / "hrtfs"
        if VLC_HRTF_DIR.is_dir() and not any(hrtf_dir.glob("*.sofa")):
            print("  WARNING: vendor/vlc/hrtfs/*.sofa not in dist — spatial audio HRTF lost")

    if (ROOT / "vendor" / "webview2").is_dir():
        require(
            "vendor/webview2/Microsoft.Web.WebView2.Core.dll",
            "WebView2 managed bridge — Web mode dead without it",
        )
        require(
            "vendor/webview2/WebView2Loader.dll",
            "WebView2 native loader — Web mode dead without it",
        )

    for tree, why in (
        ("ui", "QML shell loaded from disk"),
        ("modes", "mode panels loaded from disk"),
        ("Halcyon", "Halcyon.Ui QML import bridge"),
        ("assets", "icons"),
    ):
        if (ROOT / tree).is_dir():
            require(tree, why)

    return problems


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and verify the Halcyon standalone distribution (Nuitka)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Output directory for the compiled build (default: dist/)",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Produce a single executable file instead of a standalone folder",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Keep a console window attached (diagnosing startup failures)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Nuitka build command without running it",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip the build; only verify an existing dist tree",
    )
    args = parser.parse_args()

    cmd = get_nuitka_args(args.output_dir, onefile=args.onefile, console=args.console)

    if args.dry_run:
        print("Nuitka build command (dry run):")
        print(" ".join(cmd))
        return 0

    if not args.verify_only:
        print(f"Building Halcyon {read_app_version()} with Nuitka...")
        res = subprocess.run(cmd, cwd=ROOT, check=False)
        if res.returncode != 0:
            print(f"Nuitka build FAILED (exit {res.returncode})", file=sys.stderr)
            return res.returncode

    if args.onefile:
        # Onefile embeds everything in the binary; the on-disk layout checks
        # below only apply to the standalone tree the installer ships.
        print("Onefile build — skipping standalone layout verification.")
        return 0

    print(f"Verifying distribution at {_dist_dir(args.output_dir)} ...")
    problems = verify_dist(args.output_dir)
    if problems:
        print("", file=sys.stderr)
        print("DISTRIBUTION VERIFICATION FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "\nRefusing to call this build good — an installer made from this "
            "tree would fail on a clean machine (this is the exact class of "
            "bug that shipped in 1.2.1).",
            file=sys.stderr,
        )
        return 1

    print("Distribution verified OK — all runtime files present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
