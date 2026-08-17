#!/usr/bin/env python3
"""Automated Nuitka standalone build script for Halcyon (§10).

Packages Halcyon (Phase 1 Local + Phase 2 M3U + Phase 3 Web) into a standalone
Windows build including:
  • Bundled libVLC plugins directory (--include-data-dir=vendor/vlc/plugins=vendor/vlc/plugins).
  • Vendored WebView2 SDK bridge files (--include-data-dir=vendor/webview2=vendor/webview2, §P3.2).
  • UI/QML tree, including pre-compiled QSB shaders and theme assets.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def get_nuitka_args(output_dir: Path, onefile: bool = False) -> list[str]:
    """Generate the Nuitka command-line arguments for building Halcyon."""
    args = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--enable-plugin=pyside6",
        # CI runs with no interactive terminal; never stall on a download
        # prompt (e.g. Dependency Walker / ccache) — assume yes instead.
        "--assume-yes-for-downloads",
        # QML app: bundle the Qt qml plugin family, otherwise the frozen
        # build ships QML files that cannot be loaded (Nuitka warns about
        # this during the build).
        "--include-qt-plugins=qml",
        "--include-package=modes",
        "--include-package=ui",
        "--include-package=core",
        "--include-package=engine",
        "--include-package=remote",
        # WebView2 is reached through pythonnet at runtime, so Nuitka cannot
        # infer these lazy imports from static analysis alone.
        "--include-module=clr",
        "--include-package=pythonnet",
        "--output-filename=Halcyon.exe",
        "--product-name=Halcyon",
        "--file-description=Halcyon media player",
        "--company-name=Halcyon",
        # Windows requires file/product version numbers whenever any version
        # info (product name, file description, company) is given; without
        # them Nuitka exits instantly on Windows with:
        #   "Error, company name and file or product version need to be given
        #    when any version information is given."
        "--file-version=1.2.0",
        "--product-version=1.2.0",
        f"--output-dir={output_dir}",
    ]

    if onefile:
        args.append("--onefile")

    if sys.platform == "win32":
        args.append("--windows-console-mode=disable")

    icon_path = ROOT / "assets" / "halcyon.ico"
    if icon_path.exists():
        args.append(f"--windows-icon-from-ico={icon_path}")

    vlc_root = ROOT / "vendor" / "vlc"
    if vlc_root.exists():
        # Copy the whole *prepared* VLC runtime.  The packaging workflow prunes
        # plugins before this step, so this includes root DLL dependencies,
        # plugins/plugins.dat and the hrtfs folder without shipping VLC's own UI.
        args.append(f"--include-data-dir={vlc_root}=vendor/vlc")

    # libVLC's binauralizer resolves its HRTF relative to the directory holding
    # libvlccore.dll, so the frozen build must keep hrtfs/ next to it or 5.1
    # content loses spatial audio with only a stderr line to show for it.
    # The root copy above already includes vendor/vlc/hrtfs; keep this explicit
    # path here so packaging checks cannot accidentally forget the requirement.
    vlc_hrtfs = ROOT / "vendor" / "vlc" / "hrtfs"

    webview2_vendor = ROOT / "vendor" / "webview2"
    if webview2_vendor.exists():
        args.append(f"--include-data-dir={webview2_vendor}=vendor/webview2")

    # Dynamic QML Loaders resolve source-mode components from disk in a source
    # checkout and from the same relative tree in a frozen build.  Include both
    # the mode QML and the Halcyon URI/qmldir bridge explicitly; otherwise the
    # Web chip can exist while WebStage.qml is absent from the distribution.
    for directory in (
        ROOT / "modes",
        ROOT / "ui",
        ROOT / "Halcyon",
        ROOT / "assets",
        ROOT / "remote" / "static",
        ROOT / "config",
    ):
        if directory.exists():
            dest = "remote/static" if directory.name == "static" and directory.parent.name == "remote" else directory.name
            args.append(f"--include-data-dir={directory}={dest}")

    args.append(str(ROOT / "main.py"))
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Halcyon standalone executable via Nuitka")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Output directory for the compiled build",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Produce a single executable file instead of standalone folder",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Nuitka build command without running it",
    )
    args = parser.parse_args()

    cmd = get_nuitka_args(args.output_dir, onefile=args.onefile)

    if args.dry_run:
        print("Nuitka build command (dry run):")
        print(" ".join(cmd))
        return 0

    print("Starting Nuitka build for Halcyon...")
    res = subprocess.run(cmd, cwd=ROOT, check=False)
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
