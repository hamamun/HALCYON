#!/usr/bin/env python3
"""Automated Nuitka standalone build script for Halcyon (§10).

Packages Halcyon (Phase 1 Local + Phase 2 M3U + Phase 3 Web) into a standalone
Windows build including:
  • Bundled libVLC plugins directory (--include-data-dir=vendor/vlc/plugins=vendor/vlc/plugins).
  • Vendored WebView2 SDK bridge files (--include-data-dir=vendor/webview2=vendor/webview2, §P3.2).
  • Pre-compiled QSB shaders (--include-data-dir=ui/shaders=ui/shaders).
  • QML resources and theme assets.
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

    webview2_vendor = ROOT / "vendor" / "webview2"
    if webview2_vendor.exists():
        args.append(f"--include-data-dir={webview2_vendor}=vendor/webview2")

    shaders_dir = ROOT / "ui" / "shaders"
    if shaders_dir.exists():
        args.append(f"--include-data-dir={shaders_dir}=ui/shaders")

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
