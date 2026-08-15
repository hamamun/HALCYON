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
        "--include-package=modes",
        "--include-package=ui",
        "--include-package=core",
        "--include-package=engine",
        # WebView2 is reached through pythonnet at runtime, so Nuitka cannot
        # infer these lazy imports from static analysis alone.
        "--include-module=clr",
        "--include-package=pythonnet",
        f"--output-dir={output_dir}",
    ]

    if onefile:
        args.append("--onefile")

    icon_path = ROOT / "assets" / "halcyon.ico"
    if icon_path.exists():
        args.append(f"--windows-icon-from-ico={icon_path}")

    vlc_plugins = ROOT / "vendor" / "vlc" / "plugins"
    if vlc_plugins.exists():
        args.append(f"--include-data-dir={vlc_plugins}=vendor/vlc/plugins")

    # libVLC's binauralizer resolves its HRTF relative to the directory holding
    # libvlccore.dll, so the frozen build must keep hrtfs/ next to it or 5.1
    # content loses spatial audio with only a stderr line to show for it.
    vlc_hrtfs = ROOT / "vendor" / "vlc" / "hrtfs"
    if vlc_hrtfs.exists():
        args.append(f"--include-data-dir={vlc_hrtfs}=vendor/vlc/hrtfs")

    webview2_vendor = ROOT / "vendor" / "webview2"
    if webview2_vendor.exists():
        args.append(f"--include-data-dir={webview2_vendor}=vendor/webview2")

    # Dynamic QML Loaders resolve source-mode components from disk in a source
    # checkout and from the same relative tree in a frozen build.  Include both
    # the mode QML and the Halcyon URI/qmldir bridge explicitly; otherwise the
    # Web chip can exist while WebStage.qml is absent from the distribution.
    for directory in (ROOT / "modes", ROOT / "ui", ROOT / "Halcyon"):
        if directory.exists():
            args.append(f"--include-data-dir={directory}={directory.name}")

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
